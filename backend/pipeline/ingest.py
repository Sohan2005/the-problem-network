import os
import re
import sys
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import PipelineRun
from db.queries import insert_raw_ideas
from ingestion import hn_ingest, stackexchange_ingest

# Each adapter module provides SOURCE, DEFAULT_MAX_ITEMS and fetch_candidates(*, budget_seconds, max_items, since=None)
ADAPTERS = [hn_ingest, stackexchange_ingest]
ERROR_MAX = 500

_CREDENTIALS = [
    (re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/@]+@\S*", re.I), "[redacted-url]"),
    (re.compile(r"\b((?:api_?)?key|password|passwd|pwd|token|access_token|secret)=[^&\s'\"]+", re.I), r"\1=[redacted]"),
    (re.compile(r"\b(host|server at)(\s*=\s*|\s+)\"?[^\s\"]+\"?", re.I), r"\1 [redacted]"),
]

def safe_error(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    for pattern, replacement in _CREDENTIALS:
        message = pattern.sub(replacement, message)
    return message[:ERROR_MAX]

def run_ingestion(db, total_budget_seconds) -> dict:
    """
    Run every adapter with an equal share of the time budget, store candidates via insert_raw_ideas,
    and log one pipeline_runs row per adapter. One adapter failing does not stop the others.
    """
    budget = total_budget_seconds / len(ADAPTERS)
    summary = {}
    for adapter in ADAPTERS:
        started_at = datetime.now(timezone.utc)
        fetched, result, status, error = 0, None, "ok", None
        try:
            candidates = adapter.fetch_candidates(budget_seconds=budget, max_items=adapter.DEFAULT_MAX_ITEMS)
            fetched = len(candidates)
            result = insert_raw_ideas(db, candidates)
        except Exception as e:
            db.rollback()
            status, error = "error", safe_error(e)
        inserted = result["inserted"] if result else 0
        db.add(PipelineRun(
            stage=f"ingest:{adapter.SOURCE}",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            rows_in=fetched,
            rows_out=inserted,
            status=status,
            error=error,
        ))
        db.commit()
        summary[adapter.SOURCE] = {
            "status": status,
            "fetched": fetched,
            "inserted": inserted,
            "skipped_duplicate": result["skipped_duplicate"] if result else 0,
            "rejected": len(result["rejected"]) if result else 0,
            "error": error,
        }
    return summary
