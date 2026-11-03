import os
import unittest
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://invalid:invalid@127.0.0.1:1/none")

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from db.models import Brief, RawIdea, Tag, brief_tags
from db.queries import canonicalize_url, get_brief_by_id, get_brief_tags, list_briefs
from main import create_app
from routes import briefs as briefs_routes
from routes.briefs import TTLCache, get_db
from tests.branch_db import RolledBackTestCase

CACHE_CONTROL = "public, max-age=300, s-maxage=1800, stale-while-revalidate=3600"
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


def fake_db_client():
    """Test client with a fake session and an empty response cache."""
    briefs_routes.cache.clear()
    app = build_app()

    def fake_db():
        yield object()

    app.dependency_overrides[get_db] = fake_db
    return TestClient(app)


def detail_row(**overrides):
    values = {
        "id": 7, "title": "Route tracker", "difficulty": "beginner", "core_task": "Climbers lose track.",
        "recommended_stack": ["Python"], "target_user": "Climbers", "suggested_features": ["Log"],
        "learning_outcomes": ["SQL"], "what_youll_need": "- Python", "how_to_begin": "1. Start",
        "problem_source": None, "problem_url": None, "raw_source": None, "raw_url": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class RecordingQuery:
    def __init__(self):
        self.columns = ()
        self.joins = []
        self.order = ()
        self.limit_value = None
        self.offset_value = None

    def outerjoin(self, target, *args):
        self.joins.append(target)
        return self

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
        self.query_obj.columns = args
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

    def test_selects_card_columns_and_raw_source_only(self):
        db = RecordingSession()
        list_briefs(db)
        self.assertEqual([column.key for column in db.query_obj.columns],
                         ["id", "title", "difficulty", "core_task", "recommended_stack", "raw_source"])
        self.assertEqual(db.query_obj.joins, [RawIdea])

    def test_route_passes_limit_offset_and_cache_header(self):
        client = fake_db_client()
        with mock.patch("routes.briefs.list_briefs", return_value=[]) as listed:
            response = client.get("/briefs/?limit=2&offset=3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("cache-control"), CACHE_CONTROL)
        self.assertEqual(listed.call_args.kwargs["limit"], 2)
        self.assertEqual(listed.call_args.kwargs["offset"], 3)
        with mock.patch("routes.briefs.get_brief_stats", return_value={"total_count": 0, "recent_count": 0, "last_updated": None}):
            stats = client.get("/briefs/stats")
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.headers.get("cache-control"), CACHE_CONTROL)
        with mock.patch("routes.briefs.get_brief_by_id", return_value=detail_row()), \
                mock.patch("routes.briefs.get_brief_tags", return_value=[]):
            detail = client.get("/briefs/7")
        self.assertEqual(detail.headers.get("cache-control"), CACHE_CONTROL)
        with mock.patch("routes.briefs.get_brief_by_id", return_value=None):
            missing = client.get("/briefs/8")
        self.assertEqual(missing.status_code, 404)
        self.assertIsNone(missing.headers.get("cache-control"))


class BriefRouteTests(unittest.TestCase):
    def test_list_marks_ai_sources_and_returns_no_tags(self):
        card = {"title": "T", "difficulty": "beginner", "core_task": "C", "recommended_stack": ["Go"]}
        rows = [SimpleNamespace(id=1, raw_source="hackernews", **card), SimpleNamespace(id=2, raw_source="ai_suggested", **card),
                SimpleNamespace(id=3, raw_source=None, **card)]
        with mock.patch("routes.briefs.list_briefs", return_value=rows):
            body = fake_db_client().get("/briefs/").json()
        self.assertEqual([item["has_title_mark"] for item in body], [False, True, False])
        self.assertEqual(set(body[0]), {"id", "title", "difficulty", "core_task", "recommended_stack", "has_title_mark"})

    def test_detail_links_real_sources_and_returns_tags(self):
        url = "https://news.ycombinator.com/item?id=1"
        with mock.patch("routes.briefs.get_brief_by_id", return_value=detail_row(raw_source="hackernews", raw_url=url)), \
                mock.patch("routes.briefs.get_brief_tags", return_value=["python"]) as tags:
            body = fake_db_client().get("/briefs/7").json()
        tags.assert_called_once_with(mock.ANY, 7)
        self.assertEqual((body["source_url"], body["source_platform"], body["tags"], body["has_title_mark"]),
                         (url, "hackernews", ["python"], False))
        self.assertEqual(body["how_to_begin"], "1. Start")

    def test_detail_hides_ai_links_and_prefers_problem_source(self):
        with mock.patch("routes.briefs.get_brief_by_id", return_value=detail_row(raw_source="ai_suggested", raw_url="https://ai.example")), \
                mock.patch("routes.briefs.get_brief_tags", return_value=[]):
            ai = fake_db_client().get("/briefs/7").json()
        self.assertEqual((ai["source_url"], ai["source_platform"], ai["has_title_mark"]), (None, "ai_suggested", True))
        problem_url = "https://softwarerecs.stackexchange.com/q/1"
        row = detail_row(problem_source="stackexchange_softwarerecs", problem_url=problem_url, raw_source="hackernews", raw_url="https://x")
        with mock.patch("routes.briefs.get_brief_by_id", return_value=row), mock.patch("routes.briefs.get_brief_tags", return_value=[]):
            legacy = fake_db_client().get("/briefs/7").json()
        self.assertEqual((legacy["source_url"], legacy["source_platform"]), (problem_url, "stackexchange_softwarerecs"))

    def test_detail_404(self):
        with mock.patch("routes.briefs.get_brief_by_id", return_value=None):
            self.assertEqual(fake_db_client().get("/briefs/7").status_code, 404)


class ResponseCacheTests(unittest.TestCase):
    def test_list_is_cached_per_query(self):
        client = fake_db_client()
        with mock.patch("routes.briefs.list_briefs", return_value=[]) as listed:
            for path in ("/briefs/?tag=go", "/briefs/?tag=go", "/briefs/?tag=rust", "/briefs/?tag=go&limit=5",
                         "/briefs/?tag=go&sort=difficulty_asc", "/briefs/?tag=go"):
                self.assertEqual(client.get(path).status_code, 200)
        self.assertEqual(listed.call_count, 4)

    def test_detail_and_stats_are_cached_but_not_found_is_not(self):
        client = fake_db_client()
        with mock.patch("routes.briefs.get_brief_by_id", return_value=detail_row()) as found, \
                mock.patch("routes.briefs.get_brief_tags", return_value=[]) as tags:
            first, second = client.get("/briefs/7").json(), client.get("/briefs/7").json()
        self.assertEqual(first, second)
        self.assertEqual((found.call_count, tags.call_count), (1, 1))
        with mock.patch("routes.briefs.get_brief_by_id", return_value=None) as missing:
            self.assertEqual([client.get("/briefs/8").status_code for _ in range(2)], [404, 404])
        self.assertEqual(missing.call_count, 2)
        stats = {"total_count": 1, "recent_count": 1, "last_updated": None}
        with mock.patch("routes.briefs.get_brief_stats", return_value=stats) as counted:
            self.assertEqual([client.get("/briefs/stats").json() for _ in range(2)], [stats, stats])
        self.assertEqual(counted.call_count, 1)

    def test_entries_expire_after_ttl(self):
        now = [0.0]
        cache = TTLCache(ttl_seconds=1800, max_entries=10, clock=lambda: now[0])
        compute = mock.Mock(side_effect=["a", "b"])
        self.assertEqual(cache.get_or_set("k", compute), "a")
        now[0] = 1799.0
        self.assertEqual(cache.get_or_set("k", compute), "a")
        now[0] = 1800.0
        self.assertEqual(cache.get_or_set("k", compute), "b")
        self.assertEqual(compute.call_count, 2)

    def test_size_cap_drops_least_recently_used(self):
        cache = TTLCache(ttl_seconds=1800, max_entries=2)
        cache.get_or_set("a", lambda: 1)
        cache.get_or_set("b", lambda: 2)
        cache.get_or_set("a", lambda: 0)
        cache.get_or_set("c", lambda: 3)
        self.assertEqual(len(cache), 2)
        self.assertEqual((cache.get_or_set("a", lambda: 0), cache.get_or_set("b", lambda: 0)), (1, 0))

    def test_production_limits(self):
        self.assertEqual((briefs_routes.CACHE_TTL_SECONDS, briefs_routes.CACHE_MAX_ENTRIES), (1800, 256))


class BriefQueryBranchTests(RolledBackTestCase):
    """The API queries on the test branch: explicit columns, no embedding, source through the outer join."""

    def setUp(self):
        super().setUp()
        self.tag = f"egress-{uuid.uuid4().hex[:12]}"
        self.real = self.make_brief("hackernews", datetime(2099, 1, 2))
        self.ai = self.make_brief("ai_suggested", datetime(2099, 1, 1))
        tag = Tag(name=self.tag)
        self.db.add(tag)
        self.db.flush()
        self.db.execute(brief_tags.insert().values(brief_id=self.real.id, tag_id=tag.id))
        self.db.commit()
        self.db.expunge_all()

    def make_brief(self, source, created_at):
        url = f"https://news.ycombinator.com/item?id={uuid.uuid4().int % 10**9}"
        raw = RawIdea(source=source, source_url=url, canonical_url=canonicalize_url(url), raw_title="Ask HN",
                      raw_text="text", embedding=[0.5] * 3072)
        self.db.add(raw)
        self.db.flush()
        brief = Brief(title=f"Brief {source}", difficulty="beginner", core_task="Core task", recommended_stack=["Python"],
                      raw_idea_id=raw.id, created_at=created_at, how_to_begin="1. Start", embedding=[0.5] * 3072)
        self.db.add(brief)
        self.db.flush()
        return SimpleNamespace(id=brief.id, url=url)

    def test_list_rows_carry_raw_source_and_no_embedding(self):
        rows = list_briefs(self.db, limit=2)
        self.assertEqual([(row.id, row.raw_source) for row in rows], [(self.real.id, "hackernews"), (self.ai.id, "ai_suggested")])
        self.assertNotIn("embedding", rows[0]._fields)

    def test_detail_row_and_tags(self):
        row = get_brief_by_id(self.db, self.real.id)
        self.assertEqual((row.raw_source, row.raw_url, row.problem_source, row.how_to_begin), ("hackernews", self.real.url, None, "1. Start"))
        self.assertNotIn("embedding", row._fields)
        self.assertEqual(get_brief_tags(self.db, self.real.id), [self.tag])
        self.assertEqual(get_brief_tags(self.db, self.ai.id), [])
        self.assertIsNone(get_brief_by_id(self.db, -1))

    def test_embeddings_are_deferred_but_still_load_on_access(self):
        brief = self.db.get(Brief, self.real.id)
        raw = self.db.query(RawIdea).filter(RawIdea.id == brief.raw_idea_id).one()
        self.assertIn("embedding", inspect(brief).unloaded)
        self.assertIn("embedding", inspect(raw).unloaded)
        self.assertEqual((len(brief.embedding), len(raw.embedding)), (3072, 3072))


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
