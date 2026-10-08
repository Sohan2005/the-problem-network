"""
Step 6 publish: move the best gate-passed ideas into briefs, once per UTC day.

Daily rules: TARGET briefs per day. With fewer available, everything available is published (never zero while
anything passed); the publish_days note says whether that was a flexible-day shortfall (Wed/Sat/Sun with at least
FLEX_MINIMUM available) or a SHORTFALL. Everything happens in one transaction; the publish_days primary key makes a
second run for the same day a no-op, and briefs.raw_idea_id is unique, so overlapping runs cannot double-publish.
"""
import logging
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import exists

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import Brief, PipelineRun, PublishDay, RawIdea
from pipeline.ingest import safe_error

STAGE = "publish"
TARGET = 10
FLEX_MINIMUM = 5
FLEXIBLE_WEEKDAYS = (2, 5, 6)  # Wednesday, Saturday, Sunday
BUFFER_LOW = 30
VALID_IDEA = ("true", "needs_rescope")

def brief_fields(record) -> dict:
    """Brief columns for a raw idea: the rescoped version for needs_rescope ideas, the extracted columns otherwise."""
    rescoped_version = record.rescoped_version
    if record.is_valid_idea == "needs_rescope" and rescoped_version:
        title = rescoped_version.get("title")
        problem = rescoped_version.get("problem_summary")
        target = rescoped_version.get("target_user")
        features_list = rescoped_version.get("suggested_features", [])
        diff = rescoped_version.get("difficulty_estimate")
        tech_list = rescoped_version.get("suggested_tech_stack", [])
        learning_list = rescoped_version.get("learning_outcomes", [])
    else:
        title = record.extracted_title
        problem = record.problem_summary
        target = record.target_user
        features_list = record.suggested_features if record.suggested_features else []
        diff = record.difficulty_estimate
        tech_list = record.suggested_tech_stack if record.suggested_tech_stack else []
        learning_list = record.learning_outcomes if record.learning_outcomes else []
    return {
        "title": title,
        "difficulty": diff,
        "core_task": problem,
        "recommended_stack": tech_list,
        "target_user": target,
        "suggested_features": features_list,
        "learning_outcomes": learning_list,
        "raw_idea_id": record.id,
        "source_date": record.source_date,
    }

def embedding_text(fields: dict) -> str:
    return f"{fields['title']} {fields['core_task']}"

def candidates_query(db):
    """Gate-passed, unpublished, valid raw ideas without a brief, best first."""
    return (
        db.query(RawIdea)
        .filter(
            RawIdea.gate_status == "passed",
            RawIdea.published_brief_id.is_(None),
            RawIdea.is_valid_idea.in_(VALID_IDEA),
            ~exists().where(Brief.raw_idea_id == RawIdea.id),
        )
        .order_by(RawIdea.gate_score.desc().nullslast(), RawIdea.source_date.asc().nullslast(), RawIdea.id.asc())
    )

def is_flexible_day(day) -> bool:
    return day.weekday() in FLEXIBLE_WEEKDAYS

def day_note(published: int, available: int, flexible: bool) -> str:
    if published == 0:
        return "EMPTY - supply failure"
    if published >= TARGET:
        return "ok"
    if flexible and available >= FLEX_MINIMUM:
        return "flexible-day shortfall"
    return "SHORTFALL"

def _log_run(db, started_at, rows_in, rows_out, status, error=None):
    db.add(PipelineRun(stage=STAGE, started_at=started_at, finished_at=datetime.now(timezone.utc),
                       rows_in=rows_in, rows_out=rows_out, status=status, error=error))
    db.commit()

def run_publish(db, embed_client, today=None) -> dict:
    """
    Publish up to TARGET briefs for `today` (default: current UTC date). Returns a summary; status 'skipped' when
    the day already has a publish_days row. On error everything is rolled back, logged and re-raised.
    """
    started_at = datetime.now(timezone.utc)
    today = today or started_at.date()
    if db.get(PublishDay, today) is not None:
        return {"status": "skipped", "day": today.isoformat(), "published": 0}

    flexible = is_flexible_day(today)
    rows_in = 0
    try:
        candidates = candidates_query(db).all()
        rows_in = len(candidates)
        chosen = candidates[:TARGET]
        published_at = datetime.now(timezone.utc)
        brief_ids = []
        for record in chosen:
            fields = brief_fields(record)
            vector = record.embedding
            if vector is None:
                vector = embed_client.embed(embedding_text(fields))
            brief = Brief(**fields, created_at=published_at.replace(tzinfo=None), embedding=list(vector))
            db.add(brief)
            db.flush()
            record.published_brief_id = brief.id
            record.published_at = published_at
            record.ready_to_publish = False
            brief_ids.append(brief.id)
        note = day_note(len(chosen), rows_in, flexible)
        db.add(PublishDay(day=today, target=TARGET, published=len(chosen), is_flexible_day=flexible,
                          buffer_before=rows_in, buffer_after=rows_in - len(chosen), note=note))
        db.commit()
    except Exception as e:
        db.rollback()
        _log_run(db, started_at, rows_in, 0, "error", safe_error(e))
        raise

    buffer_after = rows_in - len(chosen)
    status = "ok" if note == "ok" else "warn"
    error = None if note == "ok" else note
    if buffer_after < BUFFER_LOW:
        logging.warning("publish: buffer low (%d passed, unpublished briefs; target %d)", buffer_after, BUFFER_LOW)
        error = f"{error + '; ' if error else ''}buffer low: {buffer_after} < {BUFFER_LOW}"
    _log_run(db, started_at, rows_in, len(chosen), status, error)
    return {"status": status, "day": today.isoformat(), "published": len(chosen), "brief_ids": brief_ids,
            "is_flexible_day": flexible, "buffer_before": rows_in, "buffer_after": buffer_after, "note": note,
            "buffer_low": buffer_after < BUFFER_LOW}
