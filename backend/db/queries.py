import html
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from typing import List, Optional

def create_problem(db: Session, source: str, title: str, body: str, source_url: str):
    from .models import Problem
    problem = Problem(source=source, source_url=source_url, raw_text=body)
    db.add(problem)
    db.commit()
    db.refresh(problem)
    return problem

def create_brief(db: Session, problem_id: int, title: str, difficulty: str, core_task: str, recommended_stack: str):
    from .models import Brief
    brief = Brief(
        problem_id=problem_id,
        title=title,
        difficulty=difficulty,
        core_task=core_task,
        recommended_stack=recommended_stack
    )
    db.add(brief)
    db.commit()
    db.refresh(brief)
    return brief

def get_or_create_tag(db: Session, name: str):
    from .models import Tag
    tag = db.query(Tag).filter(Tag.name == name).first()
    if not tag:
        tag = Tag(name=name)
        db.add(tag)
        db.commit()
        db.refresh(tag)
    return tag

def attach_tag_to_brief(db: Session, brief_id: int, tag_id: int):
    from .models import brief_tags
    db.execute(brief_tags.insert().values(brief_id=brief_id, tag_id=tag_id))
    db.commit()

def get_problem_by_url(db: Session, source_url: str):
    from .models import Problem
    return db.query(Problem).filter(Problem.source_url == source_url).first()

def list_briefs(db: Session, difficulty: Optional[str] = None, tag: Optional[str] = None, search: Optional[str] = None, sort: Optional[str] = None):
    from .models import Brief, Tag
    from sqlalchemy import or_, case, func
    
    query = db.query(Brief)
    
    if difficulty:
        query = query.filter(Brief.difficulty == difficulty.lower())
    
    if tag:
        # Filter by recommended_stack (JSON array) instead of tags relationship
        # Lowercase the JSON text, cast to JSONB and use @> for case-insensitive array containment
        from sqlalchemy import cast, Text
        from sqlalchemy.dialects.postgresql import JSONB
        stack_lower = cast(func.lower(cast(Brief.recommended_stack, Text)), JSONB)
        query = query.filter(stack_lower.op('@>')([tag.lower()]))
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Brief.title.ilike(search_term),
                Brief.core_task.ilike(search_term)
            )
        )
    
    # Sort by difficulty
    difficulty_level = func.lower(Brief.difficulty)
    if sort == "difficulty_asc":
        query = query.order_by(
            case(
                (difficulty_level == "beginner", 1),
                (difficulty_level == "intermediate", 2),
                (difficulty_level == "advanced", 3),
                else_=4
            )
        )
    elif sort == "difficulty_desc":
        query = query.order_by(
            case(
                (difficulty_level == "advanced", 1),
                (difficulty_level == "intermediate", 2),
                (difficulty_level == "beginner", 3),
                else_=4
            )
        )
    else:
        # Default: most recent (by created_at)
        query = query.order_by(Brief.created_at.desc())
    
    return query.all()

def get_brief_by_id(db: Session, brief_id: int):
    from .models import Brief
    return db.query(Brief).filter(Brief.id == brief_id).first()

def get_brief_stats(db: Session):
    """Get brief statistics: total count, count added in last 7 days, last updated timestamp"""
    from .models import Brief
    from datetime import datetime, timedelta
    from sqlalchemy import func
    
    total_count = db.query(func.count(Brief.id)).scalar()
    
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent_count = db.query(func.count(Brief.id)).filter(Brief.created_at >= seven_days_ago).scalar()
    
    last_updated = db.query(func.max(Brief.created_at)).scalar()
    
    return {
        "total_count": total_count,
        "recent_count": recent_count,
        "last_updated": last_updated.isoformat() if last_updated else None
    }

def create_raw_idea(db: Session, source: str, source_url: str, raw_title: str, raw_text: str, author: str = None):
    from .models import RawIdea
    idea = RawIdea(
        source=source,
        source_url=source_url,
        raw_title=raw_title,
        raw_text=raw_text,
        author=author
    )
    db.add(idea)
    db.commit()
    db.refresh(idea)
    return idea

def get_raw_idea_by_url(db: Session, source_url: str):
    from .models import RawIdea
    return db.query(RawIdea).filter(RawIdea.source_url == source_url).first()

# Must stay identical to the canonical_url backfill in db/migrations/001_pipeline_state.sql (statement 12):
# btrim() trims spaces only, "." matches newlines and "$" is end of string in PostgreSQL regexes.
_URL_PARTS = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://[^/?#]*)?([^?#]*)(\?[^#]*)?(#.*)?", re.DOTALL)

def canonicalize_url(url: str) -> str:
    """Lowercase scheme and host, drop the fragment and utm_* parameters, trim trailing slashes, keep other parameters in order."""
    origin, path, query, _fragment = _URL_PARTS.fullmatch(url.strip(" ")).groups()
    origin = (origin or "").lower()
    path = re.sub(r"/+\Z", "", path or "")
    params = [kv for kv in (query[1:].split("&") if query else []) if kv and not kv.lower().startswith("utm_")]
    return origin + path + ("?" + "&".join(params) if params else "")

RAW_TITLE_MAX = 500
RAW_TEXT_MAX = 8000
SOURCE_DATE_MAX_AGE = timedelta(days=3 * 365)

def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value

def _clip(value, limit: int):
    return value[:limit] if isinstance(value, str) else None

def _raw_idea_reject_reason(item, now: datetime):
    if not isinstance(item, dict):
        return "not a dict"
    for key in ("source", "source_url", "raw_title", "raw_text"):
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            return f"missing {key}"
    if len(item["source"]) > 50:
        return "source too long"
    if len(item["source_url"]) > 500:
        return "source_url too long"
    source_date = item.get("source_date")
    if source_date is not None:
        if not isinstance(source_date, datetime):
            return "invalid source_date"
        source_date = _naive_utc(source_date)
        if source_date > now:
            return "source_date in future"
        if source_date < now - SOURCE_DATE_MAX_AGE:
            return "source_date too old"
    return None

def insert_raw_ideas(db: Session, items) -> dict:
    """Validate and insert scraped ideas, skipping any whose source_url or canonical_url is already stored. Commits once; no embeddings."""
    from sqlalchemy.dialects.postgresql import insert
    from .models import RawIdea
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows, seen, rejected, batch_duplicates = [], set(), [], 0
    for item in items:
        reason = _raw_idea_reject_reason(item, now)
        if reason:
            rejected.append((item.get("source_url") if isinstance(item, dict) else None, reason))
            continue
        canonical_url = canonicalize_url(item["source_url"])
        if canonical_url in seen:
            batch_duplicates += 1
            continue
        seen.add(canonical_url)
        source_date = item.get("source_date")
        rows.append({
            "source": item["source"],
            "source_url": item["source_url"],
            "raw_title": html.unescape(item["raw_title"])[:RAW_TITLE_MAX],
            "raw_text": item["raw_text"][:RAW_TEXT_MAX],
            "author": _clip(item.get("author"), 100),
            "matched_keyword": _clip(item.get("matched_keyword"), 100),
            "confidence_flag": _clip(item.get("confidence_flag"), 20),
            "source_date": _naive_utc(source_date) if source_date is not None else None,
            "canonical_url": canonical_url,
            "fetched_at": now,
        })
    inserted = 0
    if rows:
        try:
            result = db.execute(insert(RawIdea.__table__).on_conflict_do_nothing().returning(RawIdea.__table__.c.id), rows)
            inserted = len(result.all())
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"inserted": inserted, "skipped_duplicate": batch_duplicates + len(rows) - inserted, "rejected": rejected}
