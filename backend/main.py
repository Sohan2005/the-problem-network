import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.briefs import router as briefs_router

_DEFAULT_ORIGIN = "http://localhost:3000"
_ALLOWED_METHODS = ["GET", "OPTIONS"]
_ALLOWED_HEADERS = ["Accept", "Content-Type"]


def allowed_origins() -> list[str]:
    """Comma-separated ALLOWED_ORIGINS, or the local frontend when unset."""
    raw = os.getenv("ALLOWED_ORIGINS", _DEFAULT_ORIGIN)
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or [_DEFAULT_ORIGIN]


def create_app() -> FastAPI:
    app = FastAPI(
        title="The Problem Network API",
        description="Translates real-world technical problems into structured, junior-dev-friendly briefs.",
        version="0.1.0",
    )
    origin_regex = os.getenv("ALLOWED_ORIGIN_REGEX") or None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_origin_regex=origin_regex,
        allow_credentials=False,
        allow_methods=_ALLOWED_METHODS,
        allow_headers=_ALLOWED_HEADERS,
    )
    app.include_router(briefs_router)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "the-problem-network-api"}

    return app


app = create_app()
