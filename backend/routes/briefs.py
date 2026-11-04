import threading
import time
from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from typing import Optional
from db.database import get_db
from db.queries import list_briefs, get_brief_by_id, get_brief_stats
from pipeline.publish import AI_SOURCES, source_link

router = APIRouter(prefix="/briefs")

CACHE_TTL_SECONDS = 30 * 60
CACHE_MAX_ENTRIES = 256
CACHE_CONTROL = "public, max-age=300, s-maxage=1800, stale-while-revalidate=3600"


class TTLCache:
    """
    Process-local cache of response bodies: entries expire after ttl_seconds and the least recently used entry is
    dropped beyond max_entries. Each worker process keeps its own copy. A hit opens no database connection.
    """

    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS, max_entries: int = CACHE_MAX_ENTRIES, clock=time.monotonic):
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def get_or_set(self, key, compute):
        """The cached value for key, or compute() stored under key. A None result is returned but not stored."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] > self.clock():
                self._entries.move_to_end(key)
                return entry[1]
        value = compute()
        if value is None:
            return None
        with self._lock:
            self._entries[key] = (self.clock() + self.ttl, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return value

    def clear(self):
        with self._lock:
            self._entries.clear()

    def __len__(self):
        return len(self._entries)


cache = TTLCache()

@router.get("/stats")
def get_stats(response: Response, db: Session = Depends(get_db)):
    """Get brief statistics: total count, recent count (7 days), last updated"""
    response.headers["Cache-Control"] = CACHE_CONTROL
    return cache.get_or_set(("stats",), lambda: get_brief_stats(db))

@router.get("/")
def get_briefs(response: Response, difficulty: Optional[str] = Query(None), tag: Optional[str] = Query(None), search: Optional[str] = Query(None), sort: Optional[str] = Query(None), limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = CACHE_CONTROL
    key = ("list", difficulty, tag, search, sort, limit, offset)
    return cache.get_or_set(key, lambda: brief_cards(list_briefs(db, difficulty=difficulty, tag=tag, search=search, sort=sort, limit=limit, offset=offset)))

def brief_cards(briefs) -> list:
    return [
        {
            "id": b.id,
            "title": b.title,
            "difficulty": b.difficulty,
            "core_task": b.core_task,
            "recommended_stack": b.recommended_stack,
            "has_title_mark": b.raw_source in AI_SOURCES,
        }
        for b in briefs
    ]

@router.get("/{brief_id:int}")
def get_brief(brief_id: int, response: Response, db: Session = Depends(get_db)):
    body = cache.get_or_set(("detail", brief_id), lambda: brief_detail(db, brief_id))
    if body is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    response.headers["Cache-Control"] = CACHE_CONTROL
    return body

def brief_detail(db: Session, brief_id: int) -> Optional[dict]:
    brief = get_brief_by_id(db, brief_id)
    if not brief:
        return None
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
