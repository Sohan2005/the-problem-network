import os
import unittest
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://invalid:invalid@127.0.0.1:1/none")

from fastapi.testclient import TestClient

from db.queries import list_briefs
from main import create_app
from routes.briefs import get_db

_ENV_KEYS = ("ALLOWED_ORIGINS", "ALLOWED_ORIGIN_REGEX", "ENABLE_DOCS", "ENABLE_ADMIN_ROUTES", "ADMIN_API_KEY")


def build_app(**env):
    previous = {key: os.environ.get(key) for key in _ENV_KEYS}
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    for key, value in env.items():
        os.environ[key] = value
    try:
        return create_app()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class RecordingQuery:
    def __init__(self):
        self.order = ()
        self.limit_value = None
        self.offset_value = None

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args):
        self.order = args
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def all(self):
        return []


class RecordingSession:
    def __init__(self):
        self.query_obj = RecordingQuery()

    def query(self, *args):
        return self.query_obj


class CorsTests(unittest.TestCase):
    def test_allows_configured_origin_and_blocks_others(self):
        client = TestClient(build_app(ALLOWED_ORIGINS="https://briefs.example, http://localhost:3000"))
        allowed = client.get("/health", headers={"Origin": "https://briefs.example"})
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "https://briefs.example")
        self.assertNotIn("access-control-allow-credentials", allowed.headers)
        blocked = client.get("/health", headers={"Origin": "https://evil.example"})
        self.assertIsNone(blocked.headers.get("access-control-allow-origin"))

    def test_allows_vercel_preview_regex(self):
        client = TestClient(build_app(
            ALLOWED_ORIGINS="http://localhost:3000",
            ALLOWED_ORIGIN_REGEX=r"https://.*\.vercel\.app",
        ))
        origin = "https://the-problem-network-git-abc.vercel.app"
        preview = client.get("/health", headers={"Origin": origin})
        self.assertEqual(preview.headers.get("access-control-allow-origin"), origin)


class AdminRouteTests(unittest.TestCase):
    def test_ingest_routes_are_404_when_admin_routes_are_off(self):
        client = TestClient(build_app())
        for path in ("/briefs/ingest/owner/repo", "/briefs/ingest-devpost", "/briefs/ingest-blogs"):
            response = client.post(path, json=["https://example.com/post"])
            self.assertEqual(response.status_code, 404, path)

    def test_admin_key_is_required_when_routes_are_enabled(self):
        client = TestClient(build_app(ENABLE_ADMIN_ROUTES="1", ADMIN_API_KEY="test-admin-key"))
        with mock.patch("routes.admin.fetch_hackathon_challenges") as fetch:
            missing = client.post("/briefs/ingest-devpost")
            wrong = client.post("/briefs/ingest-devpost", headers={"X-Admin-Key": "nope"})
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        fetch.assert_not_called()


class DocsTests(unittest.TestCase):
    def test_docs_are_404_by_default(self):
        client = TestClient(build_app())
        for path in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(client.get(path).status_code, 404, path)


class ListBriefsTests(unittest.TestCase):
    def test_limit_and_offset(self):
        db = RecordingSession()
        self.assertEqual(list_briefs(db, limit=10, offset=25), [])
        self.assertEqual(db.query_obj.limit_value, 10)
        self.assertEqual(db.query_obj.offset_value, 25)
        order_sql = " ".join(str(item) for item in db.query_obj.order).lower()
        self.assertIn("created_at", order_sql)
        self.assertIn("briefs.id", order_sql)

    def test_limit_is_capped_and_offset_is_clamped(self):
        db = RecordingSession()
        list_briefs(db, limit=9000, offset=-4)
        self.assertEqual(db.query_obj.limit_value, 500)
        self.assertEqual(db.query_obj.offset_value, 0)

    def test_route_passes_limit_offset_and_cache_header(self):
        app = build_app()

        def fake_db():
            yield object()

        app.dependency_overrides[get_db] = fake_db
        client = TestClient(app)
        with mock.patch("routes.briefs.list_briefs", return_value=[]) as listed:
            response = client.get("/briefs/?limit=2&offset=3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("cache-control"), "public, max-age=60")
        self.assertEqual(listed.call_args.kwargs["limit"], 2)
        self.assertEqual(listed.call_args.kwargs["offset"], 3)
        with mock.patch("routes.briefs.get_brief_stats", return_value={"total_count": 0, "recent_count": 0, "last_updated": None}):
            stats = client.get("/briefs/stats")
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.headers.get("cache-control"), "public, max-age=60")


class RateLimitTests(unittest.TestCase):
    def test_get_returns_429_past_the_limit(self):
        client = TestClient(build_app())
        headers = {"X-Forwarded-For": "203.0.113.8"}
        for _ in range(60):
            self.assertEqual(client.get("/health", headers=headers).status_code, 200)
        blocked = client.get("/health", headers=headers)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["detail"], "Rate limit exceeded. Try again in a minute.")
        self.assertEqual(blocked.headers.get("retry-after"), "60")
        self.assertEqual(client.get("/health", headers={"X-Forwarded-For": "203.0.113.9"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
