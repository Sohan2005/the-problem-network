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
