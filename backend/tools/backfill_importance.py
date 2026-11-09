"""
One-time backfill of briefs.importance (migration 003) for briefs published before the pipeline rated them.
Uses the same prompt, rules and stored format as pipeline/importance.py. One Gemini call per brief,
CALL_INTERVAL_SECONDS apart; a quota error stops the run cleanly and a rerun continues with the briefs still unrated.

The default is a dry run: it rates up to --limit unrated briefs and prints the level each would get, inside a
read-only transaction. Only --apply writes (one commit per brief). A database without the test_branch_marker table
is treated as production and --apply there also needs --production.
The database is DATABASE_URL from the environment, else backend/.env.

Usage, from backend/:
  python tools/backfill_importance.py [--limit N]                         # dry run
  python tools/backfill_importance.py --apply [--limit N]                 # test branch
  python tools/backfill_importance.py --apply --production [--limit N]    # production
"""
import argparse
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.gemini import GENERATION_MODEL, QuotaExhausted
from pipeline.importance import failed_values, rate, rated_values, store, unrated_rows
from pipeline.ingest import safe_error

CALL_INTERVAL_SECONDS = 5
MARKER_TABLE = "test_branch_marker"


def backfill(db, llm_client, apply=False, limit=None, out=print, interval=CALL_INTERVAL_SECONDS, now=None) -> dict:
    """Rate (and with apply, store) up to limit unrated briefs, newest first. Returns a summary."""
    rows = unrated_rows(db, limit if limit is not None else 1_000_000)
    model = getattr(llm_client, "model_name", GENERATION_MODEL)
    summary = {"targets": len(rows), "rated": 0, "written": 0, "failed": 0, "quota": False, "levels": Counter()}
    out(f"{len(rows)} unrated brief(s) selected")
    for i, row in enumerate(rows):
        if i and interval:
            time.sleep(interval)
        try:
            level, scores = rate(row, llm_client)
        except QuotaExhausted:
            summary["quota"] = True
            out("Gemini quota exhausted; stopping (rerun later to continue)")
            break
        except Exception as e:
            summary["failed"] += 1
            out(f"  brief {row.id}: FAILED {safe_error(e)}")
            if apply:
                store(db, row.id, failed_values(row, safe_error(e)))
            continue
        summary["rated"] += 1
        summary["levels"][level] += 1
        out(f"  brief {row.id}: {level} (severity {scores['severity']}, frequency {scores['frequency']}, "
            f"reach {scores['reach']}) {row.title[:60]}")
        if apply:
            store(db, row.id, rated_values(row, level, scores, model, now or datetime.now(timezone.utc)))
            summary["written"] += 1
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backfill briefs.importance (dry run unless --apply).")
    parser.add_argument("--apply", action="store_true", help="store the ratings")
    parser.add_argument("--production", action="store_true", help=f"required with --apply when there is no {MARKER_TABLE}")
    parser.add_argument("--limit", type=int, default=None, help="rate at most this many briefs")
    args = parser.parse_args(argv)

    from sqlalchemy import text
    from db.database import SessionLocal
    from pipeline.importance import default_client

    db = SessionLocal()
    try:
        is_test_branch = db.execute(text(f"SELECT to_regclass('public.{MARKER_TABLE}') IS NOT NULL")).scalar()
        db.rollback()
        print(f"Target: {'TEST BRANCH' if is_test_branch else 'PRODUCTION'}")
        if args.apply and not is_test_branch and not args.production:
            print("Refusing to apply on production without --production.")
            return 3
        if not args.apply:
            db.execute(text("SET TRANSACTION READ ONLY"))
        summary = backfill(db, default_client(), apply=args.apply, limit=args.limit)
        if not args.apply:
            db.rollback()
    finally:
        db.close()
    print(f"\n{'APPLIED' if args.apply else 'DRY RUN, nothing written'}: targets={summary['targets']} "
          f"rated={summary['rated']} written={summary['written']} failed={summary['failed']} quota={summary['quota']} "
          f"levels={dict(summary['levels'])}")
    return 0 if not summary["failed"] and not summary["quota"] else 1


if __name__ == "__main__":
    sys.exit(main())
