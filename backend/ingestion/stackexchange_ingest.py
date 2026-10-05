import html
import os
import sys
import time
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.queries import insert_raw_ideas

# Load .env from project root (relative to this script)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

SOURCE = "stackexchange_softwarerecs"
SITE = "softwarerecs"
BASE_URL = "https://api.stackexchange.com/2.3"
REQUEST_TIMEOUT = 15
MAX_POST_AGE_YEARS = 3  # Rolling window
MIN_QUESTION_AGE_DAYS = 30
HIGH_CONFIDENCE_VIEW_COUNT = 100
MAX_PAGES = 10  # Limit to 10 pages (1000 questions) to stay within quota
DEFAULT_BUDGET_SECONDS = 240
DEFAULT_MAX_ITEMS = 1000

def _get_json(url: str, params: dict):
    """GET with timeout; returns parsed JSON or None. Errors print the type only (the URL carries the API key)."""
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            print(f"  Request failed: HTTP {response.status_code}")
            return None
        return response.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  Request failed: {type(e).__name__}")
        return None

def _good_answer_exists(question_id, question_score: int, api_key):
    """True if an answer scores meaningfully higher than the question, None if answers could not be fetched."""
    answers_params = {
        "site": SITE,
        "order": "desc",
        "sort": "votes",
        "pagesize": 10,
        "key": api_key
    }
    data = _get_json(f"{BASE_URL}/questions/{question_id}/answers", answers_params)
    answers = data.get("items") if isinstance(data, dict) else None
    if not isinstance(answers, list):
        return None
    return any(isinstance(a, dict) and (a.get("score") or 0) > question_score + 2 for a in answers)

def fetch_candidates(*, budget_seconds, max_items, since=None) -> list:
    """
    Fetch Software Recommendations questions that look like unmet needs
    (unanswered or weakly answered, 30+ days old, within the rolling window).
    Returns raw_ideas item dicts for insert_raw_ideas; no database access. Stops early when the
    time budget or max_items is reached and returns what it has.
    """
    api_key = os.getenv("STACKEXCHANGE_API_KEY")
    if not api_key:
        print("WARNING: No STACKEXCHANGE_API_KEY set. Using anonymous quota (300/day).")
        print("Register at https://stackapps.com/apps/oauth/register for 10,000/day quota.")

    deadline = time.monotonic() + budget_seconds
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    min_date = now - timedelta(days=MAX_POST_AGE_YEARS * 365)
    if since is not None:
        since_utc = since.astimezone(timezone.utc).replace(tzinfo=None) if since.tzinfo else since
        min_date = max(min_date, since_utc)

    candidates = []
    print(f"Fetching questions from {SITE} (up to {MAX_PAGES} pages)...")
    for page in range(1, MAX_PAGES + 1):
        if time.monotonic() >= deadline:
            print(f"  Budget exhausted; returning {len(candidates)} candidates")
            return candidates
        params = {
            "site": SITE,
            "order": "desc",
            "sort": "creation",
            "pagesize": 100,
            "page": page,
            "filter": "withbody",  # Include question body
            "key": api_key
        }
        data = _get_json(f"{BASE_URL}/questions", params)
        if data is None:
            break
        questions = data.get("items") if isinstance(data, dict) else None
        if not isinstance(questions, list) or not questions:
            print(f"  Page {page}: No more questions")
            break
        print(f"  Page {page}: Found {len(questions)} questions")

        for question in questions:
            if not isinstance(question, dict):
                continue
            question_id = question.get("question_id")
            title = html.unescape(question.get("title") or "")
            created = question.get("creation_date")
            if not question_id or not title or not isinstance(created, (int, float)):
                continue
            creation_date = datetime.fromtimestamp(created, timezone.utc).replace(tzinfo=None)
            view_count = question.get("view_count") or 0
            score = question.get("score") or 0
            answer_count = question.get("answer_count") or 0

            # Rolling window, and skip questions less than 1 month old
            if creation_date < min_date or now - creation_date < timedelta(days=MIN_QUESTION_AGE_DAYS):
                continue
            # Has accepted answer - need is likely met
            if question.get("accepted_answer_id"):
                continue
            if answer_count > 0:
                if time.monotonic() >= deadline:
                    print(f"  Budget exhausted; returning {len(candidates)} candidates")
                    return candidates
                # Skip if a good answer exists, or if answers could not be fetched (skip to be safe)
                if _good_answer_exists(question_id, score, api_key) is not False:
                    continue

            source_url = f"https://softwarerecs.stackexchange.com/questions/{question_id}"
            owner = question.get("owner")
            raw_text = f"QUESTION: {title}\n\n"
            raw_text += f"QUESTION URL: {source_url}\n\n"
            raw_text += f"QUESTION BODY: {question.get('body') or ''}\n\n"
            raw_text += f"METADATA: Score={score}, Views={view_count}, Answers={answer_count}"
            candidates.append({
                "source": SOURCE,
                "source_url": source_url,
                "raw_title": title,
                "raw_text": raw_text,
                "author": owner.get("display_name", "Unknown") if isinstance(owner, dict) else "Unknown",
                "source_date": creation_date,
                "matched_keyword": "softwarerecs_question",
                "confidence_flag": "high" if view_count >= HIGH_CONFIDENCE_VIEW_COUNT else "low",
            })
            if len(candidates) >= max_items:
                return candidates
    return candidates

def fetch_softwarerecs_ideas():
    """Fetch Software Recommendations candidates and store them in raw_ideas. Returns the number of new rows."""
    from db.database import SessionLocal

    try:
        candidates = fetch_candidates(budget_seconds=DEFAULT_BUDGET_SECONDS, max_items=DEFAULT_MAX_ITEMS)
        db = SessionLocal()
        try:
            result = insert_raw_ideas(db, candidates)
        finally:
            db.close()
    except Exception as e:
        print(f"Error: {type(e).__name__}")
        return 0

    print("\n=== Summary ===")
    print(f"Fetched: {len(candidates)}")
    print(f"Processed successfully: {result['inserted']}")
    print(f"Skipped (already exists): {result['skipped_duplicate']}")
    print(f"Rejected: {len(result['rejected'])}")
    print(f"High confidence candidates: {sum(1 for c in candidates if c['confidence_flag'] == 'high')}")
    print(f"Low confidence candidates: {sum(1 for c in candidates if c['confidence_flag'] == 'low')}")

    return result["inserted"]

if __name__ == "__main__":
    fetch_softwarerecs_ideas()
