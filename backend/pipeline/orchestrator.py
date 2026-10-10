"""
One pipeline tick: ingest -> prefilter -> extract -> gates, then a top-up round when the buffer of passed, unpublished
briefs is low. Ingestion is the resumable search ladder in pipeline/sweep.py (incremental search, Way 1 phrase search,
Way 2 full sweep), given at least SHARE["ingest"] (45%) of the tick budget; the AI top-up only runs after it. Every stage
runs in its own try/except so one failure never stops the others; each stage logs its own pipeline_runs rows and the
tick logs one more with stage 'pipeline'.

Free Gemini quota (budget is $0): gemini-3.5-flash-lite allows 500 requests per day, gemini-embedding-001 1,000 per
day and 100 per minute. Free quotas reset at midnight Pacific, so both caps count today's pipeline_runs rows on the
America/Los_Angeles calendar day:
- EXTRACTION_DAILY_CAP: extraction calls per day, the sum of rows_in of today's 'extract' runs.
- AI_IDEA_CALLS_PER_DAY: AI idea generation calls per day, one per today's AI_IDEAS_STAGE run.
Extraction calls are at least extract.CALL_INTERVAL_SECONDS (5) apart, so at most 12 per minute; embedding calls of the
default client are at least gates.EMBED_INTERVAL_SECONDS (0.6) apart, so at most 100 per minute across gates and publish.
When a stage reports the quota exhausted, the remaining Gemini-using stages of the tick are skipped.
"""
import os
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import PipelineRun
from db.queries import insert_raw_ideas
from ingestion import ai_ideas
from llm.gemini import QuotaExhausted
from pipeline.extract import run_extraction
from pipeline.gates import run_gates
from pipeline.ingest import safe_error
from pipeline.prefilter import run_prefilter
from pipeline.publish import BUFFER_TARGET, candidates_query
from pipeline.sweep import run_sweep

STAGE = "pipeline"
PREFILTER_MAX_ITEMS = 500
EXTRACT_MAX_ITEMS = 40
GATES_MAX_ITEMS = 200
BUFFER_CRITICAL = 5  # below this the tick is logged as 'warn'; BUFFER_TARGET (15) comes from publish
MIN_STAGE_SECONDS = 30

QUOTA_TIMEZONE = ZoneInfo("America/Los_Angeles")
EXTRACTION_DAILY_CAP = 300
AI_IDEA_CALLS_PER_DAY = 3
AI_IDEAS_STAGE = "topup:ai_suggested"

# Share of the remaining budget each stage may use (ingest runs first, so it gets 45% of the whole tick).
SHARE = {"ingest": 0.45, "prefilter": 0.05, "extract": 0.6, "gates": 0.5, "topup": 0.5, "extract_again": 0.6}

def buffer_size(db) -> int:
    return candidates_query(db).count()

def quota_day_start(now: datetime) -> datetime:
    """Start of the current America/Los_Angeles calendar day, when the free Gemini quotas reset."""
    return now.astimezone(QUOTA_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)

def extraction_calls_today(db, now: datetime) -> int:
    return int(db.query(func.coalesce(func.sum(PipelineRun.rows_in), 0)).filter(
        PipelineRun.stage == "extract", PipelineRun.started_at >= quota_day_start(now)).scalar())

def ai_idea_calls_today(db, now: datetime) -> int:
    return db.query(PipelineRun.id).filter(
        PipelineRun.stage == AI_IDEAS_STAGE, PipelineRun.started_at >= quota_day_start(now)).count()

def topup_ai_ideas(db, *, llm_client, fetcher=None, budget_seconds) -> dict:
    """One AI idea call per top-up run, at most AI_IDEA_CALLS_PER_DAY per Pacific day; logs one AI_IDEAS_STAGE run per call."""
    now = datetime.now(timezone.utc)
    if ai_idea_calls_today(db, now) >= AI_IDEA_CALLS_PER_DAY:
        return {"status": "skipped", "reason": f"daily AI idea cap {AI_IDEA_CALLS_PER_DAY} reached"}
    if budget_seconds <= 0:
        return {"status": "skipped", "reason": "no budget"}
    avoid_titles = ai_ideas.load_avoid_titles(db)
    fetched, inserted, status, error, quota = 0, 0, "ok", None, False
    try:
        items = ai_ideas.fetch_candidates(budget_seconds=budget_seconds, max_items=ai_ideas.DEFAULT_MAX_ITEMS,
                                          avoid_titles=avoid_titles, llm_client=llm_client, now=now)
        fetched = len(items)
        inserted = insert_raw_ideas(db, items)["inserted"]
    except QuotaExhausted:
        db.rollback()
        status, error, quota = "warn", "quota", True
    except Exception as e:
        db.rollback()
        status, error = "error", safe_error(e)
    db.add(PipelineRun(stage=AI_IDEAS_STAGE, started_at=now, finished_at=datetime.now(timezone.utc),
                       rows_in=fetched, rows_out=inserted, status=status, error=error))
    db.commit()
    return {"status": status, "error": error, "fetched": fetched, "inserted": inserted, "quota": quota}

# Extra supply used when the buffer is low. Each entry is called as source(db, llm_client=..., fetcher=...,
# budget_seconds=...) and returns a summary dict.
TOPUP_SOURCES = [topup_ai_ideas]

def _quota(result) -> bool:
    return isinstance(result, dict) and bool(result.get("quota"))

def _failed(result) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "error":
        return True
    return any(isinstance(v, dict) and v.get("status") == "error" for v in result.values())

def run_pipeline(db, llm_client, embed_client, fetcher, total_budget_seconds, *, sweep_options=None,
                 extract_limit=None) -> dict:
    """
    Run one tick within total_budget_seconds and return a summary (stage results, buffer, status).
    sweep_options: keyword arguments for run_sweep (phrase and site limits, injected HTTP getters).
    extract_limit: at most this many rows extracted in the whole tick (extract and extract_again together).
    """
    deadline = time.monotonic() + total_budget_seconds
    started_at = datetime.now(timezone.utc)
    stages, failed = {}, []
    quota_hit = False
    extracted = 0

    def remaining():
        return max(0.0, deadline - time.monotonic())

    def stage(name, share, call, uses_gemini=False):
        nonlocal quota_hit
        if uses_gemini and quota_hit:
            stages[name] = {"status": "skipped", "reason": "quota"}
            return stages[name]
        budget = remaining() * share
        try:
            result = call(budget)
        except Exception as e:
            db.rollback()
            result = {"status": "error", "error": safe_error(e)}
        stages[name] = result
        if _failed(result):
            failed.append(name)
        quota_hit = quota_hit or _quota(result)
        return result

    def extract(budget):
        nonlocal extracted
        allowed = EXTRACTION_DAILY_CAP - extraction_calls_today(db, datetime.now(timezone.utc))
        if allowed <= 0:
            return {"status": "skipped", "reason": f"daily extraction cap {EXTRACTION_DAILY_CAP} reached"}
        max_items = min(EXTRACT_MAX_ITEMS, allowed)
        if extract_limit is not None:
            if extracted >= extract_limit:
                return {"status": "skipped", "reason": f"tick extraction limit {extract_limit} reached"}
            max_items = min(max_items, extract_limit - extracted)
        result = run_extraction(db, llm_client, max_items, budget)
        extracted += result.get("attempted", 0)
        return result

    stage("ingest", SHARE["ingest"], lambda budget: run_sweep(db, budget, **(sweep_options or {})))
    stage("prefilter", SHARE["prefilter"], lambda budget: run_prefilter(db, PREFILTER_MAX_ITEMS, budget))
    stage("extract", SHARE["extract"], extract, uses_gemini=True)
    stage("gates", SHARE["gates"], lambda budget: run_gates(db, embed_client, GATES_MAX_ITEMS, budget), uses_gemini=True)

    buffer = stage("buffer", 0, lambda _: buffer_size(db))
    topped_up = False
    if isinstance(buffer, int) and buffer < BUFFER_TARGET:
        topped_up = True
        for index, source in enumerate(TOPUP_SOURCES):
            name = f"topup:{getattr(source, '__name__', index)}"
            share = SHARE["topup"] / (len(TOPUP_SOURCES) - index)
            stage(name, share, lambda budget, source=source: source(db, llm_client=llm_client, fetcher=fetcher, budget_seconds=budget),
                  uses_gemini=True)
        if remaining() >= MIN_STAGE_SECONDS:
            stage("extract_again", SHARE["extract_again"], extract, uses_gemini=True)
        if remaining() >= MIN_STAGE_SECONDS:
            stage("gates_again", 1.0, lambda budget: run_gates(db, embed_client, GATES_MAX_ITEMS, budget), uses_gemini=True)
        buffer = stage("buffer_after_topup", 0, lambda _: buffer_size(db))

    buffer = buffer if isinstance(buffer, int) else None
    if failed:
        status, error = "error", f"stages failed: {', '.join(failed)}"
    elif buffer is not None and buffer < BUFFER_CRITICAL:
        status, error = "warn", f"buffer critical: {buffer} < {BUFFER_CRITICAL}"
    elif quota_hit:
        status, error = "warn", "quota"
    elif buffer is not None and buffer < BUFFER_TARGET:
        status, error = "ok", f"buffer low: {buffer} < {BUFFER_TARGET}"
    else:
        status, error = "ok", None
    try:
        db.add(PipelineRun(stage=STAGE, started_at=started_at, finished_at=datetime.now(timezone.utc),
                           rows_in=None, rows_out=buffer, status=status, error=error))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"status": status, "error": error, "buffer": buffer, "topped_up": topped_up, "failed_stages": failed,
            "quota": quota_hit, "stages": stages}
