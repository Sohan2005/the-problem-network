from sqlalchemy.orm import Session
from typing import List, Optional

def create_problem(db: Session, title: str, body: str, source_url: str):
    pass

def create_brief(db: Session, problem_id: int, title: str, difficulty: str, core_task: str, recommended_stack: str):
    pass

def get_or_create_tag(db: Session, name: str):
    pass

def attach_tag_to_brief(db: Session, brief_id: int, tag_id: int):
    pass

def get_problem_by_url(db: Session, source_url: str):
    pass

def list_briefs(db: Session, difficulty: Optional[str] = None, tag: Optional[str] = None):
    pass

def get_brief_by_id(db: Session, brief_id: int):
    pass
