"""Getting Started (what_youll_need, how_to_begin): extraction prompt and parser, publishing, backfill, end to end."""
import json
import os
import unittest
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import text

from daily_publish_to_briefs import daily_publish_to_briefs
from db.models import Brief, RawIdea
from db.queries import canonicalize_url
from llm import translate
from llm.gemini import QuotaExhausted
from pipeline import extract, gates, publish
from tests.branch_db import RolledBackTestCase
from tests.test_gates import GOOD, SOURCE_TEXT, FakeEmbed, unit
from tests.test_pipeline_stages import FakeLLM, _reply
from tools import backfill_getting_started

NEED = GOOD["what_youll_need"]
BEGIN = GOOD["how_to_begin"]
PUBLISH_DAY = date(2099, 1, 5)

# --- step 1: prompt and parser ---

class PromptTests(unittest.TestCase):

    def test_forum_prompt_requests_both_fields_everywhere(self):
        prompt = translate.FORUM_SYSTEM_PROMPT
        self.assertIn(translate.GETTING_STARTED_RULES, prompt)
        self.assertIn('exactly 3 lines separated by "\\n", each line starting with "- "', prompt)
        self.assertIn('numbered "1. ", "2. ", "3. "', prompt)
        rescoped_schema = prompt[prompt.index('"rescoped_version": {'):prompt.index("} or null,")]
        self.assertIn('"what_youll_need": "- line', rescoped_schema)
        self.assertIn('"how_to_begin": "1. step', rescoped_schema)
        self.assertIn("learning_outcomes, what_youll_need, how_to_begin)", prompt)

    def test_backfill_prompt_uses_same_rules(self):
        prompt = translate.build_getting_started_prompt("Gym tracker", "Climbers lose track", ["React", "SQLite"], ["Log sends"])
        self.assertTrue(prompt.startswith(translate.GETTING_STARTED_SYSTEM_PROMPT))
        self.assertIn(translate.GETTING_STARTED_RULES, prompt)
        self.assertIn("Suggested Tech Stack: React, SQLite", prompt)
        self.assertIn("Suggested Features: Log sends", prompt)

class FormatTests(unittest.TestCase):

    def test_bullets(self):
        self.assertEqual(translate.format_what_youll_need(["Node.js", "* Git", "  "]), "- Node.js\n- Git")
        self.assertEqual(translate.format_what_youll_need("- A\n\n\u2022 B\n1. C"), "- A\n- B\n- C")
        self.assertEqual(translate.format_what_youll_need("1.5 GB of disk"), "- 1.5 GB of disk")
        self.assertIsNone(translate.format_what_youll_need(None))
        self.assertIsNone(translate.format_what_youll_need(" \n - "))

    def test_numbering(self):
        self.assertEqual(translate.format_how_to_begin(["Init", "2) Data", "- UI"]), "1. Init\n2. Data\n3. UI")
        self.assertEqual(translate.format_how_to_begin(BEGIN), BEGIN)
        self.assertIsNone(translate.format_how_to_begin([]))

class ParseTests(unittest.TestCase):

    def test_valid_reply_is_normalized(self):
        idea = translate.parse_forum_response(_reply(True, what_youll_need=["Node.js", "Git", "VS Code"], how_to_begin="Init\nData\nUI"))
        self.assertEqual((idea["what_youll_need"], idea["how_to_begin"]), ("- Node.js\n- Git\n- VS Code", "1. Init\n2. Data\n3. UI"))

    def test_valid_reply_without_fields_is_rejected(self):
        for overrides, missing in (({"what_youll_need": None}, "what_youll_need"), ({"how_to_begin": ""}, "how_to_begin"),
                                   ({"what_youll_need": [], "how_to_begin": None}, "what_youll_need, how_to_begin")):
            with self.assertRaises(ValueError) as caught:
                translate.parse_forum_response(_reply(True, **overrides))
            self.assertEqual(str(caught.exception), f"Missing getting started field(s): {missing}")

    def test_rescoped_reply_needs_fields_inside_rescoped_version(self):
        rescoped = {"title": "Smaller", "what_youll_need": ["A", "B"], "how_to_begin": ["X", "Y"]}
        idea = translate.parse_forum_response(_reply("needs_rescope", rescoped_version=rescoped, what_youll_need=None, how_to_begin=None))
        self.assertEqual((idea["rescoped_version"]["what_youll_need"], idea["rescoped_version"]["how_to_begin"]), ("- A\n- B", "1. X\n2. Y"))
        with self.assertRaisesRegex(ValueError, r"^Missing getting started field\(s\): rescoped_version\.how_to_begin$"):
            translate.parse_forum_response(_reply("needs_rescope", rescoped_version={"title": "Smaller", "what_youll_need": "A"}))
        with self.assertRaisesRegex(ValueError, "Missing rescoped_version"):
            translate.parse_forum_response(_reply("needs_rescope", rescoped_version=None))

    def test_rejected_reply_needs_no_fields(self):
        idea = translate.parse_forum_response(_reply(False, what_youll_need=None, how_to_begin=None))
        self.assertIs(idea["is_valid_idea"], False)

    def test_getting_started_reply(self):
        reply = json.dumps({"what_youll_need": ["Node.js", "Git", "VS Code"], "how_to_begin": "1. A\n2. B\n3. C"})
        self.assertEqual(translate.parse_getting_started_response(f"```json\n{reply}\n```"),
                         {"what_youll_need": "- Node.js\n- Git\n- VS Code", "how_to_begin": "1. A\n2. B\n3. C"})
        with self.assertRaisesRegex(ValueError, r"how_to_begin$"):
            translate.parse_getting_started_response(json.dumps({"what_youll_need": "- A"}))
        with self.assertRaisesRegex(ValueError, "Invalid JSON"):
            translate.parse_getting_started_response("[1, 2]")

# --- shared branch fixtures ---

class BranchCase(RolledBackTestCase):

    def setUp(self):
        super().setUp()
        self.offset = 0

    def make_row(self, **overrides):
        self.offset += 1
        url = f"https://news.ycombinator.com/item?id={uuid.uuid4().int % 10**9}"
        values = {
            "source": "hackernews", "source_url": url, "canonical_url": canonicalize_url(url), "raw_title": "Ask HN",
            "raw_text": SOURCE_TEXT, "fetched_at": datetime(2000, 1, 1) + timedelta(seconds=self.offset),
            "processed_at": datetime(2026, 9, 1), "passed_prefilter": True, "is_valid_idea": "true",
            "source_date": datetime(2026, 6, 1), "ready_to_publish": False, "extracted_title": GOOD["title"],
            "problem_summary": GOOD["problem_summary"], "target_user": GOOD["target_user"],
            "suggested_features": GOOD["suggested_features"], "learning_outcomes": GOOD["learning_outcomes"],
            "suggested_tech_stack": GOOD["suggested_tech_stack"], "difficulty_estimate": GOOD["difficulty_estimate"],
            "what_youll_need": NEED, "how_to_begin": BEGIN,
        }
        values.update(overrides)
        row = RawIdea(**values)
        self.db.add(row)
        self.db.commit()
        return row.id

    def row(self, row_id):
        return self.conn.execute(text("select * from raw_ideas where id = :id"), {"id": row_id}).mappings().one()

    def brief_for(self, raw_id):
        return self.conn.execute(text("select * from briefs where raw_idea_id = :id"), {"id": raw_id}).mappings().one_or_none()

# --- step 4: publishing ---

class RunPublishTests(BranchCase):

    def setUp(self):
        super().setUp()
        # Park the branch's real candidates inside this rolled-back transaction so only test rows are published.
        self.conn.execute(text("update raw_ideas set gate_status = 'failed' where gate_status = 'passed' and published_brief_id is null"))

    def test_copies_fields_and_skips_rows_without_them(self):
        good_id = self.make_row(gate_status="passed", gate_score=90, embedding=list(unit(1)))
        rescoped = {k: GOOD[k] for k in ("title", "problem_summary", "target_user", "suggested_features", "learning_outcomes",
                                         "suggested_tech_stack", "difficulty_estimate", "what_youll_need", "how_to_begin")}
        rescope_id = self.make_row(gate_status="passed", gate_score=80, embedding=list(unit(2)), is_valid_idea="needs_rescope",
                                   rescoped_version=rescoped, what_youll_need=None, how_to_begin=None)
        missing_id = self.make_row(gate_status="passed", gate_score=95, embedding=list(unit(3)), how_to_begin="  ")

        summary = publish.run_publish(self.db, FakeEmbed(error=AssertionError("no embedding expected")), today=PUBLISH_DAY)

        self.assertEqual((summary["published"], summary["skipped"], summary["buffer_before"]), (2, [missing_id], 2))
        for raw_id in (good_id, rescope_id):
            brief = self.brief_for(raw_id)
            self.assertEqual((brief["what_youll_need"], brief["how_to_begin"]), (NEED, BEGIN))
            self.assertEqual(self.row(raw_id)["published_brief_id"], brief["id"])
        self.assertIsNone(self.brief_for(missing_id))
        self.assertIsNone(self.row(missing_id)["published_brief_id"])
        error = self.conn.execute(text("select error from pipeline_runs where stage = 'publish' order by id desc limit 1")).scalar()
        self.assertIn("skipped 1 without getting started", error)

class DailyPublishTests(BranchCase):

    def setUp(self):
        super().setUp()
        self.conn.execute(text("update raw_ideas set ready_to_publish = false where ready_to_publish"))

    def test_copies_fields_and_skips_without_using_a_slot(self):
        missing_id = self.make_row(ready_to_publish=True, ready_to_publish_at=datetime(2000, 1, 1), what_youll_need=None)
        good_id = self.make_row(ready_to_publish=True, ready_to_publish_at=datetime(2000, 1, 2))
        later_id = self.make_row(ready_to_publish=True, ready_to_publish_at=datetime(2000, 1, 3))
        embedded = []

        with self.assertLogs(level="WARNING") as logs:
            promoted = daily_publish_to_briefs(limit=1, db=self.db, embed=lambda t: embedded.append(t) or list(unit(4)))

        self.assertEqual(promoted, 1)
        self.assertIn(f"skipping raw idea {missing_id}, empty what_youll_need", logs.output[0])
        brief = self.brief_for(good_id)
        self.assertEqual((brief["what_youll_need"], brief["how_to_begin"]), (NEED, BEGIN))
        self.assertEqual(len(embedded), 1)
        self.assertIsNone(self.brief_for(missing_id))
        self.assertIsNone(self.brief_for(later_id))
        self.assertEqual((self.row(missing_id)["ready_to_publish"], self.row(later_id)["ready_to_publish"]), (True, True))

# --- step 5: backfill ---

GENERATED = json.dumps({"what_youll_need": ["VS Code and a modern browser", "Node.js and npm", "Git"],
                        "how_to_begin": ["Initialize a Vite project", "Create the route store", "Build the route list page"]})
GENERATED_NEED = "- VS Code and a modern browser\n- Node.js and npm\n- Git"
GENERATED_BEGIN = "1. Initialize a Vite project\n2. Create the route store\n3. Build the route list page"

class BackfillTests(BranchCase):

    def setUp(self):
        super().setUp()
        self.short = Brief(title="Climbing gym tracker", difficulty="beginner", core_task="Climbers lose track of sends",
                           recommended_stack=["React"], suggested_features=["Log sends"], what_youll_need=None, how_to_begin="1. Start")
        self.complete = Brief(title="Complete brief", difficulty="beginner", core_task="c", what_youll_need=NEED, how_to_begin=BEGIN)
        self.db.add_all([self.short, self.complete])
        self.db.commit()
        self.raw_id = self.make_row(gate_status="passed", what_youll_need=None, how_to_begin=None)
        self.complete_raw_id = self.make_row(gate_status="passed")
        self.unpassed_id = self.make_row(gate_status="failed", what_youll_need=None)

    def run_backfill(self, llm, apply):
        lines = []
        summary = backfill_getting_started.backfill(self.db, llm, apply=apply, out=lines.append, interval=0)
        return summary, "\n".join(lines)

    def brief(self, brief_id):
        return self.conn.execute(text("select what_youll_need, how_to_begin from briefs where id = :id"), {"id": brief_id}).one()

    def test_targets(self):
        targets = {(t.kind, t.id) for t in backfill_getting_started.find_targets(self.db)}
        self.assertLessEqual({("brief", self.short.id), ("raw_idea", self.raw_id)}, targets)
        self.assertFalse({("brief", self.complete.id), ("raw_idea", self.complete_raw_id), ("raw_idea", self.unpassed_id)} & targets)
        self.assertFalse({kind for kind, _ in targets} - {"brief", "raw_idea"})

    def test_dry_run_prints_and_writes_nothing(self):
        llm = FakeLLM(GENERATED)
        summary, output = self.run_backfill(llm, apply=False)

        self.assertLessEqual({("brief", self.short.id), ("raw_idea", self.raw_id)}, set(summary["ids"]))
        self.assertEqual((summary["written"], summary["failed"], summary["quota"]), (0, 0, False))
        self.assertIn(f"=== brief {self.short.id}: Climbing gym tracker", output)
        self.assertIn(f"=== raw_idea {self.raw_id}: {GOOD['title']}", output)
        self.assertIn(f"What You'll Need:\n{GENERATED_NEED}\nHow to Begin:\n{GENERATED_BEGIN}", output)
        self.assertTrue(any("Title: Climbing gym tracker" in p and "Suggested Tech Stack: React" in p for p in llm.prompts))
        self.assertEqual(tuple(self.brief(self.short.id)), (None, "1. Start"))
        self.assertEqual((self.row(self.raw_id)["what_youll_need"], self.row(self.raw_id)["how_to_begin"]), (None, None))

    def test_apply_writes_and_is_idempotent(self):
        summary, _ = self.run_backfill(FakeLLM(GENERATED), apply=True)

        self.assertEqual(summary["written"], summary["generated"])
        self.assertEqual(tuple(self.brief(self.short.id)), (GENERATED_NEED, GENERATED_BEGIN))
        self.assertEqual((self.row(self.raw_id)["what_youll_need"], self.row(self.raw_id)["how_to_begin"]), (GENERATED_NEED, GENERATED_BEGIN))
        self.assertEqual(tuple(self.brief(self.complete.id)), (NEED, BEGIN))
        self.assertEqual(self.row(self.complete_raw_id)["what_youll_need"], NEED)
        self.assertIsNone(self.row(self.unpassed_id)["what_youll_need"])
        self.assertEqual(backfill_getting_started.find_targets(self.db), [])

    def test_bad_reply_and_quota(self):
        summary, output = self.run_backfill(FakeLLM(json.dumps({"what_youll_need": "- A", "how_to_begin": "1. B"})), apply=True)
        self.assertEqual((summary["generated"], summary["written"]), (0, 0))
        self.assertEqual(summary["failed"], summary["targets"])
        self.assertIn("FAILED ValueError: out_of_range: what_youll_need length 3 not in 30..3000", output)
        self.assertEqual(tuple(self.brief(self.short.id)), (None, "1. Start"))

        llm = FakeLLM(GENERATED, QuotaExhausted("generate: 429"))
        summary, output = self.run_backfill(llm, apply=True)
        self.assertEqual((summary["written"], summary["quota"], len(llm.prompts)), (1, True, 2))
        self.assertIn("quota exhausted; stopping", output)

# --- step 7: one simulated end-to-end run ---

@unittest.skipUnless(os.environ.get("SIMULATION_ALLOWED") == "1", "end-to-end simulation needs SIMULATION_ALLOWED=1")
class EndToEndTests(BranchCase):
    """Extraction -> gates -> publish on the test branch with fake Gemini clients; everything is rolled back."""

    def setUp(self):
        super().setUp()
        self.conn.execute(text("update raw_ideas set passed_prefilter = null "
                               "where passed_prefilter and processed_at is null and gate_status = 'pending'"))
        self.conn.execute(text("update raw_ideas set gate_status = 'failed' where gate_status = 'pending' "
                               "or (gate_status = 'passed' and published_brief_id is null)"))
        self.addCleanup(setattr, extract, "CALL_INTERVAL_SECONDS", extract.CALL_INTERVAL_SECONDS)
        extract.CALL_INTERVAL_SECONDS = 0

    def test_brief_published_with_getting_started(self):
        unprocessed = {"processed_at": None, "is_valid_idea": None, "extracted_title": None, "problem_summary": None,
                       "target_user": None, "suggested_features": None, "learning_outcomes": None, "suggested_tech_stack": None,
                       "difficulty_estimate": None, "what_youll_need": None, "how_to_begin": None}
        good_id = self.make_row(**unprocessed)
        no_fields_id = self.make_row(**unprocessed)
        blocked_id = self.make_row(how_to_begin=None)  # extracted earlier without Getting Started
        brief = {k: GOOD[k] for k in ("title", "problem_summary", "target_user", "suggested_features",
                                      "suggested_tech_stack", "learning_outcomes", "difficulty_estimate")}
        llm = FakeLLM(_reply(True, **brief, what_youll_need=["A code editor such as VS Code", "Python 3 and pip", "Git"],
                             how_to_begin=["Create a Flask project", "Define the routes and sends tables", "Build the route list page"]),
                      _reply(True, **brief, what_youll_need=None))

        extracted = extract.run_extraction(self.db, llm, max_items=10, budget_seconds=60)
        gated = gates.run_gates(self.db, FakeEmbed(default=unit(42)), max_items=10, budget_seconds=60)
        published = publish.run_publish(self.db, FakeEmbed(error=AssertionError("gate-passed rows carry embeddings")), today=PUBLISH_DAY)

        self.assertEqual((extracted["succeeded"], extracted["failed"]), (1, 1))
        self.assertIn("Missing getting started field(s): what_youll_need", self.row(no_fields_id)["last_error"])
        self.assertEqual((gated["passed"], gated["failed"]), (1, 1))
        self.assertEqual(self.row(blocked_id)["gate_failures"], [{"gate": "getting_started", "reason": "missing_field: how_to_begin"}])
        self.assertEqual(published["published"], 1)
        row = self.brief_for(good_id)
        self.assertEqual(published["brief_ids"], [row["id"]])
        self.assertEqual(row["what_youll_need"], "- A code editor such as VS Code\n- Python 3 and pip\n- Git")
        self.assertEqual(row["how_to_begin"], "1. Create a Flask project\n2. Define the routes and sends tables\n3. Build the route list page")
        self.assertIsNone(self.brief_for(no_fields_id))
        self.assertIsNone(self.brief_for(blocked_id))
        print(f"\nend-to-end: brief {row['id']} published with what_youll_need ({len(row['what_youll_need'])} chars) "
              f"and how_to_begin ({len(row['how_to_begin'])} chars)")

if __name__ == "__main__":
    unittest.main()
