"""
Backfill the Getting Started fields (what_youll_need, how_to_begin) wherever they would fail the getting_started gate
(empty or shorter than its minimum): published briefs, then gate-passed, unpublished raw ideas (publish candidates).
The text comes from the same GETTING_STARTED_RULES as extraction, generated from the title, problem summary, tech
stack and features. One Gemini call per row, CALL_INTERVAL_SECONDS apart; a quota error stops the run cleanly.

The default is a dry run: it lists every target, generates text for up to --limit of them and prints what it would
write, inside a read-only transaction. Only --apply writes (one commit per row, so a stopped run keeps its progress).
The database is DATABASE_URL from the environment, else backend/.env.

Usage, from backend/:
  python tools/backfill_getting_started.py [--limit N]          # dry run
  python tools/backfill_getting_started.py --apply [--limit N]
"""
import argparse
import os
import sys
import time
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import Brief, RawIdea
from llm.gemini import QuotaExhausted
from llm.translate import FORUM_MODEL, build_getting_started_prompt, parse_getting_started_response
from pipeline.gates import effective_fields, gate_getting_started
from pipeline.ingest import safe_error
from pipeline.publish import candidates_query

CALL_INTERVAL_SECONDS = 5

Target = namedtuple("Target", "kind id title prompt")

def find_targets(db) -> list:
    """Briefs (by id), then publish candidates (best first) whose Getting Started fails the gate."""
    targets = []
    briefs = db.query(Brief.id, Brief.title, Brief.core_task, Brief.recommended_stack, Brief.suggested_features,
                      Brief.what_youll_need, Brief.how_to_begin).order_by(Brief.id)
    for brief in briefs:
        if not gate_getting_started({"what_youll_need": brief.what_youll_need, "how_to_begin": brief.how_to_begin})[0]:
            prompt = build_getting_started_prompt(brief.title, brief.core_task, brief.recommended_stack, brief.suggested_features)
            targets.append(Target("brief", brief.id, brief.title, prompt))
    for row in candidates_query(db):
        fields = effective_fields(row)
        if not gate_getting_started(fields)[0]:
            prompt = build_getting_started_prompt(fields["title"], fields["problem_summary"], fields["suggested_tech_stack"],
                                                  fields["suggested_features"])
            targets.append(Target("raw_idea", row.id, fields["title"], prompt))
    return targets

def backfill(db, llm_client, apply=False, limit=None, out=print, interval=CALL_INTERVAL_SECONDS) -> dict:
    """Generate (and with apply, write) Getting Started for up to limit targets. Returns a summary."""
    targets = find_targets(db)
    out(f"{len(targets)} target(s) missing Getting Started:")
    for target in targets:
        out(f"  {target.kind} {target.id}: {target.title}")
    summary = {"targets": len(targets), "generated": 0, "written": 0, "failed": 0, "quota": False, "ids": []}
    for i, target in enumerate(targets[:limit]):
        if i and interval:
            time.sleep(interval)
        try:
            fields = parse_getting_started_response(llm_client.generate(target.prompt))
            passed, reason, _ = gate_getting_started(fields)
            if not passed:
                raise ValueError(reason)
        except QuotaExhausted:
            summary["quota"] = True
            out("Gemini quota exhausted; stopping (rerun later to continue)")
            break
        except Exception as e:
            summary["failed"] += 1
            out(f"\n{target.kind} {target.id}: FAILED {safe_error(e)}")
            continue
        summary["generated"] += 1
        summary["ids"].append((target.kind, target.id))
        out(f"\n=== {target.kind} {target.id}: {target.title}")
        out(f"What You'll Need:\n{fields['what_youll_need']}")
        out(f"How to Begin:\n{fields['how_to_begin']}")
        if apply:
            model = Brief if target.kind == "brief" else RawIdea
            db.query(model).filter(model.id == target.id).update(fields, synchronize_session=False)
            db.commit()
            summary["written"] += 1
    return summary

def main(argv=None):
    parser = argparse.ArgumentParser(description="Backfill what_youll_need / how_to_begin (dry run unless --apply).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print what would be written (default)")
    mode.add_argument("--apply", action="store_true", help="write the generated text")
    parser.add_argument("--limit", type=int, default=None, help="generate for at most this many targets")
    args = parser.parse_args(argv)

    from sqlalchemy import text
    from db.database import SessionLocal
    from llm.gemini import GeminiClient

    db = SessionLocal()
    try:
        if not args.apply:
            db.execute(text("SET TRANSACTION READ ONLY"))
        summary = backfill(db, GeminiClient(FORUM_MODEL), apply=args.apply, limit=args.limit)
        if not args.apply:
            db.rollback()
    finally:
        db.close()
    print(f"\n{'APPLIED' if args.apply else 'DRY RUN, nothing written'}: targets={summary['targets']} "
          f"generated={summary['generated']} written={summary['written']} failed={summary['failed']} quota={summary['quota']}")
    return 0 if not summary["failed"] and not summary["quota"] else 1

if __name__ == "__main__":
    sys.exit(main())
