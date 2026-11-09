import io
import json
import os
import unittest
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://invalid:invalid@127.0.0.1:1/none")

from db.models import Brief, PipelineRun, RawIdea
from db.queries import canonicalize_url
from llm.gemini import QuotaExhausted
from pipeline import importance, orchestrator
from pipeline.importance import (MAX_ATTEMPTS, build_prompt, importance_level, parse_rating, rate, run_importance,
                                 unrated_rows)
from routes.briefs import CardEntry, select_cards
from tests.branch_db import RolledBackTestCase
from tests.test_hosting import card_row, detail_row, fake_db_client
from tools import backfill_importance


def rating(severity, frequency, reach, reason="Because."):
    return json.dumps({"severity": severity, "frequency": frequency, "reach": reach, "reason": reason})


class FakeLLM:
    """Returns the given responses in order; an Exception instance is raised instead of returned."""

    model_name = "fake-model"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ImportanceLevelTests(unittest.TestCase):
    def test_levels_at_the_boundaries(self):
        cases = {
            (2, 2, 2): "high", (2, 1, 1): "high", (2, 2, 0): "high", (2, 0, 2): "high",
            (2, 1, 0): "medium", (2, 0, 0): "medium",
            (1, 2, 2): "medium", (1, 1, 1): "medium", (1, 0, 2): "medium",
            (1, 1, 0): "everyday", (1, 0, 0): "everyday",
            (0, 2, 2): "everyday", (0, 0, 0): "everyday",
        }
        for (severity, frequency, reach), expected in cases.items():
            self.assertEqual(importance_level(severity, frequency, reach), expected, (severity, frequency, reach))

    def test_ai_suggested_is_capped_at_medium(self):
        self.assertEqual(importance_level(2, 2, 2, ai_suggested=True), "medium")
        self.assertEqual(importance_level(1, 1, 1, ai_suggested=True), "medium")
        self.assertEqual(importance_level(0, 2, 2, ai_suggested=True), "everyday")

    def test_rate_caps_ai_sources(self):
        def row(source):
            return SimpleNamespace(title="T", target_user="Nurses", problem_summary="P", core_task="C", source=source)
        self.assertEqual(rate(row("hackernews"), FakeLLM(rating(2, 2, 2)))[0], "high")
        for source in ("ai_suggested", "web_grounding"):
            self.assertEqual(rate(row(source), FakeLLM(rating(2, 2, 2)))[0], "medium", source)


class ParseRatingTests(unittest.TestCase):
    def test_valid_and_fenced_json(self):
        expected = {"severity": 2, "frequency": 1, "reach": 0, "reason": "Because."}
        self.assertEqual(parse_rating(rating(2, 1, 0)), expected)
        self.assertEqual(parse_rating(f"```json\n{rating(2, 1, 0)}\n```"), expected)

    def test_reason_is_clipped_and_optional(self):
        self.assertEqual(len(parse_rating(rating(1, 1, 1, "x" * 500))["reason"]), importance.REASON_MAX)
        self.assertEqual(parse_rating(json.dumps({"severity": 1, "frequency": 1, "reach": 1}))["reason"], "")

    def test_invalid_ratings_raise(self):
        bad = [
            "not json", "[1, 2, 3]", json.dumps({"severity": 1, "frequency": 1}),
            rating(3, 1, 1), rating(-1, 1, 1), rating("2", 1, 1), rating(1.5, 1, 1), rating(True, 1, 1),
            rating(1, None, 1),
        ]
        for text in bad:
            with self.assertRaises(ValueError, msg=text):
                parse_rating(text)

    def test_prompt_falls_back_to_core_task_and_unknown_user(self):
        prompt = build_prompt("Title", None, None, "The core task")
        self.assertIn("The core task", prompt)
        self.assertIn("unknown", prompt)


class SelectCardsImportanceTests(unittest.TestCase):
    def entries(self):
        def entry(id, level):
            return CardEntry({"id": id}, "beginner", frozenset(), frozenset(), level)
        return [entry(1, "high"), entry(2, "medium"), entry(3, ""), entry(4, "everyday"), entry(5, "high")]

    def test_filters_any_case_and_skips_unrated(self):
        ids = lambda cards: [card["id"] for card in cards]
        self.assertEqual(ids(select_cards(self.entries(), importance="high")), [1, 5])
        self.assertEqual(ids(select_cards(self.entries(), importance="Medium")), [2])
        self.assertEqual(ids(select_cards(self.entries(), importance="EVERYDAY")), [4])
        self.assertEqual(ids(select_cards(self.entries())), [1, 2, 3, 4, 5])
        self.assertEqual(select_cards(self.entries(), importance="critical"), [])


class ImportanceRouteTests(unittest.TestCase):
    def test_list_filter_combines_with_difficulty_and_returns_the_rating(self):
        rows = [card_row(1, importance="high"), card_row(2, importance="medium"), card_row(3),
                card_row(4, importance="high", difficulty="advanced")]
        client = fake_db_client()
        with mock.patch("routes.briefs.list_all_briefs", return_value=rows) as listed:
            high = client.get("/briefs/?importance=high").json()
            both = client.get("/briefs/?importance=High&difficulty=advanced").json()
            unfiltered = client.get("/briefs/").json()
        self.assertEqual(listed.call_count, 1)
        self.assertEqual(([c["id"] for c in high["items"]], high["total"]), ([1, 4], 2))
        self.assertEqual([c["id"] for c in both["items"]], [4])
        self.assertEqual([c["importance"] for c in unfiltered["items"]], ["high", "medium", None, "high"])

    def test_detail_returns_the_rating(self):
        client = fake_db_client()
        with mock.patch("routes.briefs.get_brief_by_id", return_value=detail_row(importance="medium")):
            self.assertEqual(client.get("/briefs/7").json()["importance"], "medium")


class ImportanceBranchTests(RolledBackTestCase):
    """run_importance, the daily cap and the backfill against briefs on the test branch (newer than any real brief)."""

    def setUp(self):
        super().setUp()
        self.started = datetime.now(timezone.utc)
        self.interval = mock.patch.object(importance, "CALL_INTERVAL_SECONDS", 0)
        self.interval.start()
        self.real = self.brief("hackernews", datetime(2099, 1, 3))
        self.ai = self.brief("ai_suggested", datetime(2099, 1, 2))
        self.other = self.brief("stackexchange_softwarerecs", datetime(2099, 1, 1))
        self.db.commit()

    def tearDown(self):
        self.interval.stop()
        super().tearDown()

    def brief(self, source, created_at):
        url = f"https://news.ycombinator.com/item?id={uuid.uuid4().int % 10**9}"
        raw = RawIdea(source=source, source_url=url, canonical_url=canonicalize_url(url), raw_title="Ask HN",
                      raw_text="text", problem_summary=f"Problem from {source}", embedding=[0.5] * 3072)
        self.db.add(raw)
        self.db.flush()
        row = Brief(title=f"Brief {source}", difficulty="beginner", core_task="Core task", target_user="Nurses",
                    raw_idea_id=raw.id, created_at=created_at, embedding=[0.5] * 3072)
        self.db.add(row)
        self.db.flush()
        return row.id

    def stored(self, brief_id):
        self.db.expire_all()
        row = self.db.get(Brief, brief_id)
        return row.importance, row.importance_detail

    def last_run(self):
        return (self.db.query(PipelineRun).filter(PipelineRun.stage == importance.STAGE,
                                                  PipelineRun.started_at >= self.started)
                .order_by(PipelineRun.id.desc()).first())

    def test_rates_newest_first_and_stores_the_detail(self):
        llm = FakeLLM(rating(2, 2, 1), rating(2, 2, 2), rating(0, 1, 0))
        summary = run_importance(self.db, llm, 3, 60)
        self.assertEqual((summary["status"], summary["rated"], summary["levels"]),
                         ("ok", 3, {"high": 1, "medium": 1, "everyday": 1}))
        self.assertIn("Problem from hackernews", llm.prompts[0])
        level, detail = self.stored(self.real)
        self.assertEqual(level, "high")
        self.assertEqual({k: detail[k] for k in ("severity", "frequency", "reach", "ai_suggested", "model", "attempts")},
                         {"severity": 2, "frequency": 2, "reach": 1, "ai_suggested": False, "model": "fake-model", "attempts": 1})
        self.assertEqual(self.stored(self.ai)[0], "medium")
        self.assertTrue(self.stored(self.ai)[1]["ai_suggested"])
        self.assertEqual(self.stored(self.other)[0], "everyday")
        run = self.last_run()
        self.assertEqual((run.rows_in, run.rows_out, run.status, run.error), (3, 3, "ok", None))
        self.assertNotIn(self.real, [row.id for row in unrated_rows(self.db, 3)])

    def test_failures_count_attempts_and_stop_after_max_attempts(self):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            summary = run_importance(self.db, FakeLLM("not json"), 1, 60)
            self.assertEqual((summary["status"], summary["failed"]), ("ok", 1))
            level, detail = self.stored(self.real)
            self.assertIsNone(level)
            self.assertEqual(detail["attempts"], attempt)
            self.assertIn("last_error", detail)
        self.assertEqual(self.last_run().error.split(";")[0], "1 item(s) failed")
        llm = FakeLLM(rating(1, 1, 1))
        run_importance(self.db, llm, 1, 60)
        self.assertIn("Brief ai_suggested", llm.prompts[0])
        self.assertIsNone(self.stored(self.real)[0])

    def test_quota_stops_without_counting_an_attempt(self):
        llm = FakeLLM(rating(1, 1, 1), QuotaExhausted("429"), rating(1, 1, 1))
        summary = run_importance(self.db, llm, 3, 60)
        self.assertEqual((summary["status"], summary["quota"], summary["attempted"], summary["rated"]),
                         ("warn", True, 1, 1))
        self.assertEqual(len(llm.prompts), 2)
        self.assertEqual(self.stored(self.ai), (None, None))
        run = self.last_run()
        self.assertEqual((run.rows_in, run.status, run.error), (1, "warn", importance.QUOTA_NOTE))

    def test_no_budget_rates_nothing(self):
        llm = FakeLLM()
        summary = run_importance(self.db, llm, 3, 0)
        self.assertEqual((summary["stopped_by_budget"], summary["attempted"], llm.prompts), (True, 0, []))

    def test_daily_cap_limits_and_skips(self):
        used = orchestrator.importance_calls_today(self.db, datetime.now(timezone.utc))
        now = datetime.now(timezone.utc)
        self.db.add(PipelineRun(stage=importance.STAGE, started_at=now, finished_at=now,
                                rows_in=orchestrator.IMPORTANCE_DAILY_CAP - used - 2, rows_out=0, status="ok"))
        self.db.commit()
        with mock.patch.object(importance, "run_importance", return_value={"status": "ok"}) as run:
            orchestrator.rate_importance(self.db, FakeLLM(), 5, 60)
        self.assertEqual(run.call_args.args[2], 2)
        self.db.add(PipelineRun(stage=importance.STAGE, started_at=now, finished_at=now, rows_in=2, rows_out=2, status="ok"))
        self.db.commit()
        with mock.patch.object(importance, "run_importance") as run:
            summary = orchestrator.rate_importance(self.db, FakeLLM(), 5, 60)
        self.assertEqual(summary["status"], "skipped")
        run.assert_not_called()

    def test_backfill_dry_run_writes_nothing_and_apply_writes(self):
        out = []
        summary = backfill_importance.backfill(self.db, FakeLLM(rating(2, 2, 2), rating(2, 2, 2)), limit=2,
                                               out=out.append, interval=0)
        self.assertEqual((summary["rated"], summary["written"], dict(summary["levels"])), (2, 0, {"high": 1, "medium": 1}))
        self.assertEqual(self.stored(self.real), (None, None))
        summary = backfill_importance.backfill(self.db, FakeLLM(rating(2, 2, 2), "bad"), apply=True, limit=2,
                                               out=out.append, interval=0)
        self.assertEqual((summary["written"], summary["failed"]), (1, 1))
        self.assertEqual(self.stored(self.real)[0], "high")
        self.assertEqual(self.stored(self.ai)[1]["attempts"], 1)


class BackfillGuardTests(unittest.TestCase):
    def test_refuses_to_apply_on_production_without_the_flag(self):
        fake_session = mock.MagicMock()
        fake_session.execute.return_value.scalar.return_value = False
        with mock.patch("db.database.SessionLocal", return_value=fake_session), \
                mock.patch.object(backfill_importance, "backfill") as backfill, redirect_stdout(io.StringIO()) as printed:
            code = backfill_importance.main(["--apply"])
        self.assertEqual(code, 3)
        backfill.assert_not_called()
        self.assertIn("PRODUCTION", printed.getvalue())
