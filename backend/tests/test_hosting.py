import os
import unittest
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://invalid:invalid@127.0.0.1:1/none")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, text

from db.models import Brief, Problem, RawIdea, Tag, brief_tags
from db.queries import canonicalize_url, get_brief_by_id, list_all_briefs
from main import create_app
from rate_limit import GetRateLimitMiddleware, SlidingWindowLimiter, limiter_key
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
    """Test client with a fake session and empty caches."""
    briefs_routes.cache.clear()
    briefs_routes.snapshot_cache.clear()
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
        "problem": None, "raw_idea": None, "tags": [], "importance": None,
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


def card_row(id, stack=None, title="T", core_task="C", difficulty="beginner", raw_source="hackernews", importance=None):
    return SimpleNamespace(id=id, title=title, difficulty=difficulty, core_task=core_task,
                           recommended_stack=stack if stack is not None else ["Python"], raw_source=raw_source,
                           importance=importance)


class ListBriefsTests(unittest.TestCase):
    def test_selects_every_brief_newest_first(self):
        db = RecordingSession()
        self.assertEqual(list_all_briefs(db), [])
        self.assertIsNone(db.query_obj.limit_value)
        self.assertIsNone(db.query_obj.offset_value)
        order_sql = " ".join(str(item) for item in db.query_obj.order).lower()
        self.assertIn("created_at", order_sql)
        self.assertIn("briefs.id", order_sql)

    def test_selects_card_columns_and_raw_source_only(self):
        db = RecordingSession()
        list_all_briefs(db)
        self.assertEqual([column.key for column in db.query_obj.columns],
                         ["id", "title", "difficulty", "core_task", "recommended_stack", "importance", "raw_source"])
        self.assertEqual(db.query_obj.joins, [RawIdea])

    def test_route_pages_the_snapshot_and_sets_cache_header(self):
        client = fake_db_client()
        with mock.patch("routes.briefs.list_all_briefs", return_value=[card_row(i) for i in range(1, 6)]):
            response = client.get("/briefs/?limit=2&offset=3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("cache-control"), CACHE_CONTROL)
        body = response.json()
        self.assertEqual([card["id"] for card in body["items"]], [4, 5])
        self.assertEqual((body["total"], body["offset"], body["limit"], body["has_more"]), (5, 3, 2, False))
        with mock.patch("routes.briefs.get_brief_stats", return_value={"total_count": 0, "recent_count": 0, "last_updated": None}):
            stats = client.get("/briefs/stats")
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.headers.get("cache-control"), CACHE_CONTROL)
        with mock.patch("routes.briefs.get_brief_by_id", return_value=detail_row()):
            detail = client.get("/briefs/7")
        self.assertEqual(detail.headers.get("cache-control"), CACHE_CONTROL)
        with mock.patch("routes.briefs.get_brief_by_id", return_value=None):
            missing = client.get("/briefs/8")
        self.assertEqual(missing.status_code, 404)
        self.assertIsNone(missing.headers.get("cache-control"))


class BriefRouteTests(unittest.TestCase):
    def test_list_marks_ai_sources_and_returns_no_tags(self):
        card = {"title": "T", "difficulty": "beginner", "core_task": "C", "recommended_stack": ["Go"], "importance": None}
        rows = [SimpleNamespace(id=1, raw_source="hackernews", **card), SimpleNamespace(id=2, raw_source="ai_suggested", **card),
                SimpleNamespace(id=3, raw_source=None, **card)]
        with mock.patch("routes.briefs.list_all_briefs", return_value=rows):
            body = fake_db_client().get("/briefs/").json()["items"]
        self.assertEqual([item["has_title_mark"] for item in body], [False, True, False])
        self.assertEqual(set(body[0]), {"id", "title", "difficulty", "core_task", "recommended_stack", "importance",
                                        "category", "has_title_mark"})

    def test_detail_links_real_sources_and_returns_tags(self):
        url = "https://news.ycombinator.com/item?id=1"
        row = detail_row(raw_idea=SimpleNamespace(source="hackernews", source_url=url), tags=[SimpleNamespace(name="python")])
        with mock.patch("routes.briefs.get_brief_by_id", return_value=row):
            body = fake_db_client().get("/briefs/7").json()
        self.assertEqual((body["source_url"], body["source_platform"], body["tags"], body["has_title_mark"]),
                         (url, "hackernews", ["python"], False))
        self.assertEqual(body["how_to_begin"], "1. Start")

    def test_detail_hides_ai_links_and_prefers_problem_source(self):
        ai_row = detail_row(raw_idea=SimpleNamespace(source="ai_suggested", source_url="https://ai.example"))
        with mock.patch("routes.briefs.get_brief_by_id", return_value=ai_row):
            ai = fake_db_client().get("/briefs/7").json()
        self.assertEqual((ai["source_url"], ai["source_platform"], ai["has_title_mark"]), (None, "ai_suggested", True))
        problem_url = "https://softwarerecs.stackexchange.com/q/1"
        row = detail_row(problem=SimpleNamespace(source="stackexchange_softwarerecs", source_url=problem_url),
                         raw_idea=SimpleNamespace(source="hackernews", source_url="https://x"))
        with mock.patch("routes.briefs.get_brief_by_id", return_value=row):
            legacy = fake_db_client().get("/briefs/7").json()
        self.assertEqual((legacy["source_url"], legacy["source_platform"]), (problem_url, "stackexchange_softwarerecs"))

    def test_detail_404(self):
        with mock.patch("routes.briefs.get_brief_by_id", return_value=None):
            self.assertEqual(fake_db_client().get("/briefs/7").status_code, 404)


class ResponseCacheTests(unittest.TestCase):
    def test_one_snapshot_query_serves_every_list_query(self):
        client = fake_db_client()
        with mock.patch("routes.briefs.list_all_briefs", return_value=[]) as listed:
            for path in ("/briefs/?tag=go", "/briefs/?tag=go", "/briefs/?tag=rust", "/briefs/?tag=go&limit=5",
                         "/briefs/?tag=go&sort=difficulty_asc", "/briefs/?search=x&difficulty=Advanced", "/briefs/"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get("cache-control"), CACHE_CONTROL)
        self.assertEqual(listed.call_count, 1)

    def test_detail_and_stats_are_cached_but_not_found_is_not(self):
        client = fake_db_client()
        with mock.patch("routes.briefs.get_brief_by_id", return_value=detail_row()) as found:
            first, second = client.get("/briefs/7").json(), client.get("/briefs/7").json()
        self.assertEqual(first, second)
        self.assertEqual(found.call_count, 1)
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
        self.assertEqual((briefs_routes.SNAPSHOT_TTL_SECONDS, briefs_routes.REFRESH_RETRY_SECONDS), (3600, 300))
        self.assertEqual((briefs_routes.DEFAULT_PAGE_SIZE, briefs_routes.MAX_PAGE_SIZE), (24, 100))


class StaleWhileRefreshCacheTests(unittest.TestCase):
    def setUp(self):
        self.now = [0.0]
        self.spawned = []
        self.cache = briefs_routes.StaleWhileRefreshCache(ttl_seconds=3600, retry_seconds=300,
                                                          clock=lambda: self.now[0], spawn=self.spawned.append)

    def test_missing_value_is_computed_in_the_request_and_fresh_hits_start_nothing(self):
        background = mock.Mock(return_value="new")
        self.assertEqual(self.cache.get("k", lambda: "first", background), "first")
        self.now[0] = 3599.0
        self.assertEqual(self.cache.get("k", lambda: "unused", background), "first")
        self.assertEqual(self.spawned, [])

    def test_stale_value_is_served_while_one_background_refresh_runs(self):
        self.cache.get("a", lambda: "a1", None)
        self.cache.get("b", lambda: "b1", None)
        self.now[0] = 3600.0
        self.assertEqual(self.cache.get("a", None, lambda: "a2"), "a1")
        self.assertEqual(self.cache.get("a", None, lambda: "a3"), "a1")
        self.assertEqual(self.cache.get("b", None, lambda: "b2"), "b1")
        self.assertEqual(len(self.spawned), 1)
        self.spawned.pop()()
        self.assertEqual(self.cache.get("a", None, None), "a2")
        self.assertEqual(self.cache.get("b", None, lambda: "b2"), "b1")
        self.assertEqual(len(self.spawned), 1)
        self.spawned.pop()()
        self.assertEqual(self.cache.get("b", None, None), "b2")

    def test_failed_refresh_keeps_the_old_value_and_retries_later(self):
        self.cache.get("k", lambda: "old", None)
        self.now[0] = 3600.0

        def fail():
            raise RuntimeError("database unavailable")

        self.assertEqual(self.cache.get("k", None, fail), "old")
        with self.assertLogs(level="WARNING"):
            self.spawned.pop()()
        self.now[0] = 3899.0
        self.assertEqual(self.cache.get("k", None, lambda: "new"), "old")
        self.assertEqual(self.spawned, [])
        self.now[0] = 3900.0
        self.cache.get("k", None, lambda: "new")
        self.spawned.pop()()
        self.assertEqual(self.cache.get("k", None, None), "new")

    def test_background_refresh_uses_its_own_session(self):
        session = mock.Mock()
        with mock.patch("routes.briefs.SessionLocal", return_value=session):
            self.assertEqual(briefs_routes.in_new_session(lambda db: db)(), session)
        session.close.assert_called_once()


class SearchTests(unittest.TestCase):
    ROWS = [
        card_row(1, ["React", "Node.js"], title="Climbing log", difficulty="intermediate"),
        card_row(2, ["JavaScript/TypeScript"]),
        card_row(3, ["Python", "PostgreSQL"], difficulty="advanced"),
        card_row(4, ["Kotlin/Java"]),
        card_row(5, ["Go"]),
        card_row(6, ["MongoDB", "Web development"], core_task="Track gigs for musicians."),
        SimpleNamespace(id=7, title="Empty", difficulty="beginner", core_task="C", recommended_stack=None, raw_source=None,
                        importance=None),
    ]

    def ids(self, query):
        with mock.patch("routes.briefs.list_all_briefs", return_value=self.ROWS):
            response = fake_db_client().get(f"/briefs/?limit=100&{query}")
        self.assertEqual(response.status_code, 200)
        return [card["id"] for card in response.json()["items"]]

    def test_stack_filter_ignores_case(self):
        for tag in ("react", "React", "REACT", " react "):
            self.assertEqual(self.ids(f"tag={tag}"), [1], tag)

    def test_stack_filter_matches_partial_words_and_compound_items(self):
        self.assertEqual(self.ids("tag=reac"), [1])
        self.assertEqual(self.ids("tag=pyth"), [3])
        self.assertEqual(self.ids("tag=typescript"), [2])
        self.assertEqual(self.ids("tag=web"), [6])

    def test_stack_filter_aliases(self):
        self.assertEqual(self.ids("tag=js"), [2])
        self.assertEqual(self.ids("tag=ts"), [2])
        for tag in ("node", "nodejs", "node.js", "Node-JS"):
            self.assertEqual(self.ids(f"tag={tag}"), [1], tag)
        self.assertEqual(self.ids("tag=postgres"), [3])
        self.assertEqual(self.ids("tag=py"), [3])

    def test_short_terms_and_java_match_whole_words_only(self):
        self.assertEqual(self.ids("tag=go"), [5])
        self.assertEqual(self.ids("tag=java"), [4])
        self.assertEqual(self.ids("tag=jav"), [2, 4])

    def test_every_term_must_match(self):
        for tag in ("react node", "react, node", "React/Node.js"):
            self.assertEqual(self.ids(f"tag={tag}"), [1], tag)
        self.assertEqual(self.ids("tag=react python"), [])

    def test_search_box_covers_title_core_task_and_stack(self):
        self.assertEqual(self.ids("search=python"), [3])
        self.assertEqual(self.ids("search=climbing react"), [1])
        self.assertEqual(self.ids("search=MUSICIAN"), [6])
        self.assertEqual(self.ids("search=climbing python"), [])

    def test_no_match_and_empty_queries(self):
        self.assertEqual(self.ids("tag=zzzz"), [])
        self.assertEqual(self.ids("search=zzzz"), [])
        self.assertEqual(self.ids("tag=&search="), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(self.ids("tag=,"), [1, 2, 3, 4, 5, 6, 7])

    def test_filters_combine_with_difficulty_and_sort(self):
        self.assertEqual(self.ids("tag=react&difficulty=Intermediate"), [1])
        self.assertEqual(self.ids("tag=react&difficulty=beginner"), [])
        self.assertEqual(self.ids("sort=difficulty_asc"), [2, 4, 5, 6, 7, 1, 3])
        self.assertEqual(self.ids("sort=difficulty_desc"), [3, 1, 7, 6, 5, 4, 2])



class PagingTests(unittest.TestCase):
    """305 briefs, newest first: id 305 is the newest, id 1 the oldest (only one with Elixir)."""

    ROWS = [card_row(i, ["Elixir"] if i == 1 else ["Python"], title="Oldest" if i == 1 else f"Brief {i}",
                     difficulty=("beginner", "intermediate", "advanced")[i % 3])
            for i in range(305, 0, -1)]

    def setUp(self):
        patcher = mock.patch("routes.briefs.list_all_briefs", return_value=self.ROWS)
        self.listed = patcher.start()
        self.addCleanup(patcher.stop)
        self.client = fake_db_client()

    def page(self, query=""):
        response = self.client.get(f"/briefs/?{query}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("cache-control"), CACHE_CONTROL)
        return response.json()

    def walk(self, query=""):
        """Every page of a query through has_more; returns all ids and the totals seen."""
        ids, totals, offset = [], set(), 0
        while True:
            body = self.page(f"{query}&offset={offset}")
            ids += [card["id"] for card in body["items"]]
            totals.add(body["total"])
            if not body["has_more"]:
                return ids, totals
            offset += body["limit"]

    def test_default_page_is_24_and_every_brief_is_reachable_by_paging(self):
        first = self.page()
        self.assertEqual((len(first["items"]), first["total"], first["limit"], first["has_more"]), (24, 305, 24, True))
        ids, totals = self.walk()
        self.assertEqual(ids, list(range(305, 0, -1)))
        self.assertEqual(totals, {305})
        self.assertEqual(self.listed.call_count, 1)

    def test_page_size_is_capped(self):
        body = self.page("limit=5000")
        self.assertEqual((len(body["items"]), body["limit"], body["has_more"]), (100, 100, True))
        last = self.page("limit=100&offset=300")
        self.assertEqual(([card["id"] for card in last["items"]], last["has_more"]), ([5, 4, 3, 2, 1], False))
        self.assertEqual(self.page("offset=900")["items"], [])
        self.assertEqual(self.client.get("/briefs/?limit=0").status_code, 422)

    def test_search_and_stack_filter_reach_the_oldest_brief(self):
        for query in ("search=oldest", "tag=elixir"):
            body = self.page(query)
            self.assertEqual(([card["id"] for card in body["items"]], body["total"], body["has_more"]), ([1], 1, False), query)

    def test_filters_and_sort_run_over_every_brief_before_paging(self):
        beginner = [i for i in range(305, 0, -1) if i % 3 == 0]
        ids, totals = self.walk("difficulty=Beginner&limit=10")
        self.assertEqual((ids, totals), (beginner, {len(beginner)}))
        expected = sorted(range(1, 306), key=lambda i: (i % 3, i))  # i % 3 indexes the levels in difficulty order
        ids, totals = self.walk("sort=difficulty_asc&limit=24")
        self.assertEqual((ids, totals), (expected, {305}))
        second = self.page("sort=difficulty_asc&offset=24")
        self.assertEqual([card["id"] for card in second["items"]], expected[24:48])
        self.assertEqual(self.page("tag=python&difficulty=advanced&limit=100")["total"], len([i for i in range(2, 306) if i % 3 == 2]))

    def test_saved_ids_return_only_those_briefs(self):
        body = self.page("ids=1,150,305,9999,abc,150&limit=100")
        self.assertEqual(([card["id"] for card in body["items"]], body["total"], body["has_more"]), ([305, 150, 1], 3, False))
        self.assertEqual(self.page("ids=")["items"], [])
        self.assertEqual(self.page("ids=" + ",".join(str(i) for i in range(1, 306)))["total"], 305)


class BriefQueryBranchTests(RolledBackTestCase):
    """The API queries on the test branch: the list selects explicit columns, the detail loads no embedding."""

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
        rows = list_all_briefs(self.db)[:2]
        self.assertEqual([(row.id, row.raw_source) for row in rows], [(self.real.id, "hackernews"), (self.ai.id, "ai_suggested")])
        self.assertNotIn("embedding", rows[0]._fields)

    def test_detail_loads_only_needed_columns(self):
        brief = get_brief_by_id(self.db, self.real.id)
        self.assertEqual((brief.how_to_begin, brief.raw_idea.source, brief.raw_idea.source_url), ("1. Start", "hackernews", self.real.url))
        self.assertIn("embedding", inspect(brief).unloaded)
        self.assertTrue({"embedding", "raw_text"} <= inspect(brief.raw_idea).unloaded)
        self.assertEqual([t.name for t in brief.tags], [self.tag])
        self.assertIsNone(brief.problem)
        self.assertIsNone(get_brief_by_id(self.db, -1))

    def test_embeddings_are_deferred_but_still_load_on_access(self):
        brief = self.db.get(Brief, self.real.id)
        raw = self.db.query(RawIdea).filter(RawIdea.id == brief.raw_idea_id).one()
        self.assertIn("embedding", inspect(brief).unloaded)
        self.assertIn("embedding", inspect(raw).unloaded)
        self.assertEqual((len(brief.embedding), len(raw.embedding)), (3072, 3072))


class DetailRouteBranchTests(RolledBackTestCase):
    """
    Regression for the detail 500 after the egress deploy: GET /briefs/{id} for every brief shape on the test branch.
    No embedding is selected and the problems table is only queried for briefs that have a problem_id.
    """

    def setUp(self):
        super().setUp()
        self.statements = []
        event.listen(self.conn, "before_cursor_execute", self.record)
        self.tag = f"detail-{uuid.uuid4().hex[:12]}"
        self.shapes = {
            "raw": self.brief(raw=self.raw_idea("hackernews")),
            "ai": self.brief(raw=self.raw_idea("ai_suggested")),
            "problem": self.brief(problem=self.problem("stackexchange_softwarerecs")),
            "problem_and_raw": self.brief(problem=self.problem("github"), raw=self.raw_idea("ai_suggested")),
            "no_links": self.brief(),
        }
        tag = Tag(name=self.tag)
        self.db.add(tag)
        self.db.flush()
        self.db.execute(brief_tags.insert().values(brief_id=self.shapes["raw"].id, tag_id=tag.id))
        self.db.commit()
        app = build_app()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        event.remove(self.conn, "before_cursor_execute", self.record)
        briefs_routes.cache.clear()
        super().tearDown()

    def record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def url(self):
        return f"https://news.ycombinator.com/item?id={uuid.uuid4().int % 10**9}"

    def raw_idea(self, source):
        url = self.url()
        row = RawIdea(source=source, source_url=url, canonical_url=canonicalize_url(url), raw_title="Ask HN",
                      raw_text="text", embedding=[0.5] * 3072)
        self.db.add(row)
        self.db.flush()
        return SimpleNamespace(id=row.id, url=url)

    def problem(self, source):
        url = self.url()
        row = Problem(source=source, source_url=url, raw_text="text", embedding=[0.5] * 3072)
        self.db.add(row)
        self.db.flush()
        return SimpleNamespace(id=row.id, url=url)

    def brief(self, raw=None, problem=None):
        row = Brief(title="Shape", difficulty="beginner", core_task="Core task", recommended_stack=["Python"],
                    raw_idea_id=raw and raw.id, problem_id=problem and problem.id, embedding=[0.5] * 3072)
        self.db.add(row)
        self.db.flush()
        return SimpleNamespace(id=row.id, raw=raw, problem=problem)

    def get(self, shape):
        briefs_routes.cache.clear()
        self.db.expunge_all()
        self.statements.clear()
        response = self.client.get(f"/briefs/{self.shapes[shape].id}")
        self.db.rollback()
        self.assertEqual(response.status_code, 200, shape)
        selects = [s.lower() for s in self.statements if s.lstrip().lower().startswith("select")]
        self.assertFalse([s for s in selects if "embedding" in s], f"{shape}: embedding selected")
        return response.json(), any("problems" in s for s in selects)

    def test_every_shape(self):
        shapes = self.shapes
        expected = {
            "raw": ("hackernews", shapes["raw"].raw.url, False, [self.tag], False),
            "ai": ("ai_suggested", None, True, [], False),
            "problem": ("stackexchange_softwarerecs", shapes["problem"].problem.url, False, [], True),
            "problem_and_raw": ("github", None, True, [], True),
            "no_links": (None, None, False, [], False),
        }
        for shape, want in expected.items():
            body, problems_queried = self.get(shape)
            got = (body["source_platform"], body["source_url"], body["has_title_mark"], body["tags"], problems_queried)
            self.assertEqual(got, want, shape)
            self.assertEqual((body["id"], body["core_task"], body["recommended_stack"]), (shapes[shape].id, "Core task", ["Python"]))

    def test_briefs_without_problem_link_survive_an_unusable_problems_table(self):
        """The 7156747 detail query joined problems for every brief and failed with UndefinedTable/UndefinedColumn here."""
        for ddl in ("ALTER TABLE problems RENAME TO problems_hidden_for_test",
                    "ALTER TABLE problems RENAME COLUMN source TO source_hidden_for_test"):
            hidden = self.conn.begin_nested()
            self.conn.execute(text(ddl))
            try:
                for shape in ("raw", "ai", "no_links"):
                    body, problems_queried = self.get(shape)
                    self.assertFalse(problems_queried, shape)
                    self.assertEqual(body["id"], self.shapes[shape].id)
            finally:
                hidden.rollback()


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

    def limited_client(self, limit):
        limiter = SlidingWindowLimiter(limit=limit, window_seconds=60)
        app = FastAPI()
        app.add_middleware(GetRateLimitMiddleware, limiter=limiter)
        app.get("/ping")(lambda: {"ok": True})
        return TestClient(app), limiter

    def test_buckets_are_per_ip_and_keyed_by_a_salted_hash(self):
        client, limiter = self.limited_client(limit=2)
        first, second = {"X-Forwarded-For": "203.0.113.8"}, {"X-Forwarded-For": "198.51.100.4"}
        self.assertEqual([client.get("/ping", headers=first).status_code for _ in range(3)], [200, 200, 429])
        self.assertEqual([client.get("/ping", headers=second).status_code for _ in range(3)], [200, 200, 429])
        self.assertEqual(set(limiter._hits), {limiter_key("203.0.113.8"), limiter_key("198.51.100.4")})
        self.assertEqual(limiter_key("203.0.113.8"), limiter_key("203.0.113.8"))
        for key in limiter._hits:
            self.assertNotIn("203.0.113.8", key)
            self.assertNotIn("198.51.100.4", key)

    def test_raw_ip_is_not_in_the_429_response(self):
        client, _ = self.limited_client(limit=1)
        headers = {"X-Forwarded-For": "203.0.113.8"}
        client.get("/ping", headers=headers)
        blocked = client.get("/ping", headers=headers)
        self.assertEqual(blocked.status_code, 429)
        self.assertNotIn("203.0.113.8", blocked.text)
        self.assertNotIn("203.0.113.8", " ".join(f"{k}: {v}" for k, v in blocked.headers.items()))


if __name__ == "__main__":
    unittest.main()
