from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from typing import Optional
from db.database import get_db
from db.queries import list_briefs, get_brief_by_id, get_brief_stats
from db.models import Brief, RawIdea
from pipeline.publish import AI_SOURCES, source_link

router = APIRouter(prefix="/briefs")

@router.get("/stats")
def get_stats(response: Response, db: Session = Depends(get_db)):
    """Get brief statistics: total count, recent count (7 days), last updated"""
    response.headers["Cache-Control"] = "public, max-age=60"
    return get_brief_stats(db)

@router.get("/")
def get_briefs(response: Response, difficulty: Optional[str] = Query(None), tag: Optional[str] = Query(None), search: Optional[str] = Query(None), sort: Optional[str] = Query(None), limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=60"
    briefs = list_briefs(db, difficulty=difficulty, tag=tag, search=search, sort=sort, limit=limit, offset=offset)
    marked = {
        brief_id for (brief_id,) in db.query(Brief.id).join(RawIdea, RawIdea.id == Brief.raw_idea_id)
        .filter(RawIdea.source.in_(AI_SOURCES), Brief.id.in_([b.id for b in briefs]))
    } if briefs else set()
    return [
        {
            "id": b.id,
            "title": b.title,
            "difficulty": b.difficulty,
            "core_task": b.core_task,
            "recommended_stack": b.recommended_stack,
            "tags": [t.name for t in b.tags],
            "has_title_mark": b.id in marked,
        }
        for b in briefs
    ]

@router.get("/{brief_id:int}")
def get_brief(brief_id: int, db: Session = Depends(get_db)):
    brief = get_brief_by_id(db, brief_id)
    if not brief:
        raise HTTPException(status_code=404, detail="Brief not found")
    source = brief.problem or brief.raw_idea
    return {
        "id": brief.id,
        "title": brief.title,
        "difficulty": brief.difficulty,
        "core_task": brief.core_task,
        "recommended_stack": brief.recommended_stack,
        "target_user": brief.target_user,
        "suggested_features": brief.suggested_features,
        "learning_outcomes": brief.learning_outcomes,
        "what_youll_need": brief.what_youll_need,
        "how_to_begin": brief.how_to_begin,
        "tags": [t.name for t in brief.tags],
        "source_url": source_link(source.source, source.source_url) if source else None,
        "source_platform": source.source if source else None,
        "has_title_mark": brief.raw_idea is not None and brief.raw_idea.source in AI_SOURCES,
    }
