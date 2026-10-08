"""
AI-suggested ideas: one Gemini call (no search tool) returns up to IDEAS_PER_CALL realistic first-person need
statements on the day's theme. They have no real source post: source 'ai_suggested', confidence_flag 'low', a
synthetic ai-idea:// URL derived from the title, and source_date = now (UTC).

fetch_candidates has no database access: the caller reads the topics to avoid with load_avoid_titles (one query)
and passes them in, together with the LLM client (anything with generate(prompt) -> str).
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SOURCE = "ai_suggested"
IDEAS_PER_CALL = 8
DEFAULT_MAX_ITEMS = IDEAS_PER_CALL
AVOID_LIMIT = 30  # recent ai_suggested titles and recent published brief titles, each
STATEMENT_WORDS = (60, 150)
TITLE_MAX = 120

THEMES = [
    "students", "freelancers", "teachers", "small shops", "health tracking", "accessibility", "hobbies",
    "developer workflows", "family organisation", "local community", "pet owners", "gardeners",
    "home cooking and meal planning", "personal budgeting habits", "roommates and shared homes", "commuters",
    "volunteers and small non-profits", "musicians", "fitness beginners", "parents of young children",
    "older adults", "remote workers", "job seekers", "travellers", "readers and book clubs",
    "amateur sports teams and coaches", "family caregivers", "language learners", "DIY and makers",
    "recycling and sustainable habits",
]

PROMPT = """You write realistic need statements for a site that turns everyday problems into student portfolio projects.

Theme for today: {theme}

Write up to {count} distinct ideas. Each one is a first-person need statement of 60 to 150 words in the voice of one
real person describing a recurring problem in their own life or work ("I keep ... and wish there was ..."). Name the
concrete situation, what they do today, why it is painful and what kind of simple app or website would help. Each
need must be small enough for one student to build as a web or mobile app: no payments, marketplaces, hardware,
enterprise integrations or machine-learning infrastructure. Do not name existing products as the solution and do not
claim that the app already exists.

Give each idea a short title of 3 to 8 words naming the app.

Avoid these topics, which are already covered:
{avoid}

Return ONLY valid JSON in this exact shape:
{{"ideas": [{{"title": string, "statement": string}}]}}
Do not include any markdown, explanations, or text outside the JSON."""

def theme_for(day) -> str:
    """Theme seed rotating by day of year."""
    return THEMES[(day.timetuple().tm_yday - 1) % len(THEMES)]

def idea_url(title: str) -> str:
    return "ai-idea://" + hashlib.sha1(title.strip().lower().encode("utf-8")).hexdigest()[:16]

def build_prompt(theme: str, avoid_titles, count: int = IDEAS_PER_CALL) -> str:
    avoid = "\n".join(f"- {title}" for title in avoid_titles if title) or "- (none)"
    return PROMPT.format(theme=theme, count=count, avoid=avoid)

def parse_ideas(response_text: str) -> list:
    """[(title, statement)] for well-formed ideas; raises ValueError when the reply is not the expected JSON."""
    text = response_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON response from Gemini")
    ideas = data.get("ideas") if isinstance(data, dict) else None
    if not isinstance(ideas, list):
        raise ValueError("Missing ideas list")
    parsed = []
    for idea in ideas:
        if not isinstance(idea, dict):
            continue
        title, statement = idea.get("title"), idea.get("statement")
        if not isinstance(title, str) or not isinstance(statement, str):
            continue
        title, statement = " ".join(title.split()), " ".join(statement.split())
        if title and len(title) <= TITLE_MAX and STATEMENT_WORDS[0] <= len(statement.split()) <= STATEMENT_WORDS[1]:
            parsed.append((title, statement))
    return parsed

def load_avoid_titles(db, limit: int = AVOID_LIMIT) -> list:
    """The `limit` most recent ai_suggested titles and the `limit` most recent published brief titles, in one query."""
    from sqlalchemy import select, union_all
    from db.models import Brief, RawIdea
    ai = (select(RawIdea.raw_title.label("title")).where(RawIdea.source == SOURCE)
          .order_by(RawIdea.fetched_at.desc(), RawIdea.id.desc()).limit(limit).subquery())
    briefs = select(Brief.title.label("title")).order_by(Brief.created_at.desc(), Brief.id.desc()).limit(limit).subquery()
    return [title for (title,) in db.execute(union_all(select(ai.c.title), select(briefs.c.title)))]

def fetch_candidates(*, budget_seconds, max_items, since=None, avoid_titles=(), llm_client=None, now=None) -> list:
    """
    One Gemini call for up to min(max_items, IDEAS_PER_CALL) ideas on today's theme; returns raw_ideas item dicts.
    `since` is accepted for the adapter contract and ignored. No call when the budget or max_items is zero.
    Quota and LLM errors propagate to the caller.
    """
    count = min(max_items, IDEAS_PER_CALL)
    if budget_seconds <= 0 or count <= 0:
        return []
    now = now or datetime.now(timezone.utc)
    if llm_client is None:
        from llm.gemini import GeminiClient
        llm_client = GeminiClient(timeout_seconds=max(1, min(60, int(budget_seconds))))
    ideas = parse_ideas(llm_client.generate(build_prompt(theme_for(now), avoid_titles, count)))
    return [
        {
            "source": SOURCE,
            "source_url": idea_url(title),
            "raw_title": title,
            "raw_text": statement,
            "author": None,
            "source_date": now,
            "matched_keyword": theme_for(now),
            "confidence_flag": "low",
        }
        for title, statement in ideas[:count]
    ]
