"""
Anonymous visit counter. POST /visits adds one to today's count; GET /visits/count returns the cached totals.
Nothing about the visitor is stored: the rate limiter keeps a salted hash of the caller's IP in memory only, and the
database holds one number per UTC day.
"""
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db.database import get_db
from db.queries import get_visit_counts, record_visit
from rate_limit import SlidingWindowLimiter, client_ip, limiter_key
from routes.briefs import CACHE_CONTROL, in_new_session, snapshot_cache

router = APIRouter()

VISIT_LIMIT = 20
VISIT_WINDOW_SECONDS = 60 * 60
VISITS_KEY = ("visits",)

BOT_AGENT = re.compile(
    r"bot|crawl|spider|slurp|scrap|headless|lighthouse|pagespeed|preview|monitor|uptime|pingdom|"
    r"curl|wget|python|httpx|axios|okhttp|go-http-client|java/|libwww|node-fetch|"
    r"facebookexternalhit|embedly|whatsapp|telegram|discord|slack",
    re.IGNORECASE,
)
PREFETCH_HEADERS = ("purpose", "sec-purpose", "x-purpose", "x-moz")
PREFETCH_VALUES = ("prefetch", "prerender", "preview")

visit_limiter = SlidingWindowLimiter(limit=VISIT_LIMIT, window_seconds=VISIT_WINDOW_SECONDS)


def utc_today():
    return datetime.now(timezone.utc).date()


def is_bot_or_prefetch(headers) -> bool:
    """True for a missing or automated User-Agent and for prefetch, prerender or link-preview requests."""
    agent = headers.get("user-agent", "")
    if not agent.strip() or BOT_AGENT.search(agent):
        return True
    for name in PREFETCH_HEADERS:
        value = headers.get(name, "").lower()
        if any(word in value for word in PREFETCH_VALUES):
            return True
    return False


@router.post("/visits")
def post_visit(request: Request, db: Session = Depends(get_db)):
    """Count one visit. Bots and prefetches get 204 without being counted; over the limit gets 429."""
    headers = {"Cache-Control": "no-store"}
    if is_bot_or_prefetch(request.headers):
        return Response(status_code=204, headers=headers)
    if not visit_limiter.allow(limiter_key(client_ip(request))):
        return Response(status_code=429, headers={**headers, "Retry-After": str(VISIT_WINDOW_SECONDS)})
    try:
        record_visit(db, utc_today())
    except SQLAlchemyError as exc:
        db.rollback()
        logging.warning("visit not recorded: %s", type(exc).__name__)
        return Response(status_code=503, headers=headers)
    return Response(status_code=204, headers=headers)


def visit_counts(db: Session) -> dict:
    return get_visit_counts(db, utc_today())


@router.get("/visits/count")
def get_visit_count(response: Response, db: Session = Depends(get_db)):
    """Total visits and today's visits (UTC), served from the snapshot cache."""
    response.headers["Cache-Control"] = CACHE_CONTROL
    return snapshot_cache.get(VISITS_KEY, lambda: visit_counts(db), in_new_session(visit_counts))
