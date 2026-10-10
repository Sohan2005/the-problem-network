"""
Step 3 extraction: one synchronous LLM call per prefiltered row, using the prompt and parser in llm/translate.py.

Each row gets at most MAX_ATTEMPTS calls: extraction_attempts is incremented and committed before the call,
so a crash mid-call still counts. Gate, ready and published columns are never touched here.

Rows are chosen by rank: real sources before AI_SOURCES, then the local intent score (computed on the fly from
raw_title and raw_text, highest first), then source_date (newest first).

When Gemini reports its free quota exhausted, the stage stops at once, refunds that row's attempt (it stays
pending) and logs a 'warn' run with the note 'quota'.
"""
import os
import sys
import time
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import PipelineRun, RawIdea
from llm.gemini import GeminiClient as _GeminiClient, QuotaExhausted
from llm.translate import FORUM_MODEL, build_forum_prompt, parse_forum_response
from pipeline.ingest import ERROR_MAX, safe_error
from pipeline.prefilter import row_intent_score
from pipeline.publish import AI_SOURCES

STAGE = "extract"
QUOTA_NOTE = "quota"
MAX_ATTEMPTS = 3
CALL_INTERVAL_SECONDS = 5  # at most 12 calls per minute, also across runs in one process (extract, extract_again)
_EPOCH = datetime(1970, 1, 1)
_last_call_end = None  # time.monotonic() when the latest extraction call in this process returned

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

def rank_key(row):
    """Sort key over (id, source, raw_title, raw_text, source_date): real sources, intent score desc, source_date desc."""
    date = row.source_date
    return (row.source in AI_SOURCES, -row_intent_score(row.raw_title, row.raw_text),
            date is None, -(date - _EPOCH).total_seconds() if date is not None else 0, row.id)

def ranked_ids(db, max_items) -> list:
    """Ids of the top max_items rows of the eligible pool (fewer than MAX_ATTEMPTS attempts) by rank_key."""
    pool = (_eligible(db.query(RawIdea.id, RawIdea.source, RawIdea.raw_title, RawIdea.raw_text, RawIdea.source_date))
            .filter(RawIdea.extraction_attempts < MAX_ATTEMPTS).all())
    return [row.id for row in sorted(pool, key=rank_key)[:max_items]]

def _pause(deadline: float):
    """Sleep until CALL_INTERVAL_SECONDS have passed since the previous extraction call (or the deadline)."""
    if _last_call_end is not None and CALL_INTERVAL_SECONDS:
        wait = _last_call_end + CALL_INTERVAL_SECONDS - time.monotonic()
        time.sleep(max(0, min(wait, deadline - time.monotonic())))

def _generate(llm_client, prompt: str) -> str:
    global _last_call_end
    try:
        return llm_client.generate(prompt)
    finally:
        _last_call_end = time.monotonic()

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
    Extract prefiltered, unprocessed, pending rows with fewer than MAX_ATTEMPTS attempts, best ranked first (rank_key).
    One failing row never stops the run. Logs one pipeline_runs row and returns a summary.
    """
    deadline = time.monotonic() + budget_seconds
    started_at = datetime.now(timezone.utc)
    summary = {"attempted": 0, "succeeded": 0, "failed": 0, "gave_up": 0, "valid": 0, "needs_rescope": 0,
               "rejected": 0, "exhausted": 0, "stopped_by_budget": False, "quota": False}
    status, error, last_item_error = "ok", None, None
    try:
        summary["exhausted"] = _eligible(db.query(RawIdea)).filter(RawIdea.extraction_attempts >= MAX_ATTEMPTS).count()
        row_ids = ranked_ids(db, max_items)
        for row_id in row_ids:
            _pause(deadline)
            if time.monotonic() >= deadline:
                summary["stopped_by_budget"] = True
                break
            row = db.get(RawIdea, row_id)
            row.extraction_attempts += 1
            db.commit()
            summary["attempted"] += 1
            try:
                prompt = build_forum_prompt(row.raw_text, row.source_url, row.source)
                _apply_result(row, parse_forum_response(_generate(llm_client, prompt)))
                db.commit()
            except QuotaExhausted:
                db.rollback()
                row = db.get(RawIdea, row_id)
                row.extraction_attempts = max(0, row.extraction_attempts - 1)
                db.commit()
                summary["attempted"] -= 1
                summary["quota"] = True
                break
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
    if status == "ok" and summary["quota"]:
        status, error = "warn", QUOTA_NOTE if error is None else f"{QUOTA_NOTE}; {error}"[:ERROR_MAX]
    db.add(PipelineRun(stage=STAGE, started_at=started_at, finished_at=datetime.now(timezone.utc),
                       rows_in=summary["attempted"], rows_out=summary["succeeded"], status=status, error=error))
    db.commit()
    return {"status": status, "error": error, **summary}
