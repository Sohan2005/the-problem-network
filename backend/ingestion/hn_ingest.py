import os
import sys
import time
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.queries import insert_raw_ideas

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

def _hit_to_item(hit: dict, search_mode: str, keyword: str):
    object_id = hit.get("objectID")
    story_title = hit.get("story_title") or ""
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
