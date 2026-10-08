import json
import time
import unittest
import uuid
from datetime import datetime, timedelta
from unittest import mock

from sqlalchemy import text

from db.models import RawIdea
from db.queries import canonicalize_url
from pipeline import extract, prefilter
from tests.branch_db import RolledBackTestCase

LONG_TEXT = "STORY: Tools\n\nMATCHING COMMENT: " + " ".join(["word"] * 30)
OLDEST = datetime(2000, 1, 1)  # sorts before every real branch row, so oldest-first picks test rows

def _reply(is_valid=True, **overrides):
    reply = {"is_valid_idea": is_valid, "rejection_reason": None, "original_ask": None, "rescoped_version": None,
             "rescope_reason": None, "title": "Habit tracker for dorms", "problem_summary": "P", "target_user": "Students",
             "suggested_features": ["f"], "difficulty_estimate": "beginner", "suggested_tech_stack": ["Python"],
             "learning_outcomes": ["l"], "what_youll_need": ["An account", "A laptop"], "how_to_begin": "1. Start",
             "source_url": None, "source_platform": None}
    reply.update(overrides)
    return json.dumps(reply)

class FakeLLM:
    """generate() returns (or raises) the queued replies in order, repeating the last one."""

    def __init__(self, *replies, delay=0):
        self.replies = list(replies)
        self.prompts = []
        self.delay = delay

    def generate(self, prompt):
        self.prompts.append(prompt)
        if self.delay:
            time.sleep(self.delay)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

class PrefilterRuleTests(unittest.TestCase):

    def test_long_text_passes(self):
        self.assertEqual(prefilter.evaluate(LONG_TEXT), (True, None))

    def test_too_short(self):
        self.assertEqual(prefilter.evaluate("MATCHING COMMENT: just a few words here"),
                         (False, "Too short (5 words < 20 minimum)"))
        self.assertEqual(prefilter.evaluate(""), (False, "Too short (0 words < 20 minimum)"))
        self.assertEqual(prefilter.evaluate(None), (False, "Too short (0 words < 20 minimum)"))

    def test_trigger_phrase_exception(self):
        rescued = "MATCHING COMMENT: someone should build a shared calendar for climbing gyms with route grades"
        self.assertEqual(prefilter.evaluate(rescued), (True, None))
        thin = "MATCHING COMMENT: someone should build this please"
        self.assertEqual(prefilter.evaluate(thin), (
            False, "Too short (5 words), insufficient context beyond trigger phrase (2 words < 8 minimum)"))

    def test_intent_rule_is_kept_but_disabled(self):
        no_signals = " ".join(["lorem"] * 25)
        self.assertEqual(prefilter.rule_no_intent(no_signals), prefilter.REASON_NO_INTENT)
        self.assertNotIn(prefilter.rule_no_intent, prefilter.RULES)
        self.assertEqual(prefilter.evaluate(no_signals), (True, None))

class StageTestCase(RolledBackTestCase):

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(extract, "CALL_INTERVAL_SECONDS", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.offset = 0

    def make_row(self, **overrides):
        self.offset += 1
        url = f"https://unittest.example/{uuid.uuid4().hex}"
        values = {"source": "unittest", "source_url": url, "canonical_url": canonicalize_url(url), "raw_title": "T",
                  "raw_text": LONG_TEXT, "fetched_at": OLDEST + timedelta(seconds=self.offset)}
        values.update(overrides)
        row = RawIdea(**values)
        self.db.add(row)
        self.db.commit()
        return row.id

    def row(self, row_id):
        return self.conn.execute(text("select * from raw_ideas where id = :id"), {"id": row_id}).mappings().one()

    def runs(self, stage):
        return self.conn.execute(text("select rows_in, rows_out, status, error from pipeline_runs where stage = :s and started_at >= now() order by id"),
                                 {"s": stage}).mappings().all()

class PrefilterStageTests(StageTestCase):

    def test_prefilter_marks_rows_oldest_first(self):
        long_id = self.make_row()
        short_id = self.make_row(raw_text="MATCHING COMMENT: too short")
        processed_id = self.make_row(processed_at=datetime(2026, 1, 1))
        rejected_id = self.make_row(passed_prefilter=False, prefilter_reject_reason="manual")
        newest_id = self.make_row(fetched_at=datetime(2001, 1, 1))

        summary = prefilter.run_prefilter(self.db, max_items=2, budget_seconds=60)

        self.assertEqual({k: summary[k] for k in ("status", "examined", "passed", "rejected")}, {"status": "ok", "examined": 2, "passed": 1, "rejected": 1})
        self.assertEqual((self.row(long_id)["passed_prefilter"], self.row(long_id)["prefilter_reject_reason"]), (True, None))
        self.assertEqual((self.row(short_id)["passed_prefilter"], self.row(short_id)["prefilter_reject_reason"]), (False, "Too short (2 words < 20 minimum)"))
        self.assertIsNone(self.row(processed_id)["passed_prefilter"])
        self.assertEqual(self.row(rejected_id)["prefilter_reject_reason"], "manual")
        self.assertIsNone(self.row(newest_id)["passed_prefilter"])
        self.assertEqual([dict(r) for r in self.runs("prefilter")], [{"rows_in": 2, "rows_out": 1, "status": "ok", "error": None}])

    def test_prefilter_budget_exhausted(self):
        row_id = self.make_row()
        summary = prefilter.run_prefilter(self.db, max_items=1, budget_seconds=0)
        self.assertEqual((summary["examined"], summary["stopped_by_budget"]), (0, True))
        self.assertIsNone(self.row(row_id)["passed_prefilter"])

class ExtractionStageTests(StageTestCase):

    def make_eligible(self, **overrides):
        return self.make_row(passed_prefilter=True, **overrides)

    def test_success(self):
        valid_id = self.make_eligible()
        rescope_id = self.make_eligible()
        rescoped = {"title": "Smaller", "problem_summary": "P"}
        llm = FakeLLM(_reply(True), _reply("needs_rescope", rescoped_version=rescoped, original_ask="Big"))

        summary = extract.run_extraction(self.db, llm, max_items=10, budget_seconds=60)

        self.assertEqual({k: summary[k] for k in ("status", "attempted", "succeeded", "failed", "valid", "needs_rescope", "rejected")},
                         {"status": "ok", "attempted": 2, "succeeded": 2, "failed": 0, "valid": 1, "needs_rescope": 1, "rejected": 0})
        self.assertEqual(len(llm.prompts), 2)
        self.assertTrue(llm.prompts[0].startswith(extract.build_forum_prompt("", "", "")[:200]))
        self.assertIn("MATCHING COMMENT:", llm.prompts[0])
        valid = self.row(valid_id)
        self.assertEqual((valid["is_valid_idea"], valid["extracted_title"], valid["extraction_attempts"]), ("true", "Habit tracker for dorms", 1))
        self.assertEqual(valid["what_youll_need"], "An account\nA laptop")
        self.assertIsNotNone(valid["processed_at"])
        self.assertIsNone(valid["last_error"])
        self.assertEqual((valid["gate_status"], valid["ready_to_publish"], valid["published_at"], valid["published_brief_id"]), ("pending", False, None, None))
        rescope = self.row(rescope_id)
        self.assertEqual((rescope["is_valid_idea"], rescope["rescoped_version"], rescope["original_ask"]), ("needs_rescope", rescoped, "Big"))
        self.assertEqual([dict(r) for r in self.runs("extract")], [{"rows_in": 2, "rows_out": 2, "status": "ok", "error": None}])

    def test_rejected_idea_stored_as_false(self):
        row_id = self.make_eligible()
        summary = extract.run_extraction(self.db, FakeLLM(_reply(False, rejection_reason="Show HN", title=None)), max_items=10, budget_seconds=60)
        self.assertEqual(summary["rejected"], 1)
        self.assertEqual((self.row(row_id)["is_valid_idea"], self.row(row_id)["rejection_reason"]), ("false", "Show HN"))

    def test_malformed_json(self):
        row_id = self.make_eligible()
        summary = extract.run_extraction(self.db, FakeLLM("not json at all"), max_items=10, budget_seconds=60)
        self.assertEqual((summary["attempted"], summary["succeeded"], summary["failed"], summary["gave_up"]), (1, 0, 1, 0))
        row = self.row(row_id)
        self.assertEqual((row["extraction_attempts"], row["processed_at"], row["is_valid_idea"]), (1, None, None))
        self.assertEqual(row["last_error"], "ValueError: Invalid JSON response from Gemini")
        self.assertEqual([dict(r) for r in self.runs("extract")],
                         [{"rows_in": 1, "rows_out": 0, "status": "ok", "error": "1 item(s) failed; last: ValueError: Invalid JSON response from Gemini"}])

    def test_exception_is_recorded_and_next_item_runs(self):
        failing_id = self.make_eligible()
        next_id = self.make_eligible()
        llm = FakeLLM(RuntimeError("quota exceeded https://user:pw@api.example/v1?key=SECRET123 " + "x" * 600), _reply(True))
        summary = extract.run_extraction(self.db, llm, max_items=10, budget_seconds=60)
        self.assertEqual((summary["succeeded"], summary["failed"]), (1, 1))
        error = self.row(failing_id)["last_error"]
        self.assertTrue(error.startswith("RuntimeError: quota exceeded"))
        self.assertLessEqual(len(error), 500)
        self.assertNotIn("SECRET123", error)
        self.assertNotIn("user:pw", error)
        self.assertIsNotNone(self.row(next_id)["processed_at"])

    def test_third_failure_stops_retries(self):
        row_id = self.make_eligible(extraction_attempts=2)
        llm = FakeLLM(RuntimeError("boom"))
        summary = extract.run_extraction(self.db, llm, max_items=10, budget_seconds=60)
        self.assertEqual((summary["failed"], summary["gave_up"]), (1, 1))
        self.assertEqual(self.row(row_id)["extraction_attempts"], 3)

        again = extract.run_extraction(self.db, llm, max_items=10, budget_seconds=60)
        self.assertEqual((again["attempted"], again["exhausted"]), (0, 1))
        self.assertEqual(len(llm.prompts), 1)
        self.assertEqual(self.row(row_id)["extraction_attempts"], 3)

    def test_attempt_counted_before_call(self):
        row_id = self.make_eligible()
        seen = {}
        class Inspecting:
            def generate(inner, prompt):
                seen["attempts"] = self.conn.execute(text("select extraction_attempts from raw_ideas where id = :id"), {"id": row_id}).scalar()
                raise KeyboardInterrupt  # simulates the process dying mid-call
        with self.assertRaises(KeyboardInterrupt):
            extract.run_extraction(self.db, Inspecting(), max_items=1, budget_seconds=60)
        self.assertEqual(seen["attempts"], 1)

    def test_budget_exhausted(self):
        row_id = self.make_eligible()
        llm = FakeLLM(_reply(True))
        summary = extract.run_extraction(self.db, llm, max_items=10, budget_seconds=0)
        self.assertEqual((summary["attempted"], summary["stopped_by_budget"]), (0, True))
        self.assertEqual(llm.prompts, [])
        self.assertEqual(self.row(row_id)["extraction_attempts"], 0)

    def test_budget_runs_out_mid_run(self):
        first_id = self.make_eligible()
        second_id = self.make_eligible()
        summary = extract.run_extraction(self.db, FakeLLM(_reply(True), delay=3), max_items=10, budget_seconds=2)
        self.assertEqual((summary["attempted"], summary["succeeded"], summary["stopped_by_budget"]), (1, 1, True))
        self.assertIsNotNone(self.row(first_id)["processed_at"])
        self.assertEqual(self.row(second_id)["extraction_attempts"], 0)

    def test_max_items(self):
        ids = [self.make_eligible() for _ in range(3)]
        summary = extract.run_extraction(self.db, FakeLLM(_reply(True)), max_items=2, budget_seconds=60)
        self.assertEqual(summary["attempted"], 2)
        self.assertEqual([self.row(i)["extraction_attempts"] for i in ids], [1, 1, 0])

    def test_idempotent(self):
        self.make_eligible()
        self.make_eligible()
        llm = FakeLLM(_reply(True))
        first = extract.run_extraction(self.db, llm, max_items=10, budget_seconds=60)
        second = extract.run_extraction(self.db, llm, max_items=10, budget_seconds=60)
        self.assertEqual((first["succeeded"], second["attempted"]), (2, 0))
        self.assertEqual(len(llm.prompts), 2)

    def test_only_eligible_rows_selected(self):
        excluded = [
            self.make_row(passed_prefilter=None),
            self.make_row(passed_prefilter=False),
            self.make_eligible(processed_at=datetime(2026, 1, 1)),
            self.make_eligible(gate_status="failed"),
            self.make_eligible(extraction_attempts=3),
        ]
        summary = extract.run_extraction(self.db, FakeLLM(_reply(True)), max_items=10, budget_seconds=60)
        self.assertEqual((summary["attempted"], summary["exhausted"]), (0, 1))
        self.assertEqual([self.row(i)["extraction_attempts"] for i in excluded], [0, 0, 0, 0, 3])

if __name__ == "__main__":
    unittest.main()
