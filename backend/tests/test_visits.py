import os
import unittest
from datetime import date
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://invalid:invalid@127.0.0.1:1/none")

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from db.queries import VISIT_INCREMENT_SQL, get_visit_counts, record_visit
from routes import briefs as briefs_routes
from routes import visits as visits_routes
from routes.briefs import get_db
from rate_limit import SlidingWindowLimiter
from tests.branch_db import RolledBackTestCase
from tests.test_hosting import CACHE_CONTROL, build_app

CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/131.0.0.0 Safari/537.36")
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"
SAFARI = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/18.1 Mobile/15E148 Safari/604.1")
TODAY = date(2026, 11, 7)


def visit_client(limit=visits_routes.VISIT_LIMIT):
    briefs_routes.snapshot_cache.clear()
    app = build_app()
    session = mock.Mock()

    def fake_db():
        yield session

    app.dependency_overrides[get_db] = fake_db
    limiter = SlidingWindowLimiter(limit=limit, window_seconds=visits_routes.VISIT_WINDOW_SECONDS)
    return TestClient(app), session, mock.patch.object(visits_routes, "visit_limiter", limiter)


class BotFilterTests(unittest.TestCase):
    def test_browsers_are_counted(self):
        for agent in (CHROME, FIREFOX, SAFARI):
            self.assertFalse(visits_routes.is_bot_or_prefetch({"user-agent": agent}), agent)

    def test_bots_tools_and_missing_agents_are_ignored(self):
        for agent in ("", "   ", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
                      "Mozilla/5.0 (compatible; bingbot/2.0)", "curl/8.5.0", "python-requests/2.32",
                      "Mozilla/5.0 HeadlessChrome/131.0.0.0", "facebookexternalhit/1.1", "Slackbot-LinkExpanding 1.0",
                      "Mozilla/5.0 (Linux) Chrome-Lighthouse"):
            self.assertTrue(visits_routes.is_bot_or_prefetch({"user-agent": agent}), agent)
        self.assertTrue(visits_routes.is_bot_or_prefetch({}))

    def test_prefetch_and_prerender_requests_are_ignored(self):
        for name, value in (("purpose", "prefetch"), ("sec-purpose", "prefetch;prerender"),
                            ("sec-purpose", "prefetch"), ("x-moz", "prefetch"), ("x-purpose", "preview")):
            self.assertTrue(visits_routes.is_bot_or_prefetch({"user-agent": CHROME, name: value}), (name, value))


class VisitRouteTests(unittest.TestCase):
    def test_a_browser_visit_is_one_increment_for_today(self):
        client, session, limiter = visit_client()
        with limiter, mock.patch.object(visits_routes, "utc_today", return_value=TODAY), \
                mock.patch.object(visits_routes, "record_visit") as recorded:
            response = client.post("/visits", headers={"User-Agent": CHROME})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        recorded.assert_called_once_with(session, TODAY)

    def test_bots_and_prefetches_get_204_without_an_increment(self):
        client, _, limiter = visit_client()
        with limiter, mock.patch.object(visits_routes, "record_visit") as recorded:
            for headers in ({"User-Agent": "Googlebot/2.1"}, {"User-Agent": ""},
                            {"User-Agent": CHROME, "Sec-Purpose": "prefetch"}):
                self.assertEqual(client.post("/visits", headers=headers).status_code, 204)
        recorded.assert_not_called()

    def test_rate_limit_per_caller(self):
        client, _, limiter = visit_client(limit=3)
        with limiter, mock.patch.object(visits_routes, "record_visit") as recorded:
            first = {"User-Agent": CHROME, "X-Forwarded-For": "203.0.113.8"}
            self.assertEqual([client.post("/visits", headers=first).status_code for _ in range(4)], [204, 204, 204, 429])
            other = {"User-Agent": CHROME, "X-Forwarded-For": "203.0.113.9"}
            self.assertEqual(client.post("/visits", headers=other).status_code, 204)
        self.assertEqual(recorded.call_count, 4)

    def test_limiter_never_keys_on_the_raw_ip(self):
        key = visits_routes.limiter_key("203.0.113.8")
        self.assertNotIn("203.0.113.8", key)
        self.assertEqual(key, visits_routes.limiter_key("203.0.113.8"))
        self.assertNotEqual(key, visits_routes.limiter_key("203.0.113.9"))

    def test_database_error_is_503_and_rolled_back(self):
        client, session, limiter = visit_client()
        failure = OperationalError("INSERT", {}, Exception("down"))
        with limiter, mock.patch.object(visits_routes, "record_visit", side_effect=failure):
            self.assertEqual(client.post("/visits", headers={"User-Agent": CHROME}).status_code, 503)
        session.rollback.assert_called_once()

    def test_count_is_cached(self):
        client, _, _ = visit_client()
        counts = {"total": 12, "today": 3}
        with mock.patch.object(visits_routes, "get_visit_counts", return_value=counts) as read:
            responses = [client.get("/visits/count") for _ in range(3)]
        self.assertEqual([r.json() for r in responses], [counts] * 3)
        self.assertEqual(responses[0].headers.get("cache-control"), CACHE_CONTROL)
        self.assertEqual(read.call_count, 1)

    def test_cors_allows_post_from_configured_origin(self):
        client = TestClient(build_app(ALLOWED_ORIGINS="https://briefs.example"))
        preflight = client.options("/visits", headers={"Origin": "https://briefs.example",
                                                       "Access-Control-Request-Method": "POST"})
        self.assertEqual(preflight.status_code, 200)
        self.assertIn("POST", preflight.headers.get("access-control-allow-methods", ""))


class IncrementSqlTests(unittest.TestCase):
    def test_increment_is_one_atomic_upsert(self):
        self.assertIn("ON CONFLICT (day) DO UPDATE SET visits = site_visits.visits + 1", VISIT_INCREMENT_SQL)
        self.assertNotIn("SELECT", VISIT_INCREMENT_SQL.upper())


class VisitBranchTests(RolledBackTestCase):
    def test_increments_accumulate_per_day_and_in_total(self):
        before = get_visit_counts(self.db, TODAY)
        for _ in range(3):
            record_visit(self.db, TODAY)
        record_visit(self.db, date(2026, 11, 6))
        after = get_visit_counts(self.db, TODAY)
        self.assertEqual(after["today"] - before["today"], 3)
        self.assertEqual(after["total"] - before["total"], 4)


if __name__ == "__main__":
    unittest.main()
