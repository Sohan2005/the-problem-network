import time
from collections import defaultdict, deque
from threading import Lock
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

GET_LIMIT = 60
WINDOW_SECONDS = 60


def client_ip(request: Request) -> str:
    """IP of the caller. App Service appends the connecting address, so the last hop is used."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if parts:
            return parts[-1]
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class SlidingWindowLimiter:
    """In-process limit of GET_LIMIT hits per IP per WINDOW_SECONDS."""

    def __init__(self, limit: int = GET_LIMIT, window_seconds: float = WINDOW_SECONDS):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


class GetRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: Optional[SlidingWindowLimiter] = None):
        super().__init__(app)
        self.limiter = limiter or SlidingWindowLimiter()

    async def dispatch(self, request: Request, call_next):
        if request.method == "GET" and not self.limiter.allow(client_ip(request)):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again in a minute."},
                headers={"Retry-After": "60"},
            )
        return await call_next(request)
