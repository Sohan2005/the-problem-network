"""
One pipeline tick: ingest (at most every 12 hours) -> prefilter -> extract -> gates, then a top-up round when the
buffer of passed, unpublished briefs is low. Every stage runs in its own try/except so one failure never stops
the others; each stage logs its own pipeline_runs rows and the tick logs one more with stage 'pipeline'.

Free Gemini quota (budget is $0; these caps are starting values, to be adjusted against the limits shown in
AI Studio). Free quotas reset at midnight Pacific, so both caps count today's pipeline_runs rows on the
America/Los_Angeles calendar day:
- EXTRACTION_DAILY_CAP: extraction calls per day, the sum of rows_in of today's 'extract' runs.
- AI_IDEA_CALLS_PER_DAY: AI idea generation calls per day, one per today's AI_IDEAS_STAGE run.
When a stage reports the quota exhausted, the remaining Gemini-using stages of the tick are skipped.
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import PipelineRun
from pipeline.extract import run_extraction
from pipeline.gates import run_gates
from pipeline.ingest import run_ingestion, safe_error
from pipeline.prefilter import run_prefilter
from pipeline.publish import candidates_query

STAGE = "pipeline"
INGEST_INTERVAL = timedelta(hours=12)
PREFILTER_MAX_ITEMS = 500
EXTRACT_MAX_ITEMS = 40
GATES_MAX_ITEMS = 200
BUFFER_TARGET = 30
BUFFER_CRITICAL = 10
MIN_STAGE_SECONDS = 30

QUOTA_TIMEZONE = ZoneInfo("America/Los_Angeles")
EXTRACTION_DAILY_CAP = 80
AI_IDEA_CALLS_PER_DAY = 3
AI_IDEAS_STAGE = "topup:ai_suggested"

# Share of the remaining budget each stage may use.
SHARE = {"ingest": 0.25, "prefilter": 0.05, "extract": 0.6, "gates": 0.5, "topup": 0.5, "extract_again": 0.6}

# Extra supply used when the buffer is low. Each entry is called as source(db, llm_client=..., fetcher=...,
# budget_seconds=...) and returns a summary dict; the grounding task adds the first one.
TOPUP_SOURCES = []

def buffer_size(db) -> int:
    return candidates_query(db).count()

def ingested_recently(db, now: datetime) -> bool:
    return db.query(PipelineRun.id).filter(
        PipelineRun.stage.like("ingest:%"),
        PipelineRun.status == "ok",
        PipelineRun.started_at >= now - INGEST_INTERVAL,
    ).first() is not None

def quota_day_start(now: datetime) -> datetime:
    """Start of the current America/Los_Angeles calendar day, when the free Gemini quotas reset."""
    return now.astimezone(QUOTA_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)

def extraction_calls_today(db, now: datetime) -> int:
    return int(db.query(func.coalesce(func.sum(PipelineRun.rows_in), 0)).filter(
        PipelineRun.stage == "extract", PipelineRun.started_at >= quota_day_start(now)).scalar())

def ai_idea_calls_today(db, now: datetime) -> int:
    return db.query(PipelineRun.id).filter(
        PipelineRun.stage == AI_IDEAS_STAGE, PipelineRun.started_at >= quota_day_start(now)).count()

def _quota(result) -> bool:
    return isinstance(result, dict) and bool(result.get("quota"))

def _failed(result) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") == "error":
        return True
    return any(isinstance(v, dict) and v.get("status") == "error" for v in result.values())

def run_pipeline(db, llm_client, embed_client, fetcher, total_budget_seconds) -> dict:
    """Run one tick within total_budget_seconds and return a summary (stage results, buffer, status)."""
    deadline = time.monotonic() + total_budget_seconds
    started_at = datetime.now(timezone.utc)
    stages, failed = {}, []
    quota_hit = False

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
        allowed = EXTRACTION_DAILY_CAP - extraction_calls_today(db, datetime.now(timezone.utc))
        if allowed <= 0:
            return {"status": "skipped", "reason": f"daily extraction cap {EXTRACTION_DAILY_CAP} reached"}
        return run_extraction(db, llm_client, min(EXTRACT_MAX_ITEMS, allowed), budget)

    if ingested_recently(db, started_at):
        stages["ingest"] = {"status": "skipped", "reason": "ingested within the last 12 hours"}
    else:
        stage("ingest", SHARE["ingest"], lambda budget: run_ingestion(db, budget))
    stage("prefilter", SHARE["prefilter"], lambda budget: run_prefilter(db, PREFILTER_MAX_ITEMS, budget))
    stage("extract", SHARE["extract"], extract, uses_gemini=True)
    stage("gates", SHARE["gates"], lambda budget: run_gates(db, embed_client, fetcher, GATES_MAX_ITEMS, budget), uses_gemini=True)

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
            stage("gates_again", 1.0, lambda budget: run_gates(db, embed_client, fetcher, GATES_MAX_ITEMS, budget), uses_gemini=True)
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
