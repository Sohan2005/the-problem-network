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

SOURCE = "stackexchange_softwarerecs"  # adapter name in pipeline_runs; items carry their own site's source
BASE_URL = "https://api.stackexchange.com/2.3"
REQUEST_TIMEOUT = 15
MAX_POST_AGE_YEARS = 3  # Rolling window
SEARCH_WINDOW_DAYS = 365  # Phrase-search sites: questions created in the last 12 months
MIN_QUESTION_AGE_DAYS = 30
HIGH_CONFIDENCE_VIEW_COUNT = 100
MAX_PAGES = 10  # Limit to 10 pages (1000 questions) to stay within quota
SEARCH_PAGE_SIZE = 100  # Phrase-search sites: one page per phrase
DEFAULT_BUDGET_SECONDS = 240
DEFAULT_MAX_ITEMS = 1000

# phrases None: every recent question on the site (paged). Otherwise one /search/advanced page per exact phrase.
SOFTWARERECS = {"site": "softwarerecs", "source": "stackexchange_softwarerecs", "host": "softwarerecs.stackexchange.com",
                "phrases": None}

NEED_PHRASES = ("is there an app", "is there a tool", "looking for software", "how can I automate")

# Disabled: measured 2026-10 over the last 12 months with the exact NEED_PHRASES, no site reached the 50 matching
# questions required to enable it (android 1, apple 3, superuser 4, webapps 0, money 0, askubuntu 2). Matching all
# words loosely finds 50+ on superuser, askubuntu, android and apple, but those are mostly troubleshooting questions.
# 'productivity' is no longer an API site (bad_parameter); webapps replaces it.
ANDROID = {"site": "android", "source": "stackexchange_android", "host": "android.stackexchange.com", "phrases": NEED_PHRASES}
APPLE = {"site": "apple", "source": "stackexchange_apple", "host": "apple.stackexchange.com", "phrases": NEED_PHRASES}
SUPERUSER = {"site": "superuser", "source": "stackexchange_superuser", "host": "superuser.com", "phrases": NEED_PHRASES}
WEBAPPS = {"site": "webapps", "source": "stackexchange_webapps", "host": "webapps.stackexchange.com", "phrases": NEED_PHRASES}
MONEY = {"site": "money", "source": "stackexchange_money", "host": "money.stackexchange.com", "phrases": NEED_PHRASES}
ASKUBUNTU = {"site": "askubuntu", "source": "stackexchange_askubuntu", "host": "askubuntu.com", "phrases": NEED_PHRASES}

SITES = [SOFTWARERECS]

class _BudgetExhausted(Exception):
    pass

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

def _good_answer_exists(site: str, question_id, question_score: int, api_key):
    """True if an answer scores meaningfully higher than the question, None if answers could not be fetched."""
    answers_params = {
        "site": site,
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

def _requests(site: dict, api_key, min_date: datetime):
    """(label, url, params, paged, matched_keyword) per request, in order; paged requests stop at the first empty page."""
    if site["phrases"] is None:
        for page in range(1, MAX_PAGES + 1):
            params = {
                "site": site["site"],
                "order": "desc",
                "sort": "creation",
                "pagesize": 100,
                "page": page,
                "filter": "withbody",  # Include question body
                "key": api_key
            }
            yield f"Page {page}", f"{BASE_URL}/questions", params, True, f"{site['site']}_question"
        return
    for phrase in site["phrases"]:
        params = {
            "site": site["site"],
            "q": f'"{phrase}"',
            "fromdate": int(min_date.replace(tzinfo=timezone.utc).timestamp()),
            "order": "desc",
            "sort": "creation",
            "pagesize": SEARCH_PAGE_SIZE,
            "page": 1,
            "filter": "withbody",
            "key": api_key
        }
        yield f"Phrase '{phrase}'", f"{BASE_URL}/search/advanced", params, False, phrase

def _candidate(site: dict, question, matched_keyword: str, api_key, now: datetime, min_date: datetime, deadline: float):
    """raw_ideas item for a question that looks like an unmet need, or None. Raises _BudgetExhausted before a late answers call."""
    if not isinstance(question, dict):
        return None
    question_id = question.get("question_id")
    title = html.unescape(question.get("title") or "")
    created = question.get("creation_date")
    if not question_id or not title or not isinstance(created, (int, float)):
        return None
    creation_date = datetime.fromtimestamp(created, timezone.utc).replace(tzinfo=None)
    view_count = question.get("view_count") or 0
    score = question.get("score") or 0
    answer_count = question.get("answer_count") or 0

    # Rolling window, and skip questions less than 1 month old
    if creation_date < min_date or now - creation_date < timedelta(days=MIN_QUESTION_AGE_DAYS):
        return None
    # Has accepted answer - need is likely met
    if question.get("accepted_answer_id"):
        return None
    if answer_count > 0:
        if time.monotonic() >= deadline:
            raise _BudgetExhausted()
        # Skip if a good answer exists, or if answers could not be fetched (skip to be safe)
        if _good_answer_exists(site["site"], question_id, score, api_key) is not False:
            return None

    source_url = f"https://{site['host']}/questions/{question_id}"
    owner = question.get("owner")
    raw_text = f"QUESTION: {title}\n\n"
    raw_text += f"QUESTION URL: {source_url}\n\n"
    raw_text += f"QUESTION BODY: {question.get('body') or ''}\n\n"
    raw_text += f"METADATA: Score={score}, Views={view_count}, Answers={answer_count}"
    return {
        "source": site["source"],
        "source_url": source_url,
        "raw_title": title,
        "raw_text": raw_text,
        "author": owner.get("display_name", "Unknown") if isinstance(owner, dict) else "Unknown",
        "source_date": creation_date,
        "matched_keyword": matched_keyword,
        "confidence_flag": "high" if view_count >= HIGH_CONFIDENCE_VIEW_COUNT else "low",
    }

def fetch_candidates(*, budget_seconds, max_items, since=None) -> list:
    """
    Fetch questions that look like unmet needs (unanswered or weakly answered, 30+ days old, within the
    rolling window) from every site in SITES, in order.
    Returns raw_ideas item dicts for insert_raw_ideas; no database access. Stops early when the
    time budget or max_items is reached and returns what it has.
    """
    api_key = os.getenv("STACKEXCHANGE_API_KEY")
    if not api_key:
        print("WARNING: No STACKEXCHANGE_API_KEY set. Using anonymous quota (300/day).")
        print("Register at https://stackapps.com/apps/oauth/register for 10,000/day quota.")

    deadline = time.monotonic() + budget_seconds
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since_utc = None
    if since is not None:
        since_utc = since.astimezone(timezone.utc).replace(tzinfo=None) if since.tzinfo else since

    candidates = []
    for site in SITES:
        window_days = MAX_POST_AGE_YEARS * 365 if site["phrases"] is None else SEARCH_WINDOW_DAYS
        min_date = now - timedelta(days=window_days)
        if since_utc is not None:
            min_date = max(min_date, since_utc)
        seen = set()
        print(f"Fetching questions from {site['site']}...")
        for label, url, params, paged, keyword in _requests(site, api_key, min_date):
            if time.monotonic() >= deadline:
                print(f"  Budget exhausted; returning {len(candidates)} candidates")
                return candidates
            data = _get_json(url, params)
            if data is None:
                if paged:
                    break
                continue
            questions = data.get("items") if isinstance(data, dict) else None
            if not isinstance(questions, list) or not questions:
                print(f"  {label}: No more questions")
                if paged:
                    break
                continue
            print(f"  {label}: Found {len(questions)} questions")

            for question in questions:
                try:
                    item = _candidate(site, question, keyword, api_key, now, min_date, deadline)
                except _BudgetExhausted:
                    print(f"  Budget exhausted; returning {len(candidates)} candidates")
                    return candidates
                if item is None:
                    continue
                if not paged:  # one question can match several phrases
                    if item["source_url"] in seen:
                        continue
                    seen.add(item["source_url"])
                candidates.append(item)
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
