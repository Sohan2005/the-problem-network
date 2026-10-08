"""
Step 3 extraction: one synchronous LLM call per prefiltered row, using the prompt and parser in llm/translate.py.

Each row gets at most MAX_ATTEMPTS calls: extraction_attempts is incremented and committed before the call,
so a crash mid-call still counts. Gate, ready and published columns are never touched here.
"""
import os
import sys
import time
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import PipelineRun, RawIdea
from llm.gemini import GeminiClient as _GeminiClient
from llm.translate import FORUM_MODEL, build_forum_prompt, parse_forum_response
from pipeline.ingest import ERROR_MAX, safe_error

STAGE = "extract"
MAX_ATTEMPTS = 3
CALL_INTERVAL_SECONDS = 5  # Free-tier rate limit, same pause as the old extraction scripts

class GeminiClient(_GeminiClient):
    """Default LLM client. Anything with generate(prompt) -> str can be passed instead (tests use a fake)."""

    def __init__(self, model_name: str = FORUM_MODEL, timeout_seconds: int = 60):
        super().__init__(model_name=model_name, timeout_seconds=timeout_seconds)

def _eligible(query):
    return query.filter(
        RawIdea.processed_at.is_(None),
        RawIdea.gate_status == "pending",
        RawIdea.passed_prefilter.is_(True),
    )

def _text(value):
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return value

def _clip(value, limit: int):
    return value[:limit] if isinstance(value, str) else value

def _apply_result(row, result: dict):
    is_valid = result["is_valid_idea"]
    row.is_valid_idea = str(is_valid).lower() if isinstance(is_valid, bool) else is_valid
    row.rejection_reason = result["rejection_reason"]
    row.original_ask = result["original_ask"]
    row.rescoped_version = result["rescoped_version"]
    row.rescope_reason = result["rescope_reason"]
    row.extracted_title = _clip(result["title"], 500)
    row.problem_summary = result["problem_summary"]
    row.target_user = _clip(result["target_user"], 300)
    row.suggested_features = result["suggested_features"]
    row.difficulty_estimate = result["difficulty_estimate"]
    row.suggested_tech_stack = result["suggested_tech_stack"]
    row.learning_outcomes = result["learning_outcomes"]
    row.what_youll_need = _text(result.get("what_youll_need"))
    row.how_to_begin = _text(result.get("how_to_begin"))
    row.processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.last_error = None

def run_extraction(db, llm_client, max_items, budget_seconds) -> dict:
    """
    Extract prefiltered, unprocessed, pending rows with fewer than MAX_ATTEMPTS attempts, oldest first.
    One failing row never stops the run. Logs one pipeline_runs row and returns a summary.
    """
    deadline = time.monotonic() + budget_seconds
    started_at = datetime.now(timezone.utc)
    summary = {"attempted": 0, "succeeded": 0, "failed": 0, "gave_up": 0, "valid": 0, "needs_rescope": 0,
               "rejected": 0, "exhausted": 0, "stopped_by_budget": False}
    status, error, last_item_error = "ok", None, None
    try:
        summary["exhausted"] = _eligible(db.query(RawIdea)).filter(RawIdea.extraction_attempts >= MAX_ATTEMPTS).count()
        row_ids = [
            row_id for (row_id,) in _eligible(db.query(RawIdea.id))
            .filter(RawIdea.extraction_attempts < MAX_ATTEMPTS)
            .order_by(RawIdea.fetched_at.asc().nullsfirst(), RawIdea.id.asc())
            .limit(max_items)
        ]
        for index, row_id in enumerate(row_ids):
            if index and CALL_INTERVAL_SECONDS:
                time.sleep(max(0, min(CALL_INTERVAL_SECONDS, deadline - time.monotonic())))
            if time.monotonic() >= deadline:
                summary["stopped_by_budget"] = True
                break
            row = db.get(RawIdea, row_id)
            row.extraction_attempts += 1
            db.commit()
            summary["attempted"] += 1
            try:
                prompt = build_forum_prompt(row.raw_text, row.source_url, row.source)
                _apply_result(row, parse_forum_response(llm_client.generate(prompt)))
                db.commit()
            except Exception as e:
                db.rollback()
                last_item_error = safe_error(e)
                row = db.get(RawIdea, row_id)
                row.last_error = last_item_error
                db.commit()
                summary["failed"] += 1
                summary["gave_up"] += row.extraction_attempts >= MAX_ATTEMPTS
                continue
            summary["succeeded"] += 1
            summary[{"true": "valid", "needs_rescope": "needs_rescope"}.get(row.is_valid_idea, "rejected")] += 1
    except Exception as e:
        db.rollback()
        status, error = "error", safe_error(e)

    if error is None and summary["failed"]:
        error = f"{summary['failed']} item(s) failed; last: {last_item_error}"[:ERROR_MAX]
    db.add(PipelineRun(stage=STAGE, started_at=started_at, finished_at=datetime.now(timezone.utc),
                       rows_in=summary["attempted"], rows_out=summary["succeeded"], status=status, error=error))
    db.commit()
    return {"status": status, "error": error, **summary}
