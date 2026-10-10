"""
Resumable search ladder for the organic sources: Hacker News (Ask HN stories) and Stack Exchange (every site in
stackexchange_ingest.SITES), inside the 3-year window.

The work is cut into units. A unit is one search: (way, source, site, phrase or tag group, time window). Each tick the
ingestion stage walks the ladder below in order and runs the units that are due, until its time share is used up:

1. Incremental: the newest INCREMENTAL_DAYS (14) days, searched with the INCREMENTAL_PHRASES (40) strongest phrases
   (Hacker News, and every Stack Exchange site). Each of these units runs at most once every INCREMENTAL_EVERY_HOURS (6).
2. Way 1, phrase search, strongest phrases first: Hacker News searches each exact phrase over the whole 3-year window
   (one unit per phrase); Stack Exchange searches each phrase on each site over the whole 3-year window too (one unit
   per site and phrase; inside the unit the window is halved only when 10 pages still report more results).
   Hacker News and Stack Exchange units alternate so both sources move forward. With the current phrase bank that is
   869 Hacker News + 836 phrases x 7 sites = 5,852 Stack Exchange units, about 6,700 Way 1 units in total.
3. Way 2, full sweep, only once every Way 1 unit has been done: every Ask HN story, one calendar month per unit; on
   Stack Exchange, the questions carrying the site's recommendation/software/tool tags, per 6-month window.
4. Repeats: a finished unit whose window ends inside the last RECENT_WINDOW_DAYS (30) days is run again once every
   REPEAT_RECENT_HOURS (24), after all new work of the tick.

Progress is stateless: when a unit finishes, a pipeline_runs row is written with stage
'sweep:<way>:<source>:<site>:<key>:<window>', rows_in = candidates kept, rows_out = rows inserted, status 'ok'. A unit
with such an 'ok' row is skipped (apart from the repeats above), so the next tick resumes where this one stopped.

Stops: the time share running out ends the sweep for this tick. Stack Exchange quota below 1,500, a backoff longer than
the remaining time, throttling or request errors stop that source for the tick with status 'warn'; Algolia errors stop
Hacker News the same way. The sweep also stops once real pending rows (real source, passed prefilter, not yet extracted)
plus the rows inserted during the tick reach REAL_PENDING_TARGET (900). Every unit runs in its own try/except, so the
ladder never fails the tick. The AI top-up stays in the orchestrator and only runs after this stage, when the buffer of
passed, unpublished briefs is below BUFFER_TARGET.
"""
import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import func

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import PipelineRun, RawIdea
from db.queries import insert_raw_ideas
from ingestion import hn_ingest, stackexchange_ingest
from ingestion.search_terms import all_phrases, hn_phrases
from pipeline.extract import MAX_ATTEMPTS
from pipeline.ingest import safe_error
from pipeline.publish import AI_SOURCES

STAGE = "sweep"
STAGE_PREFIX = "sweep:"
HN, SE = "hackernews", "stackexchange"
HN_SITE = "askhn"
INCREMENTAL, WAY1, WAY2 = "incremental", "way1", "way2"
INCREMENTAL_EVERY_HOURS = 6
INCREMENTAL_DAYS = 14
INCREMENTAL_PHRASES = 40
REPEAT_RECENT_HOURS = 24
RECENT_WINDOW_DAYS = 30
REAL_PENDING_TARGET = 900
WINDOW_YEARS = 3
SE_WINDOW_MONTHS = 6
HN_SWEEP_WINDOW_MONTHS = 1
MIN_UNIT_SECONDS = 10
STAGE_MAX = 200
KEY_MAX = 60
_SAFE_KEY = re.compile(r"[a-z0-9 '.+;_-]+")

def unit_key(text: str) -> str:
    """The phrase or tag group as written when short and free of separators, otherwise 'h' + 12 hex digits of its SHA-1."""
    if len(text) <= KEY_MAX and _SAFE_KEY.fullmatch(text):
        return text
    return "h" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]

@dataclass
class Unit:
    way: str
    source: str
    site: str
    key: str
    window: str
    start_ts: int
    end_ts: int
    run: Callable = field(repr=False, compare=False)  # run(budget_seconds) -> adapter result dict

    @property
    def stage(self) -> str:
        return f"{STAGE_PREFIX}{self.way}:{self.source}:{self.site}:{unit_key(self.key)}:{self.window}"[:STAGE_MAX]

def _ts(value: datetime) -> int:
    return int(value.timestamp())

def _window_start(now: datetime) -> datetime:
    return now - timedelta(days=WINDOW_YEARS * 365)

def aligned_windows(now: datetime, months: int) -> list:
    """(label, start_ts, end_ts) for calendar-aligned blocks of `months` inside the 3-year window, newest first, clipped to it."""
    limit = _window_start(now)
    index = (now.year * 12 + now.month - 1) // months
    windows = []
    while True:
        first, last = index * months, (index + 1) * months
        block_start = datetime(first // 12, first % 12 + 1, 1, tzinfo=timezone.utc)
        block_end = datetime(last // 12, last % 12 + 1, 1, tzinfo=timezone.utc)
        if block_end <= limit:
            return windows
        label = f"{block_start:%Y-%m}" if months == 1 else f"{block_start:%Y-%m}+{months}m"
        windows.append((label, _ts(max(block_start, limit)), _ts(min(block_end, now))))
        index -= 1

def _interleave(*lists):
    """Round-robin over the lists until all are used up."""
    iterators = [iter(items) for items in lists]
    while iterators:
        for iterator in list(iterators):
            try:
                yield next(iterator)
            except StopIteration:
                iterators.remove(iterator)

def _hn_phrase_run(phrase, start_ts, end_ts, get):
    return lambda budget: hn_ingest.phrase_search(phrase, budget_seconds=budget, start_ts=start_ts, end_ts=end_ts, get=get)

def _hn_sweep_run(start_ts, end_ts, get):
    return lambda budget: hn_ingest.full_sweep(budget_seconds=budget, start_ts=start_ts, end_ts=end_ts, get=get)

def _se_phrase_run(site, phrase, start_ts, end_ts, get):
    return lambda budget: stackexchange_ingest.phrase_search(site, phrase, budget_seconds=budget, start_ts=start_ts,
                                                             end_ts=end_ts, get=get)

def _se_tag_run(site, tags, start_ts, end_ts, get):
    return lambda budget: stackexchange_ingest.tag_search(site, tags, budget_seconds=budget, start_ts=start_ts,
                                                          end_ts=end_ts, get=get)

def incremental_units(now: datetime, hn_get=None, se_get=None, hn_list=None, se_list=None, se_sites=None) -> list:
    start_ts, end_ts = _ts(now - timedelta(days=INCREMENTAL_DAYS)), _ts(now)
    window = f"{INCREMENTAL_DAYS}d"
    hn_units = [Unit(INCREMENTAL, HN, HN_SITE, p, window, start_ts, end_ts, _hn_phrase_run(p, start_ts, end_ts, hn_get))
                for p in (hn_phrases() if hn_list is None else hn_list)[:INCREMENTAL_PHRASES]]
    se_units = [Unit(INCREMENTAL, SE, site["site"], p, window, start_ts, end_ts, _se_phrase_run(site, p, start_ts, end_ts, se_get))
                for p in (all_phrases() if se_list is None else se_list)[:INCREMENTAL_PHRASES]
                for site in (stackexchange_ingest.SITES if se_sites is None else se_sites)]
    return list(_interleave(hn_units, se_units))

def hn_way1_units(now: datetime, phrases=None, get=None) -> list:
    start_ts, end_ts = _ts(_window_start(now)), _ts(now)
    return [Unit(WAY1, HN, HN_SITE, p, f"{WINDOW_YEARS}y", start_ts, end_ts, _hn_phrase_run(p, start_ts, end_ts, get))
            for p in (hn_phrases() if phrases is None else phrases)]

def se_way1_units(now: datetime, phrases=None, sites=None, get=None) -> list:
    start_ts, end_ts = _ts(_window_start(now)), _ts(now)
    return [Unit(WAY1, SE, site["site"], p, f"{WINDOW_YEARS}y", start_ts, end_ts, _se_phrase_run(site, p, start_ts, end_ts, get))
            for p in (all_phrases() if phrases is None else phrases)
            for site in (stackexchange_ingest.SITES if sites is None else sites)]

def way1_units(now: datetime, hn_get=None, se_get=None, hn_list=None, se_list=None, se_sites=None) -> list:
    return list(_interleave(hn_way1_units(now, hn_list, get=hn_get), se_way1_units(now, se_list, se_sites, get=se_get)))

def hn_way2_units(now: datetime, get=None) -> list:
    return [Unit(WAY2, HN, HN_SITE, "all", label, start_ts, end_ts, _hn_sweep_run(start_ts, end_ts, get))
            for label, start_ts, end_ts in aligned_windows(now, HN_SWEEP_WINDOW_MONTHS)]

def se_way2_units(now: datetime, tags_for, get=None):
    """Generated lazily: tags_for(site) makes the site's one /tags call (or returns None to skip the site)."""
    windows = aligned_windows(now, SE_WINDOW_MONTHS)
    for site in stackexchange_ingest.SITES:
        tags = tags_for(site) or []
        for i in range(0, len(tags), stackexchange_ingest.TAGS_PER_CALL):
            group = tags[i:i + stackexchange_ingest.TAGS_PER_CALL]
            for label, start_ts, end_ts in windows:
                yield Unit(WAY2, SE, site["site"], ";".join(group), label, start_ts, end_ts,
                           _se_tag_run(site, group, start_ts, end_ts, get))

def way2_units(now: datetime, tags_for, hn_get=None, se_get=None):
    return _interleave(hn_way2_units(now, get=hn_get), se_way2_units(now, tags_for, get=se_get))

def repeat_interval(unit: Unit, now: datetime):
    """How often a finished unit is redone: incremental units every 6 hours, recent windows every 24 hours, else never."""
    if unit.way == INCREMENTAL:
        return timedelta(hours=INCREMENTAL_EVERY_HOURS)
    if unit.end_ts >= _ts(now - timedelta(days=RECENT_WINDOW_DAYS)):
        return timedelta(hours=REPEAT_RECENT_HOURS)
    return None

def load_progress(db) -> dict:
    """stage -> latest started_at of its 'ok' sweep rows."""
    rows = (db.query(PipelineRun.stage, func.max(PipelineRun.started_at))
            .filter(PipelineRun.stage.like(STAGE_PREFIX + "%"), PipelineRun.status == "ok")
            .group_by(PipelineRun.stage).all())
    return {stage: started_at for stage, started_at in rows}

def real_pending(db) -> int:
    return db.query(RawIdea.id).filter(
        RawIdea.source.notin_(AI_SOURCES),
        RawIdea.passed_prefilter.is_(True),
        RawIdea.processed_at.is_(None),
        RawIdea.gate_status == "pending",
        RawIdea.extraction_attempts < MAX_ATTEMPTS,
    ).count()

def plan(now: datetime, progress: dict, tags_for, hn_get=None, se_get=None, hn_list=None, se_list=None, se_sites=None):
    """
    Due units in ladder order: incremental, new Way 1, new Way 2 (only when Way 1 is complete), then repeats.
    hn_list, se_list and se_sites narrow the incremental and Way 1 units to those phrases and sites; Way 2 still waits
    for the complete, unnarrowed Way 1.
    """
    def new(units):
        return (u for u in units if u.stage not in progress)

    def repeats(units):
        for u in units:
            interval = repeat_interval(u, now) if u.stage in progress else None
            if interval is not None and now - progress[u.stage] >= interval:
                yield u

    yield from (u for u in incremental_units(now, hn_get, se_get, hn_list, se_list, se_sites)
                if u.stage not in progress or now - progress[u.stage] >= repeat_interval(u, now))
    first = way1_units(now, hn_get, se_get, hn_list, se_list, se_sites)
    narrowed = any(limit is not None for limit in (hn_list, se_list, se_sites))
    way1_complete = all(u.stage in progress for u in (way1_units(now) if narrowed else first))
    yield from new(first)
    if way1_complete:
        yield from new(way2_units(now, tags_for, hn_get, se_get))
    yield from repeats(first)
    if way1_complete:
        yield from repeats(way2_units(now, tags_for, hn_get, se_get))

def _new_summary() -> dict:
    return {"status": "ok", "reason": None, "units_ok": 0, "units_warn": 0, "seen": 0, "candidates": 0, "inserted": 0,
            "skipped_duplicate": 0, "rejected": 0, "calls": {HN: 0, SE: 0}, "stopped": {}, "sites": {},
            "real_pending": None, "se_quota_remaining": None}

def run_units(db, units, *, budget_seconds, pending_start=0, summary=None, pending_target=REAL_PENDING_TARGET) -> dict:
    """
    Run units in order within budget_seconds, store their candidates with insert_raw_ideas and write one pipeline_runs
    row per unit ('ok' when finished, 'warn' when stopped). Never raises; see the module docstring for the stops.
    """
    deadline = time.monotonic() + budget_seconds
    summary = summary if summary is not None else _new_summary()
    stopped = summary["stopped"]
    iterator = iter(units)
    while True:
        if deadline - time.monotonic() < MIN_UNIT_SECONDS:
            summary["reason"] = summary["reason"] or "budget"
            break
        if pending_start + summary["inserted"] >= pending_target:
            summary["reason"] = summary["reason"] or "real pending target reached"
            break
        if len(stopped) == 2:
            break
        try:
            unit = next(iterator)
        except StopIteration:
            break
        except Exception as e:
            db.rollback()
            summary["status"], summary["reason"] = "warn", f"planning failed: {safe_error(e)}"
            break
        if unit.source in stopped:
            continue
        started_at = datetime.now(timezone.utc)
        result, inserted, duplicates = None, 0, 0
        try:
            result = unit.run(deadline - time.monotonic())
            stored = insert_raw_ideas(db, result["candidates"])
            inserted, duplicates = stored["inserted"], stored["skipped_duplicate"]
            summary["rejected"] += len(stored["rejected"])
            status, error = result["status"], result["reason"]
        except Exception as e:
            db.rollback()
            status, error = "warn", safe_error(e)
        result = result or {}
        candidates = len(result.get("candidates") or [])
        site_stats = summary["sites"].setdefault(f"{unit.source}:{unit.site}", {"calls": 0, "seen": 0, "candidates": 0,
                                                                                  "inserted": 0, "skipped_duplicate": 0})
        for key, value in (("calls", result.get("calls", 0)), ("seen", result.get("seen", 0)), ("candidates", candidates),
                           ("inserted", inserted), ("skipped_duplicate", duplicates)):
            site_stats[key] += value
            if key in summary and key != "calls":
                summary[key] += value
        summary["calls"][unit.source] += result.get("calls", 0)
        if result.get("quota_remaining") is not None:
            summary["se_quota_remaining"] = result["quota_remaining"]
        summary["units_ok" if status == "ok" else "units_warn"] += 1
        try:
            db.add(PipelineRun(stage=unit.stage, started_at=started_at, finished_at=datetime.now(timezone.utc),
                               rows_in=candidates, rows_out=inserted, status=status, error=error))
            db.commit()
        except Exception as e:
            db.rollback()
            summary["status"], summary["reason"] = "warn", f"progress row failed: {safe_error(e)}"
            break
        if status != "ok" and error == "budget":
            summary["reason"] = summary["reason"] or "budget"
            break
        if status != "ok" or result.get("quota_stop"):
            stopped[unit.source] = "quota" if result.get("quota_stop") else error
            summary["status"] = "warn"
    return summary

def run_sweep(db, budget_seconds, *, now=None, hn_get=None, se_get=None, hn_list=None, se_list=None,
              se_sites=None, pending_target=REAL_PENDING_TARGET) -> dict:
    """
    Walk the ladder for one tick within budget_seconds, log a summary row with stage 'sweep' and return the summary.
    hn_list / se_list (phrases) and se_sites (entries of stackexchange_ingest.SITES) narrow the ladder; see plan.
    pending_target replaces REAL_PENDING_TARGET as the real-pending stop.
    """
    deadline = time.monotonic() + budget_seconds
    started_at = datetime.now(timezone.utc)
    now = now or started_at
    summary = _new_summary()
    tag_cache = {}

    def tags_for(site):
        if SE in summary["stopped"] or deadline - time.monotonic() < MIN_UNIT_SECONDS:
            return None
        result = stackexchange_ingest.discover_tags(site, budget_seconds=deadline - time.monotonic(), cache=tag_cache,
                                                    get=se_get)
        summary["calls"][SE] += result["calls"]
        if result["status"] != "ok" or result["quota_stop"]:
            summary["stopped"][SE] = "quota" if result["quota_stop"] else result["reason"]
            summary["status"] = "warn"
        return result["tags"] if result["status"] == "ok" else None

    try:
        summary["real_pending"] = pending = real_pending(db)
        if pending >= pending_target:
            summary["status"], summary["reason"] = "skipped", f"real pending rows {pending} >= {pending_target}"
        else:
            units = plan(now, load_progress(db), tags_for, hn_get, se_get, hn_list, se_list, se_sites)
            run_units(db, units, budget_seconds=deadline - time.monotonic(), pending_start=pending, summary=summary,
                      pending_target=pending_target)
    except Exception as e:
        db.rollback()
        summary["status"], summary["reason"] = "warn", safe_error(e)
    if summary["stopped"] and summary["reason"] is None:
        summary["reason"] = "; ".join(f"{source}: {why}" for source, why in summary["stopped"].items())
    try:
        db.add(PipelineRun(stage=STAGE, started_at=started_at, finished_at=datetime.now(timezone.utc),
                           rows_in=summary["candidates"], rows_out=summary["inserted"],
                           status=summary["status"], error=summary["reason"]))
        db.commit()
    except Exception:
        db.rollback()
    return summary
