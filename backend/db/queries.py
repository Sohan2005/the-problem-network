import html
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

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

# Never add embedding here: it is about 39 KB per brief and the API does not return it.
LIST_COLUMNS = ("id", "title", "difficulty", "core_task", "recommended_stack")
DETAIL_COLUMNS = LIST_COLUMNS + ("target_user", "suggested_features", "learning_outcomes", "what_youll_need", "how_to_begin")


def list_all_briefs(db: Session):
    """
    Every brief, newest first (then highest id), as rows with LIST_COLUMNS plus raw_source (the linked raw idea's
    source, None without one). No filter or limit: the API filters, sorts and pages this snapshot in memory.
    """
    from .models import Brief, RawIdea
    return (
        db.query(*(getattr(Brief, name) for name in LIST_COLUMNS), RawIdea.source.label("raw_source"))
        .outerjoin(RawIdea, RawIdea.id == Brief.raw_idea_id)
        .order_by(Brief.created_at.desc(), Brief.id.desc())
        .all()
    )

def get_brief_by_id(db: Session, brief_id: int):
    """
    The Brief with DETAIL_COLUMNS and its link ids. brief.problem, brief.raw_idea and brief.tags stay lazy: the problems
    table is only queried for briefs with a problem_id, and the linked rows load source and source_url only.
    """
    from sqlalchemy.orm import lazyload, load_only
    from .models import Brief, Problem, RawIdea
    return (
        db.query(Brief)
        .options(
            load_only(*(getattr(Brief, name) for name in DETAIL_COLUMNS), Brief.problem_id, Brief.raw_idea_id),
            lazyload(Brief.problem).load_only(Problem.source, Problem.source_url),
            lazyload(Brief.raw_idea).load_only(RawIdea.source, RawIdea.source_url),
        )
        .filter(Brief.id == brief_id)
        .first()
    )

def get_brief_stats(db: Session):
    """
    Total brief count and last updated timestamp. recent_count is always None: the frontend no longer shows it, so it
    is not queried; the key stays for frontends deployed before that change.
    """
    from .models import Brief
    from sqlalchemy import func
    
    total_count = db.query(func.count(Brief.id)).scalar()
    last_updated = db.query(func.max(Brief.created_at)).scalar()
    
    return {
        "total_count": total_count,
        "recent_count": None,
        "last_updated": last_updated.isoformat() if last_updated else None
    }

VISIT_INCREMENT_SQL = (
    "INSERT INTO site_visits (day, visits) VALUES (:day, 1) "
    "ON CONFLICT (day) DO UPDATE SET visits = site_visits.visits + 1"
)

def record_visit(db: Session, day):
    """
    Add one visit to day's row. A single upsert statement: the row lock taken by ON CONFLICT DO UPDATE serializes
    concurrent requests, so no increment is lost.
    """
    from sqlalchemy import text
    db.execute(text(VISIT_INCREMENT_SQL), {"day": day})
    db.commit()

def get_visit_counts(db: Session, today):
    """Total visits over every day and visits on today, in one query."""
    from sqlalchemy import text
    total, on_day = db.execute(
        text("SELECT coalesce(sum(visits), 0), coalesce(sum(visits) FILTER (WHERE day = :today), 0) FROM site_visits"),
        {"today": today},
    ).one()
    return {"total": int(total), "today": int(on_day)}

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
