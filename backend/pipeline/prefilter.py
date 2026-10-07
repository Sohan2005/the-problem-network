"""
Step 2 prefilter: cheap heuristics applied before any LLM call.

passed_prefilter: NULL = not yet prefiltered, TRUE = passed, FALSE = rejected (prefilter_reject_reason says why).
Rules are rebuilt from prefilter_raw_ideas.py and the reason strings recorded on the July 2026 run.
They lean towards passing: extraction and the gates catch what slips through.

Loosened against the historical record (2026-10): MIN_WORDS 40 -> 20 and rule_no_intent disabled, because at
40 words / with the intent check they rejected items later extracted as valid (shortest valid: 23 words; several
valid Stack Exchange and HN items contain none of INTENT_SIGNALS).
"""
import os
import sys
import time
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import PipelineRun, RawIdea
from pipeline.ingest import safe_error

STAGE = "prefilter"
COMMIT_EVERY = 100
MIN_WORDS = 20
MIN_WORDS_BEYOND_TRIGGER = 8

INTENT_SIGNALS = [
    "idea", "build", "app", "website", "tool",
    "wish there was", "alternative to", "someone should build",
    "would gladly pay", "i would pay", "shut up and take my money",
    "scratch my own itch", "frustratingly bad", "hate the current options",
    "gap in the market", "surprised no one sells",
]

TRIGGER_PHRASES = [
    "wish there was a tool", "someone should build", "is there a lightweight alternative",
    "gap in the market", "surprised no one sells", "would gladly pay",
    "i would pay monthly", "shut up and take my money", "is there a paid version",
    "scratch my own itch", "frustratingly bad", "hate the current options",
    "why is there no open source alternative", "i ended up writing a script",
]

REASON_TOO_SHORT = "Too short ({words} words < {minimum} minimum)"
REASON_TOO_SHORT_BEYOND_TRIGGER = (
    "Too short ({words} words), insufficient context beyond trigger phrase ({beyond} words < {minimum} minimum)"
)
REASON_NO_INTENT = "No buildable intent signals found"

def matching_comment(raw_text: str) -> str:
    """The MATCHING COMMENT portion of comment-mode text, otherwise the whole text."""
    if "MATCHING COMMENT:" in raw_text:
        return raw_text.split("MATCHING COMMENT:")[1].strip()
    return raw_text

def count_words(text: str) -> int:
    return len(text.split())

def first_trigger_phrase(raw_text: str):
    text_lower = raw_text.lower()
    return next((phrase for phrase in TRIGGER_PHRASES if phrase in text_lower), None)

def count_words_beyond_phrase(text: str, phrase: str) -> int:
    text_lower = text.lower()
    if phrase in text_lower:
        return len(text_lower.replace(phrase, "").split())
    return len(text.split())

def has_buildable_intent(raw_text: str) -> bool:
    text_lower = raw_text.lower()
    return any(signal in text_lower for signal in INTENT_SIGNALS)

def rule_too_short(raw_text: str):
    """Reject bodies under MIN_WORDS, unless a trigger phrase comes with MIN_WORDS_BEYOND_TRIGGER words of context."""
    body = matching_comment(raw_text)
    words = count_words(body)
    if words >= MIN_WORDS:
        return None
    phrase = first_trigger_phrase(raw_text)
    if phrase is None:
        return REASON_TOO_SHORT.format(words=words, minimum=MIN_WORDS)
    beyond = count_words_beyond_phrase(body, phrase)
    if beyond < MIN_WORDS_BEYOND_TRIGGER:
        return REASON_TOO_SHORT_BEYOND_TRIGGER.format(words=words, beyond=beyond, minimum=MIN_WORDS_BEYOND_TRIGGER)
    return None

def rule_no_intent(raw_text: str):
    """Reject text with none of the buildable-intent signals. Disabled: see module docstring."""
    return None if has_buildable_intent(raw_text) else REASON_NO_INTENT

RULES = [rule_too_short]

def evaluate(raw_text: str):
    """Returns (passed, reason); reason is None when passed."""
    for rule in RULES:
        reason = rule(raw_text or "")
        if reason:
            return False, reason
    return True, None

def run_prefilter(db, max_items, budget_seconds) -> dict:
    """
    Prefilter rows not yet prefiltered (passed_prefilter IS NULL), oldest first. Rows already extracted
    or past the pending gate are left alone. Logs one pipeline_runs row and returns a summary.
    """
    deadline = time.monotonic() + budget_seconds
    started_at = datetime.now(timezone.utc)
    examined = passed = 0  # committed counts only
    stopped_by_budget = False
    status, error = "ok", None
    try:
        rows = (
            db.query(RawIdea)
            .filter(RawIdea.passed_prefilter.is_(None), RawIdea.processed_at.is_(None), RawIdea.gate_status == "pending")
            .order_by(RawIdea.fetched_at.asc().nullsfirst(), RawIdea.id.asc())
            .limit(max_items)
            .all()
        )
        batch_examined = batch_passed = 0
        for row in rows:
            if time.monotonic() >= deadline:
                stopped_by_budget = True
                break
            row.passed_prefilter, row.prefilter_reject_reason = evaluate(row.raw_text)
            batch_examined += 1
            batch_passed += row.passed_prefilter
            if batch_examined == COMMIT_EVERY:
                db.commit()
                examined, passed = examined + batch_examined, passed + batch_passed
                batch_examined = batch_passed = 0
        db.commit()
        examined, passed = examined + batch_examined, passed + batch_passed
    except Exception as e:
        db.rollback()
        status, error = "error", safe_error(e)

    db.add(PipelineRun(stage=STAGE, started_at=started_at, finished_at=datetime.now(timezone.utc),
                       rows_in=examined, rows_out=passed, status=status, error=error))
    db.commit()
    return {"status": status, "examined": examined, "passed": passed, "rejected": examined - passed,
            "stopped_by_budget": stopped_by_budget, "error": error}
