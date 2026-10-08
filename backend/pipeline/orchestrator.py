"""
One pipeline tick: ingest (at most every 12 hours) -> prefilter -> extract -> gates, then a top-up round when the
buffer of passed, unpublished briefs is low. Every stage runs in its own try/except so one failure never stops
the others; each stage logs its own pipeline_runs rows and the tick logs one more with stage 'pipeline'.
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

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

    def remaining():
        return max(0.0, deadline - time.monotonic())

    def stage(name, share, call):
        budget = remaining() * share
        try:
            result = call(budget)
        except Exception as e:
            db.rollback()
            result = {"status": "error", "error": safe_error(e)}
        stages[name] = result
        if _failed(result):
            failed.append(name)
        return result

    if ingested_recently(db, started_at):
        stages["ingest"] = {"status": "skipped", "reason": "ingested within the last 12 hours"}
    else:
        stage("ingest", SHARE["ingest"], lambda budget: run_ingestion(db, budget))
    stage("prefilter", SHARE["prefilter"], lambda budget: run_prefilter(db, PREFILTER_MAX_ITEMS, budget))
    stage("extract", SHARE["extract"], lambda budget: run_extraction(db, llm_client, EXTRACT_MAX_ITEMS, budget))
    stage("gates", SHARE["gates"], lambda budget: run_gates(db, embed_client, fetcher, GATES_MAX_ITEMS, budget))

    buffer = stage("buffer", 0, lambda _: buffer_size(db))
    topped_up = False
    if isinstance(buffer, int) and buffer < BUFFER_TARGET:
        topped_up = True
        for index, source in enumerate(TOPUP_SOURCES):
            name = f"topup:{getattr(source, '__name__', index)}"
            share = SHARE["topup"] / (len(TOPUP_SOURCES) - index)
            stage(name, share, lambda budget, source=source: source(db, llm_client=llm_client, fetcher=fetcher, budget_seconds=budget))
        if remaining() >= MIN_STAGE_SECONDS:
            stage("extract_again", SHARE["extract_again"], lambda budget: run_extraction(db, llm_client, EXTRACT_MAX_ITEMS, budget))
        if remaining() >= MIN_STAGE_SECONDS:
            stage("gates_again", 1.0, lambda budget: run_gates(db, embed_client, fetcher, GATES_MAX_ITEMS, budget))
        buffer = stage("buffer_after_topup", 0, lambda _: buffer_size(db))

    buffer = buffer if isinstance(buffer, int) else None
    if failed:
        status, error = "error", f"stages failed: {', '.join(failed)}"
    elif buffer is not None and buffer < BUFFER_CRITICAL:
        status, error = "warn", f"buffer critical: {buffer} < {BUFFER_CRITICAL}"
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
            "stages": stages}
