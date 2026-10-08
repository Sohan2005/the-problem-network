import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import numpy as np
from sqlalchemy import text

from db.models import Brief, RawIdea
from db.queries import canonicalize_url
from pipeline import gates
from tests.branch_db import RolledBackTestCase

NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)
DIM = 3072

GOOD = {
    "title": "Shared climbing gym route tracker",
    "problem_summary": "Climbers at small gyms lose track of which routes they have sent and cannot see route grades "
                       "or setter notes in one place.",
    "target_user": "Recreational climbers at small bouldering gyms",
    "suggested_features": ["Log sent routes with their grade", "Browse current routes by wall"],
    "learning_outcomes": ["CRUD web apps", "Relational data modelling"],
    "suggested_tech_stack": ["Python", "PostgreSQL"],
    "difficulty_estimate": "beginner",
    "what_youll_need": None,
    "how_to_begin": None,
}
SOURCE_TEXT = ("STORY: Ask HN: What do you wish existed?\n\nSTORY URL: \n\nMATCHING COMMENT: I wish there was a tool where "
               "climbers at my gym could track routes they have sent, see route grades and setter notes, because small "
               "gyms have nothing like this for their climbers.")

def fields(**overrides):
    return {**GOOD, **overrides}

def unit(i, j=None, weight=0.0):
    """One-hot vector e_i, optionally tilted towards e_j: cosine with e_i is 1/sqrt(1+weight^2)."""
    vec = np.zeros(DIM, dtype=np.float32)
    vec[i] = 1.0
    if j is not None:
        vec[j] = weight
    return vec

class FakeEmbed:
    def __init__(self, by_title=None, default=None, error=None):
        self.by_title = by_title or {}
        self.default = default
        self.error = error
        self.calls = []

    def embed(self, text_):
        self.calls.append(text_)
        if self.error:
            raise self.error
        for title, vector in self.by_title.items():
            if text_.startswith(title):
                return list(vector)
        return list(self.default if self.default is not None else unit(len(self.calls) + 100))

# --- pure gate tests ---

class TextHelperTests(unittest.TestCase):

    def test_overlap(self):
        self.assertEqual(gates.overlap("alpha bravo charlie delta", "alpha and delta"), 0.5)
        self.assertEqual(gates.overlap("", "anything"), 0.0)
        self.assertEqual(gates.salient_words("The users would need a tool for climbing"), {"climbing"})

    def test_own_text(self):
        self.assertEqual(gates.own_text("Show HN: parent", "STORY: x\n\nMATCHING COMMENT: my comment").strip(), "my comment")
        self.assertIn("Need a tool", gates.own_text("Need a tool", "QUESTION: q\n\nQUESTION BODY: body\n\nMETADATA: Score=1"))
        self.assertNotIn("Score=1", gates.own_text("t", "QUESTION BODY: body\n\nMETADATA: Score=1"))

class EligibilityGateTests(unittest.TestCase):

    def row(self, **overrides):
        values = {"processed_at": NOW, "is_valid_idea": "true", "gate_status": "pending", "published_brief_id": None}
        return SimpleNamespace(**{**values, **overrides})

    def test_valid_and_rescope_pass(self):
        self.assertEqual(gates.gate_eligibility(self.row()), (True, None, 0.0))
        self.assertTrue(gates.gate_eligibility(self.row(is_valid_idea="needs_rescope"))[0])

    def test_rejected_by_extraction(self):
        self.assertEqual(gates.gate_eligibility(self.row(is_valid_idea="false"))[1], "rejected_by_extraction")

    def test_not_eligible(self):
        for overrides in ({"processed_at": None}, {"gate_status": "passed"}, {"published_brief_id": 7}, {"is_valid_idea": None}):
            self.assertEqual(gates.gate_eligibility(self.row(**overrides))[1], "not_eligible", overrides)

class StructureGateTests(unittest.TestCase):

    def assert_pass(self, **overrides):
        passed, reason, _ = gates.gate_structure(fields(**overrides))
        self.assertTrue(passed, reason)

    def assert_fail(self, code, **overrides):
        passed, reason, _ = gates.gate_structure(fields(**overrides))
        self.assertFalse(passed)
        self.assertIn(code, reason)

    def test_good_fields_pass_with_full_completeness(self):
        self.assertEqual(gates.gate_structure(fields()), (True, None, 25.0))

    def test_missing_fields(self):
        for name in ("title", "problem_summary", "target_user"):
            self.assert_fail(f"missing_field: {name}", **{name: None})
            self.assert_fail(f"missing_field: {name}", **{name: "   "})
        self.assert_fail("missing_field: suggested_features", suggested_features=None)

    def test_text_length_boundaries(self):
        for name, (low, high) in (("title", gates.TITLE_LEN), ("problem_summary", gates.PROBLEM_LEN), ("target_user", gates.TARGET_LEN)):
            self.assert_pass(**{name: "x" * low})
            self.assert_pass(**{name: "x" * high})
            self.assert_fail(f"out_of_range: {name}", **{name: "x" * (low - 1)})
            self.assert_fail(f"out_of_range: {name}", **{name: "x" * (high + 1)})

    def test_list_size_boundaries(self):
        for name, (low, high) in (("suggested_features", gates.FEATURES_COUNT), ("learning_outcomes", gates.LEARNING_COUNT),
                                  ("suggested_tech_stack", gates.STACK_COUNT)):
            self.assert_pass(**{name: ["item"] * low})
            self.assert_pass(**{name: ["item"] * high})
            self.assert_fail(f"out_of_range: {name}", **{name: ["item"] * (high + 1)})
            if low:
                self.assert_fail(f"out_of_range: {name}", **{name: ["item"] * (low - 1)})
        self.assert_pass(suggested_tech_stack=None)
        self.assert_fail("bad_list_item: suggested_features", suggested_features=["ok", ""])
        self.assert_fail("bad_list_item: suggested_features", suggested_features=["ok", "x" * (gates.LIST_ITEM_MAX + 1)])

    def test_difficulty(self):
        for value in gates.DIFFICULTIES:
            self.assert_pass(difficulty_estimate=value)
        self.assert_fail("bad_difficulty", difficulty_estimate="expert")
        self.assert_fail("bad_difficulty", difficulty_estimate=None)

    def test_placeholders(self):
        self.assert_fail("placeholder: target_user", target_user="TBD by the team later")
        self.assert_fail("placeholder: suggested_features", suggested_features=["Lorem ipsum feature"])
        self.assert_fail("placeholder: what_youll_need", what_youll_need="N/A")
        self.assert_pass(title="Todo list sharing app")

    def test_optional_texts(self):
        self.assert_pass(what_youll_need="A laptop", how_to_begin="1. Start")
        self.assert_fail("out_of_range: how_to_begin", how_to_begin="x" * (gates.OPTIONAL_TEXT_MAX + 1))

    def test_all_problems_reported(self):
        passed, reason, score = gates.gate_structure(fields(title=None, difficulty_estimate="expert", learning_outcomes=[]))
        self.assertFalse(passed)
        self.assertEqual(len(reason.split("; ")), 3)
        self.assertLess(score, 25.0)

class RedFlagGateTests(unittest.TestCase):

    def test_clean_need_passes(self):
        self.assertEqual(gates.gate_red_flags("Ask HN", SOURCE_TEXT, "https://news.ycombinator.com/item?id=1"), (True, None, 0.0))

    def test_patterns(self):
        samples = {
            "i_built": "I built this over the weekend", "we_built": "we've built a platform", "we_launched": "We just launched today",
            "check_out_my": "check out our new app", "my_startup": "my startup does this", "hiring": "We're hiring engineers",
            "waitlist": "join our waitlist now", "promo_code": "use promo code SAVE10", "affiliate": "buy via https://x.example/?ref=abc",
        }
        self.assertEqual(set(samples), set(gates.RED_FLAG_PATTERNS))
        for name, sample in samples.items():
            passed, reason, _ = gates.gate_red_flags("t", f"QUESTION BODY: {sample}", "https://x.example/q/1")
            self.assertFalse(passed, name)
            self.assertIn(f"red_flag: {name}", reason)

    def test_show_and_launch_hn_titles(self):
        for title in ("Show HN: My new app", "Launch HN: Acme (YC W26)"):
            passed, reason, _ = gates.gate_red_flags(title, "POST TEXT: details", "https://news.ycombinator.com/item?id=2")
            self.assertFalse(passed)
            self.assertIn("show_or_launch_hn_title", reason)

    def test_parent_story_context_is_not_flagged(self):
        raw_text = "STORY: Show HN: I built a thing\n\nSTORY URL: https://x.example/?ref=hn\n\nMATCHING COMMENT: someone should build a gym tracker"
        self.assertTrue(gates.gate_red_flags("Show HN: I built a thing", raw_text, "https://news.ycombinator.com/item?id=3")[0])

    def test_calibrated_non_flags(self):
        for body in ("here is a comment i made months ago", "I created a spreadsheet for this", "make a wiki, show hn, iterate", "I don't want to sign up"):
            self.assertTrue(gates.gate_red_flags("t", f"POST TEXT: {body}", "https://x.example/1")[0], body)

    def test_domain_blocklist(self):
        with mock.patch.object(gates, "DOMAIN_BLOCKLIST", frozenset({"spam.example"})):
            passed, reason, _ = gates.gate_red_flags("t", "POST TEXT: fine", "https://www.spam.example/page")
        self.assertFalse(passed)
        self.assertIn("blocked_domain: spam.example", reason)

class GroundingGateTests(unittest.TestCase):

    def grounding(self, source="hackernews", raw_text=SOURCE_TEXT, brief=None):
        return gates.gate_grounding(brief or fields(), source, "Ask HN", raw_text)

    def test_hn_overlap_has_no_minimum(self):
        passed, reason, score = self.grounding(raw_text="completely unrelated words here")
        self.assertTrue(passed, reason)
        self.assertEqual(score, 0.0)

    def test_overlap_threshold_boundary(self):
        brief = {"title": " ".join(f"term{i:02d}" for i in range(20)), "problem_summary": ""}
        at = " ".join(f"term{i:02d}" for i in range(3))     # 3/20 = 0.15
        below = " ".join(f"term{i:02d}" for i in range(2))  # 2/20 = 0.10
        self.assertTrue(self.grounding("stackexchange_softwarerecs", raw_text=at, brief=brief)[0])
        passed, reason, _ = self.grounding("stackexchange_softwarerecs", raw_text=below, brief=brief)
        self.assertFalse(passed)
        self.assertIn("low_source_overlap: 0.10 < 0.15", reason)

    def test_overlap_score_part(self):
        self.assertEqual(self.grounding()[2], 25 * min(1.0, gates.overlap(gates.brief_text(fields()), f"Ask HN {SOURCE_TEXT}") / gates.OVERLAP_FULL_SCORE))

    def test_web_grounding_checked_against_raw_text_only(self):
        self.assertTrue(self.grounding("web_grounding")[0])
        passed, reason, _ = self.grounding("web_grounding", raw_text="nothing shared")
        self.assertFalse(passed)
        self.assertEqual(reason, "low_source_overlap: 0.00 < 0.20")
        self.assertTrue(self.grounding("ai_suggested", raw_text="nothing shared")[0])

    def test_html_to_text(self):
        self.assertEqual(gates.html_to_text("<script>x=1</script><p>Tom &amp; Jerry</p>").split(), ["Tom", "&", "Jerry"])

class DuplicateGateTests(unittest.TestCase):

    def test_threshold_boundary(self):
        self.assertEqual(gates.gate_duplicate(None), (True, None, 0.0))
        self.assertTrue(gates.gate_duplicate(("brief", 3, 0.8499))[0])
        passed, reason, _ = gates.gate_duplicate(("brief", 3, 0.85))
        self.assertFalse(passed)
        self.assertEqual(reason, "duplicate: brief 3 similarity 0.850")
        self.assertLessEqual(gates.DUPLICATE_THRESHOLD, 0.88)

    def test_pool_nearest_and_exclusions(self):
        pool = gates.VectorPool()
        pool.add("brief", 10, unit(0), owner_raw_idea_id=500)
        pool.add("raw", 20, unit(1))
        self.assertEqual(pool.nearest(unit(0))[:2], ("brief", 10))
        self.assertAlmostEqual(pool.nearest(unit(0, 1, 0.5))[2], 1 / np.sqrt(1.25), places=5)
        self.assertEqual(pool.nearest(unit(0), raw_idea_id=500)[:2], ("raw", 20))
        self.assertIsNone(gates.VectorPool().nearest(unit(0)))
        lonely = gates.VectorPool()
        lonely.add("raw", 20, unit(1))
        self.assertIsNone(lonely.nearest(unit(1), raw_idea_id=20))

class ScoreTests(unittest.TestCase):

    def test_extras(self):
        recent = datetime(2026, 10, 7)
        self.assertEqual(gates.score_extras(fields(), "high", recent, NOW) - gates.score_extras(fields(), "low", recent, NOW), 10.0)
        self.assertEqual(gates.score_extras(fields(), None, None, NOW) - gates.score_extras(fields(), None, recent, NOW), 7.5 - 15.0)
        self.assertEqual(gates.score_extras(fields(), None, datetime(2020, 1, 1), NOW), gates.score_extras(fields(), None, datetime(2021, 1, 1), NOW))

    def test_score_order(self):
        a = SimpleNamespace(id=2, source_date=datetime(2025, 1, 1))
        b = SimpleNamespace(id=1, source_date=datetime(2024, 1, 1))
        c = SimpleNamespace(id=0, source_date=None)
        d = SimpleNamespace(id=3, source_date=datetime(2020, 1, 1))
        ordered = sorted([(a, 50.0), (b, 50.0), (c, 50.0), (d, 60.0)], key=gates.score_order)
        self.assertEqual([row.id for row, _ in ordered], [3, 1, 2, 0])

class EffectiveFieldsTests(unittest.TestCase):

    def row(self, **overrides):
        values = {"is_valid_idea": "true", "rescoped_version": None, "extracted_title": "Extracted", "problem_summary": "p",
                  "target_user": "t", "suggested_features": [], "learning_outcomes": [], "suggested_tech_stack": [],
                  "difficulty_estimate": "beginner", "what_youll_need": "w", "how_to_begin": "h"}
        return SimpleNamespace(**{**values, **overrides})

    def test_valid_uses_extracted_columns(self):
        self.assertEqual(gates.effective_fields(self.row())["title"], "Extracted")

    def test_needs_rescope_uses_rescoped_version(self):
        effective = gates.effective_fields(self.row(is_valid_idea="needs_rescope", rescoped_version={"title": "Smaller"}))
        self.assertEqual(effective["title"], "Smaller")
        self.assertIsNone(effective["what_youll_need"])
        self.assertIsNone(gates.effective_fields(self.row(is_valid_idea="needs_rescope"))["title"])

# --- stage tests on the test branch ---

class GateStageTests(RolledBackTestCase):

    def setUp(self):
        super().setUp()
        # Park every real pending row inside this rolled-back transaction so only test rows are selected.
        self.conn.execute(text("update raw_ideas set gate_status = 'failed' where gate_status = 'pending'"))
        self.offset = 0

    def make_row(self, brief=None, **overrides):
        self.offset += 1
        url = overrides.pop("source_url", f"https://news.ycombinator.com/item?id={uuid.uuid4().int % 10**9}")
        brief = brief or {}
        values = {
            "source": "hackernews", "source_url": url, "canonical_url": canonicalize_url(url), "raw_title": "Ask HN",
            "raw_text": SOURCE_TEXT, "fetched_at": datetime(2000, 1, 1) + timedelta(seconds=self.offset),
            "processed_at": datetime(2026, 9, 1), "passed_prefilter": True, "is_valid_idea": "true",
            "source_date": datetime(2026, 6, 1), "confidence_flag": None, "ready_to_publish": False,
            "extracted_title": brief.get("title", GOOD["title"]), "problem_summary": brief.get("problem_summary", GOOD["problem_summary"]),
            "target_user": brief.get("target_user", GOOD["target_user"]),
            "suggested_features": brief.get("suggested_features", GOOD["suggested_features"]),
            "learning_outcomes": brief.get("learning_outcomes", GOOD["learning_outcomes"]),
            "suggested_tech_stack": brief.get("suggested_tech_stack", GOOD["suggested_tech_stack"]),
            "difficulty_estimate": brief.get("difficulty_estimate", GOOD["difficulty_estimate"]),
        }
        values.update(overrides)
        row = RawIdea(**values)
        self.db.add(row)
        self.db.commit()
        return row.id

    def row(self, row_id):
        return self.conn.execute(text("select * from raw_ideas where id = :id"), {"id": row_id}).mappings().one()

    def run_gates(self, embed=None, max_items=50, budget_seconds=60):
        return gates.run_gates(self.db, embed or FakeEmbed(), max_items=max_items, budget_seconds=budget_seconds)

    def test_outcomes_and_written_columns(self):
        stamp = datetime(2026, 1, 2, 3, 4, 5)
        good_id = self.make_row(confidence_flag="high")
        ready_id = self.make_row(brief={"title": "Bouldering wall setter notes board"}, ready_to_publish=True, ready_to_publish_at=stamp)
        bad_id = self.make_row(brief={"title": None, "difficulty_estimate": "expert"},
                               raw_title="Show HN: thing", raw_text="POST TEXT: We just launched our app")
        rejected_id = self.make_row(is_valid_idea="false", extracted_title=None)
        wg_url = "https://www.reddit.com/r/climbing/comments/xyz/gym_tracker"
        wg_ok_id = self.make_row(brief={"title": "Climbing gym route log for small gyms"}, source="web_grounding", source_url=wg_url,
                                 raw_text="Climbers at small gyms want to track routes, grades and setter notes.")
        wg_low_url = "https://www.quora.com/What-app-should-exist"
        wg_low_id = self.make_row(brief={"title": "Climbing gym route board with grades"}, source="web_grounding", source_url=wg_low_url,
                                  raw_text="Unrelated words only.")
        embed = FakeEmbed(by_title={GOOD["title"]: unit(0), "Bouldering": unit(1), "Climbing gym route log": unit(2)})
        before = {i: (self.row(i)["ready_to_publish"], self.row(i)["ready_to_publish_at"]) for i in (good_id, ready_id, bad_id, rejected_id, wg_ok_id, wg_low_id)}

        summary = self.run_gates(embed)

        self.assertEqual({k: summary[k] for k in ("status", "rejected_by_extraction", "examined", "passed", "failed", "duplicate", "deferred")},
                         {"status": "ok", "rejected_by_extraction": 1, "examined": 5, "passed": 3, "failed": 2, "duplicate": 0, "deferred": 0})
        self.assertEqual(summary["failure_reasons"], {"rejected_by_extraction": 1, "missing_field": 1, "bad_difficulty": 1,
                                                      "red_flag": 2, "low_source_overlap": 1})
        good = self.row(good_id)
        self.assertEqual((good["gate_status"], good["gate_failures"]), ("passed", []))
        self.assertTrue(0 < float(good["gate_score"]) <= 100)
        self.assertIsNotNone(good["gated_at"])
        self.assertIsNotNone(good["embedding"])
        bad = self.row(bad_id)
        self.assertEqual(bad["gate_status"], "failed")
        self.assertEqual([f["gate"] for f in bad["gate_failures"]], ["structure", "red_flags"])
        self.assertIn("red_flag: show_or_launch_hn_title", bad["gate_failures"][1]["reason"])
        self.assertIn("red_flag: we_launched", bad["gate_failures"][1]["reason"])
        self.assertIsNone(bad["embedding"])
        rejected = self.row(rejected_id)
        self.assertEqual((rejected["gate_status"], rejected["gate_failures"], rejected["gate_score"]),
                         ("failed", [{"gate": "eligibility", "reason": "rejected_by_extraction"}], None))
        self.assertEqual(self.row(wg_ok_id)["gate_status"], "passed")
        self.assertLess(float(self.row(wg_ok_id)["gate_score"]), float(good["gate_score"]) - 20)
        self.assertEqual(self.row(wg_low_id)["gate_failures"], [{"gate": "grounding", "reason": "low_source_overlap: 0.00 < 0.20"}])
        after = {i: (self.row(i)["ready_to_publish"], self.row(i)["ready_to_publish_at"]) for i in before}
        self.assertEqual(after, before)
        self.assertEqual(before[ready_id], (True, stamp))
        runs = self.conn.execute(text("select rows_in, rows_out, status, error from pipeline_runs where stage = 'gates' and started_at >= now()")).mappings().all()
        self.assertEqual([dict(r) for r in runs], [{"rows_in": 6, "rows_out": 3, "status": "ok", "error": None}])

    def test_duplicate_within_batch_keeps_higher_score(self):
        low_id = self.make_row(confidence_flag="low", brief={"title": "Gym route tracker B"})
        high_id = self.make_row(confidence_flag="high", brief={"title": "Gym route tracker A"})
        embed = FakeEmbed(by_title={"Gym route tracker A": unit(0), "Gym route tracker B": unit(0, 1, 0.1)})
        summary = self.run_gates(embed)
        self.assertEqual((summary["passed"], summary["duplicate"]), (1, 1))
        self.assertEqual(self.row(high_id)["gate_status"], "passed")
        low = self.row(low_id)
        self.assertEqual(low["gate_status"], "duplicate")
        self.assertIsNone(low["duplicate_of_brief_id"])
        self.assertRegex(low["gate_failures"][0]["reason"], rf"^duplicate: raw {high_id} similarity 0\.99\d$")
        self.assertGreater(float(self.row(high_id)["gate_score"]), float(low["gate_score"]))

    def test_duplicate_of_published_brief(self):
        brief = Brief(title="Existing brief", difficulty="beginner", core_task="c", embedding=list(unit(7)))
        self.db.add(brief)
        self.db.commit()
        row_id = self.make_row()
        summary = self.run_gates(FakeEmbed(default=unit(7, 8, 0.2)))
        self.assertEqual(summary["duplicate"], 1)
        row = self.row(row_id)
        self.assertEqual((row["gate_status"], row["duplicate_of_brief_id"]), ("duplicate", brief.id))
        self.assertIn(f"duplicate: brief {brief.id} similarity", row["gate_failures"][0]["reason"])

    def test_own_brief_is_not_a_duplicate(self):
        row_id = self.make_row()
        self.db.add(Brief(title="Own brief", difficulty="beginner", core_task="c", raw_idea_id=row_id, embedding=list(unit(9))))
        self.db.commit()
        self.assertEqual(self.run_gates(FakeEmbed(default=unit(9)))["passed"], 1)

    def test_needs_rescope_gates_rescoped_fields(self):
        rescoped = {k: GOOD[k] for k in ("title", "problem_summary", "target_user", "suggested_features", "learning_outcomes",
                                         "suggested_tech_stack", "difficulty_estimate")}
        good_id = self.make_row(is_valid_idea="needs_rescope", rescoped_version=rescoped, extracted_title=None, target_user=None)
        bad_id = self.make_row(is_valid_idea="needs_rescope", rescoped_version={**rescoped, "difficulty_estimate": "expert"},
                               brief={"title": "Another climbing gym route tracker"})
        self.run_gates(FakeEmbed())
        self.assertEqual(self.row(good_id)["gate_status"], "passed")
        bad = self.row(bad_id)
        self.assertEqual((bad["gate_status"], bad["gate_failures"]), ("failed", [{"gate": "structure", "reason": "bad_difficulty: 'expert'"}]))

    def test_stored_embedding_is_reused(self):
        row_id = self.make_row(embedding=list(unit(3)))
        embed = FakeEmbed()
        self.assertEqual(self.run_gates(embed)["passed"], 1)
        self.assertEqual(embed.calls, [])
        self.assertEqual(self.row(row_id)["gate_status"], "passed")

    def test_embedding_error_defers_row(self):
        row_id = self.make_row()
        summary = self.run_gates(FakeEmbed(error=RuntimeError("quota")))
        self.assertEqual((summary["deferred"], summary["passed"]), (1, 0))
        row = self.row(row_id)
        self.assertEqual((row["gate_status"], row["gated_at"], row["embedding"]), ("pending", None, None))

    def test_idempotent(self):
        self.make_row()
        self.make_row(brief={"title": "Bouldering wall setter notes board"})
        embed = FakeEmbed()
        first = self.run_gates(embed)
        second = self.run_gates(embed)
        self.assertEqual((first["passed"], second["examined"], second["rejected_by_extraction"]), (2, 0, 0))
        self.assertEqual(len(embed.calls), 2)

    def test_budget_exhausted(self):
        row_id = self.make_row()
        rejected_id = self.make_row(is_valid_idea="false")
        summary = self.run_gates(budget_seconds=0)
        self.assertTrue(summary["stopped_by_budget"])
        self.assertEqual((summary["examined"], summary["rejected_by_extraction"]), (0, 0))
        self.assertEqual((self.row(row_id)["gate_status"], self.row(rejected_id)["gate_status"]), ("pending", "pending"))

    def test_max_items_oldest_first(self):
        ids = [self.make_row(brief={"title": f"Climbing gym route tracker {n}"}) for n in range(3)]
        summary = self.run_gates(max_items=2)
        self.assertEqual(summary["examined"], 2)
        self.assertEqual([self.row(i)["gate_status"] for i in ids], ["passed", "passed", "pending"])

class PublishedCalibrationTests(RolledBackTestCase):
    """All 49 published raw ideas must pass every gate (each excluded from its own duplicate comparison)."""

    def test_published_briefs_pass_all_gates(self):
        rows = self.db.query(RawIdea).filter(RawIdea.published_brief_id.isnot(None)).order_by(RawIdea.id).all()
        if not rows:
            self.skipTest("no published raw ideas on the branch")
        briefs = {b.raw_idea_id: b for b in self.db.query(Brief).filter(Brief.raw_idea_id.in_([r.id for r in rows]))}
        for row in rows:
            row.embedding = briefs[row.id].embedding  # the brief embedding is the same title+problem text
        self.db.commit()
        embed = FakeEmbed(error=AssertionError("embedding API must not be called"))

        summary = gates.gate_rows(self.db, rows, embed, deadline=float("inf"))

        outcomes = self.conn.execute(text("select id, gate_status, gate_failures from raw_ideas where published_brief_id is not null order by id")).all()
        duplicates = [(r.id, r.gate_failures) for r in outcomes if r.gate_status == "duplicate"]
        if duplicates:
            print("\npublished duplicates of each other:", duplicates)
        self.assertEqual([(r.id, r.gate_failures) for r in outcomes if r.gate_status != "passed"], [])
        self.assertEqual((len(rows), summary["passed"]), (49, 49))

if __name__ == "__main__":
    unittest.main()
