import threading
import time
from collections import OrderedDict
from typing import NamedTuple, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from brief_search import matches_all, terms, words
from db.database import get_db
from db.queries import list_all_briefs, get_brief_by_id, get_brief_stats
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
    entries = cache.get_or_set(SNAPSHOT_KEY, lambda: card_snapshot(db))
    return select_cards(entries, difficulty=difficulty, tag=tag, search=search, sort=sort)[offset:offset + limit]

SNAPSHOT_KEY = ("cards",)
DIFFICULTY_ASC = {"beginner": 1, "intermediate": 2, "advanced": 3}
DIFFICULTY_DESC = {"advanced": 1, "intermediate": 2, "beginner": 3}

class CardEntry(NamedTuple):
    card: dict
    difficulty: str
    stack_words: frozenset
    search_words: frozenset

def card_snapshot(db: Session) -> list:
    """Every brief as a CardEntry, newest first. One query; the result is cached for every filter, sort and page."""
    entries = []
    for card in brief_cards(list_all_briefs(db)):
        stack = card["recommended_stack"] if isinstance(card["recommended_stack"], list) else []
        stack_words = words(*stack)
        entries.append(CardEntry(card, (card["difficulty"] or "").lower(), stack_words,
                                 stack_words | words(card["title"], card["core_task"])))
    return entries

def select_cards(entries, difficulty=None, tag=None, search=None, sort=None) -> list:
    """
    Cards matching every filter: difficulty (any case), tag terms against the stack, search terms against title,
    core task and stack. Newest first unless sort is difficulty_asc (then id ascending) or difficulty_desc (then id descending).
    """
    level = difficulty.lower() if difficulty else None
    stack_terms, search_terms = terms(tag), terms(search)
    chosen = [
        entry for entry in entries
        if (level is None or entry.difficulty == level)
        and matches_all(stack_terms, entry.stack_words)
        and matches_all(search_terms, entry.search_words)
    ]
    if sort == "difficulty_asc":
        chosen.sort(key=lambda entry: (DIFFICULTY_ASC.get(entry.difficulty, 4), entry.card["id"]))
    elif sort == "difficulty_desc":
        chosen.sort(key=lambda entry: (DIFFICULTY_DESC.get(entry.difficulty, 4), -entry.card["id"]))
    return [entry.card for entry in chosen]

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
