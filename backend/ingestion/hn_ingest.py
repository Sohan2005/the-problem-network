import html
import os
import re
import sys
import time
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.queries import insert_raw_ideas
from ingestion.search_terms import intent_score

# Load .env from project root (relative to this script)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

SOURCE = "hackernews"
ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
REQUEST_TIMEOUT = 15
RESULTS_PER_KEYWORD = 50
MAX_POST_AGE_YEARS = 3
DEFAULT_BUDGET_SECONDS = 240
DEFAULT_MAX_ITEMS = 1000

# Search modes: ask_hn only (direct idea requests) - higher signal than comment mining
SEARCH_MODES = ["ask_hn"]

# Keyword buckets - expanded with broader phrasings
BUCKET_A = ["would gladly pay", "i would pay monthly", "surprised no one sells", "shut up and take my money", "is there a paid version"]
BUCKET_B = ["scratch my own itch", "frustratingly bad", "i ended up writing a script", "why is there no open source alternative", "hate the current options"]
BUCKET_C = ["wish there was a tool", "someone should build", "is there a lightweight alternative", "gap in the market"]
BUCKET_D = ["is there a tool that", "why doesn't this exist", "looking for an app/tool that", "wish there was a way to"]
KEYWORDS = BUCKET_A + BUCKET_B + BUCKET_C + BUCKET_D

# Deep search (phrase_search = way 1, full_sweep = way 2): Ask HN stories only, newest first.
SEARCH_BY_DATE_URL = "https://hn.algolia.com/api/v1/search_by_date"
SWEEP_TAGS = "story,ask_hn"  # comma = AND
SWEEP_HITS_PER_PAGE = 1000
SWEEP_ATTRIBUTES = "title,story_text,author,created_at_i,_tags"
SPLIT_AT_HITS = 900  # Algolia serves at most ~1,000 results per query, so busier windows are halved
MIN_SPLIT_SECONDS = 60 * 60
RETRY_PAUSE_SECONDS = 2
MIN_STORE_SCORE = 2
MIN_TEXT_WORDS = 20
SWEEP_KEYWORD = "sweep"
EXCLUDED_TITLE_PREFIXES = ("show hn", "launch hn")
EXCLUDED_TAGS = {"show_hn", "launch_hn"}
_HTML_TAG = re.compile(r"<[^>]+>")

def _hit_to_item(hit: dict, search_mode: str, keyword: str):
    object_id = hit.get("objectID")
    story_title = hit.get("title") or hit.get("story_title") or ""  # stories carry "title"; comments carry "story_title"
    story_url = hit.get("story_url") or ""
    comment_text = hit.get("comment_text") or ""
    story_text = hit.get("story_text") or ""  # For ask_hn posts, use story_text
    created_at_i = hit.get("created_at_i")  # Unix timestamp of post creation

    if not object_id or not story_title:
        return None
    if search_mode == "comment" and not comment_text:
        return None
    if search_mode == "ask_hn" and not story_text:
        return None

    body = f"MATCHING COMMENT: {comment_text}" if search_mode == "comment" else f"POST TEXT: {story_text}"
    source_date = None
    if isinstance(created_at_i, (int, float)):
        source_date = datetime.fromtimestamp(created_at_i, timezone.utc).replace(tzinfo=None)
    return {
        "source": SOURCE,
        "source_url": f"https://news.ycombinator.com/item?id={object_id}",
        "raw_title": story_title,
        "raw_text": f"STORY: {story_title}\n\nSTORY URL: {story_url}\n\n{body}",
        "author": hit.get("author"),
        "source_date": source_date,
        "matched_keyword": keyword,
    }

def fetch_candidates(*, budget_seconds, max_items, since=None) -> list:
    """
    Search Algolia for Ask HN posts matching need-signal keywords (last MAX_POST_AGE_YEARS, Show HN excluded).
    Returns raw_ideas item dicts for insert_raw_ideas; no database access. Stops early when the
    time budget or max_items is reached and returns what it has.
    """
    deadline = time.monotonic() + budget_seconds
    min_timestamp = int(time.time()) - MAX_POST_AGE_YEARS * 365 * 24 * 60 * 60
    if since is not None:
        since_utc = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        min_timestamp = max(min_timestamp, int(since_utc.timestamp()))

    candidates, seen_urls = [], set()
    for search_mode in SEARCH_MODES:
        for keyword in KEYWORDS:
            if len(candidates) >= max_items:
                return candidates
            if time.monotonic() >= deadline:
                print(f"  Budget exhausted; returning {len(candidates)} candidates")
                return candidates
            params = {
                "tags": search_mode,
                "query": keyword,
                "hitsPerPage": RESULTS_PER_KEYWORD,
                "numericFilters": f"created_at_i>{min_timestamp}",
                "tagFilters": "-show_hn"  # Exclude Show HN posts (completed projects)
            }
            try:
                response = requests.get(ALGOLIA_URL, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError) as e:
                print(f"  Search failed for '{keyword}': {type(e).__name__}")
                continue
            hits = data.get("hits") if isinstance(data, dict) else None
            if not isinstance(hits, list):
                continue
            for hit in hits:
                item = _hit_to_item(hit, search_mode, keyword) if isinstance(hit, dict) else None
                if item is None or item["source_url"] in seen_urls:
                    continue
                seen_urls.add(item["source_url"])
                candidates.append(item)
                if len(candidates) >= max_items:
                    return candidates
    return candidates

def clean_text(value) -> str:
    """Algolia story_text without HTML tags and entities, whitespace collapsed."""
    return " ".join(html.unescape(_HTML_TAG.sub(" ", value or "")).split())

def three_year_window(now=None):
    """(start_ts, end_ts) covering the last MAX_POST_AGE_YEARS, as Unix seconds."""
    end_ts = int(now if now is not None else time.time())
    return end_ts - MAX_POST_AGE_YEARS * 365 * 24 * 60 * 60, end_ts

def _sweep_item(hit, keyword: str):
    """Candidate for an Ask HN story with buildable intent and enough text, otherwise None. Show HN / Launch HN never pass."""
    if not isinstance(hit, dict):
        return None
    title = hit.get("title") or ""
    tags = hit.get("_tags") if isinstance(hit.get("_tags"), list) else []
    if title.strip().lower().startswith(EXCLUDED_TITLE_PREFIXES) or EXCLUDED_TAGS.intersection(tags):
        return None
    text = clean_text(hit.get("story_text"))
    if len(text.split()) < MIN_TEXT_WORDS or intent_score(title, text) < MIN_STORE_SCORE:
        return None
    return _hit_to_item(hit, "ask_hn", keyword)

class _UnitStopped(Exception):
    pass

def _sweep(query: str, keyword: str, start_ts, end_ts, budget_seconds, get) -> dict:
    """
    All Ask HN stories matching query in [start_ts, end_ts), newest first. A window with SPLIT_AT_HITS or more hits is
    halved recursively; smaller windows are paged to the last page. A failed request is retried once; a second failure
    or the budget running out stops the unit with status 'warn' (candidates found so far are still returned).
    """
    get = get or requests.get
    default_start, default_end = three_year_window()
    start_ts = default_start if start_ts is None else int(start_ts)
    end_ts = default_end if end_ts is None else int(end_ts)
    deadline = time.monotonic() + budget_seconds
    result = {"status": "ok", "reason": None, "calls": 0, "seen": 0, "candidates": []}
    seen_urls = set()

    def fetch(start, end, page):
        params = {"tags": SWEEP_TAGS, "numericFilters": f"created_at_i>={start},created_at_i<{end}",
                  "hitsPerPage": SWEEP_HITS_PER_PAGE, "page": page, "attributesToRetrieve": SWEEP_ATTRIBUTES}
        if query:
            params.update({"query": f'"{query}"', "advancedSyntax": "true"})  # exact phrase
        error = None
        for attempt in range(2):
            if time.monotonic() >= deadline:
                raise _UnitStopped("budget")
            if attempt:
                time.sleep(max(0.0, min(RETRY_PAUSE_SECONDS, deadline - time.monotonic())))
            result["calls"] += 1
            try:
                response = get(SEARCH_BY_DATE_URL, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict) and isinstance(data.get("hits"), list):
                    return data
                error = "malformed response"
            except (requests.RequestException, ValueError) as e:
                error = type(e).__name__
        raise _UnitStopped(f"algolia: {error}")

    def collect(data):
        for hit in data["hits"]:
            result["seen"] += 1
            item = _sweep_item(hit, keyword)
            if item is not None and item["source_url"] not in seen_urls:
                seen_urls.add(item["source_url"])
                result["candidates"].append(item)

    def walk(start, end):
        data = fetch(start, end, 0)
        if (data.get("nbHits") or 0) >= SPLIT_AT_HITS and end - start > MIN_SPLIT_SECONDS:
            middle = (start + end) // 2
            walk(middle, end)
            walk(start, middle)
            return
        collect(data)
        for page in range(1, data.get("nbPages") or 1):
            collect(fetch(start, end, page))

    try:
        if start_ts < end_ts:
            walk(start_ts, end_ts)
    except _UnitStopped as e:
        result["status"], result["reason"] = "warn", str(e)
    return result

def phrase_search(phrase: str, *, budget_seconds, start_ts=None, end_ts=None, get=None) -> dict:
    """
    Way 1: Ask HN stories containing the exact phrase, window defaulting to the last MAX_POST_AGE_YEARS. Keeps stories
    with intent_score >= MIN_STORE_SCORE and MIN_TEXT_WORDS words of text, matched_keyword = phrase. No database access.
    Returns {"status": "ok"|"warn", "reason", "calls", "seen", "candidates"}.
    """
    return _sweep(phrase, phrase, start_ts, end_ts, budget_seconds, get)

def full_sweep(*, budget_seconds, start_ts=None, end_ts=None, get=None) -> dict:
    """Way 2: every Ask HN story in the window, same filters and result as phrase_search, matched_keyword = 'sweep'."""
    return _sweep("", SWEEP_KEYWORD, start_ts, end_ts, budget_seconds, get)

def fetch_hn_ideas_via_context_stitching():
    """Fetch HN candidates and store them in raw_ideas. Returns the number of new rows."""
    from db.database import SessionLocal

    candidates = fetch_candidates(budget_seconds=DEFAULT_BUDGET_SECONDS, max_items=DEFAULT_MAX_ITEMS)
    db = SessionLocal()
    try:
        result = insert_raw_ideas(db, candidates)
    finally:
        db.close()

    print("\n=== Summary ===")
    print(f"Fetched: {len(candidates)}")
    print(f"Processed successfully: {result['inserted']}")
    print(f"Skipped (already exists): {result['skipped_duplicate']}")
    print(f"Rejected: {len(result['rejected'])}")

    return result["inserted"]

if __name__ == "__main__":
    fetch_hn_ideas_via_context_stitching()
