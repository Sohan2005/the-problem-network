import os
import re
import unittest
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://invalid:invalid@127.0.0.1:1/none")

from categories import CATEGORIES, OTHER, SLUGS, category_scores, classify
from routes.briefs import CardEntry, count_categories, select_cards
from tests.test_hosting import card_row, fake_db_client

FRONTEND_CATEGORIES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                   "frontend", "lib", "categories.ts")


class ClassifyTests(unittest.TestCase):
    def test_real_postings_land_in_the_expected_category(self):
        cases = [
            ("Multi-Model AI Prompt Comparison Tool", "Compare responses from multiple AI models.", ["React"], "ai"),
            ("C++ Standard Header Inclusion Linter", "Code compiles on some compilers only.", ["Python"], "developer-tools"),
            ("Satellite Orbit Predictor and Visualizer", "Predict passes.", ["web development"], "data"),
            ("Multi-Timezone Reminder Web App", "Schedule reminders across time zones.", ["web development"], "productivity"),
            ("Ad-Blocking & Cookie Auto-Responder Browser Extension", "Cookie pop-ups and ads.", ["JavaScript"],
             "security-privacy"),
            ("Text-Only Android Web Browser", "Save data.", ["Android", "Kotlin"], "mobile"),
            ("Batch Video Frame Cropper", "Remove static watermarks.", ["FFmpeg"], "media-games"),
            ("Manual Bank Transaction & Monthly Budget Tracker", "Track spending.", ["web development"], "money-work"),
            ("Medication Tracker for Elderly Family Members", "Doses get missed.", ["web development"], "life-health"),
        ]
        for title, core_task, stack, expected in cases:
            self.assertEqual(classify(title, core_task, stack), expected, title)

    def test_no_keyword_is_other(self):
        self.assertEqual(classify("Untitled", "Something vague.", ["web development"]), OTHER)
        self.assertEqual(classify(None, None, None), OTHER)

    def test_title_outweighs_stack_and_stack_outweighs_core_task(self):
        scores = category_scores("Reminder", "", [])
        self.assertEqual(scores["productivity"], 3)
        self.assertEqual(category_scores("", "", ["Kotlin"])["mobile"], 2)
        self.assertEqual(category_scores("", "Uses Kotlin.", [])["mobile"], 1)
        self.assertEqual(classify("Game", "Reminders and notifications", []), "media-games")

    def test_web_stack_boilerplate_does_not_count(self):
        self.assertEqual(category_scores("", "", ["HTML/CSS", "OpenAI API"])["developer-tools"], 0)
        self.assertEqual(category_scores("CSS Component Library", "", [])["developer-tools"], 6)
        self.assertEqual(category_scores("", "A mock API for testing.", [])["developer-tools"], 3)

    def test_keywords_match_whole_words_in_any_case(self):
        self.assertEqual(category_scores("Maintain said email", "", [])["ai"], 0)
        self.assertEqual(category_scores("AI-driven", "", [])["ai"], 3)
        self.assertEqual(category_scores("c++ linter", "", [])["developer-tools"], 6)
        self.assertEqual(category_scores("Gaming", "", [])["media-games"], 3)

    def test_tie_goes_to_the_category_listed_first(self):
        scores = category_scores("Reminder Game", "", [])
        self.assertEqual((scores["productivity"], scores["media-games"]), (3, 3))
        self.assertEqual(classify("Reminder Game", "", []), "productivity")

    def test_odd_stack_values_are_tolerated(self):
        self.assertEqual(classify("Untitled", "", "Kotlin"), "mobile")
        self.assertEqual(classify("Untitled", "", {"lang": "Kotlin"}), OTHER)

    def test_slugs_are_unique_and_match_the_frontend(self):
        self.assertEqual(len(set(SLUGS)), len(SLUGS))
        self.assertEqual(SLUGS[-1], OTHER)
        with open(FRONTEND_CATEGORIES, encoding="utf-8") as f:
            frontend = re.findall(r'slug: "([^"]+)", label: "([^"]+)"', f.read())
        self.assertEqual(frontend, [(slug, label) for slug, label, _ in CATEGORIES] + [(OTHER, "Other")])


def entry(id, category, difficulty="beginner", importance=""):
    return CardEntry({"id": id}, difficulty, frozenset(), frozenset(), importance, category)


class CategoryFilterTests(unittest.TestCase):
    entries = [entry(1, "ai"), entry(2, "data", "advanced"), entry(3, "ai", "advanced", "high"), entry(4, OTHER)]

    def ids(self, cards):
        return [card["id"] for card in cards]

    def test_filters_by_slug_in_any_case(self):
        self.assertEqual(self.ids(select_cards(self.entries, category="ai")), [1, 3])
        self.assertEqual(self.ids(select_cards(self.entries, category="AI")), [1, 3])
        self.assertEqual(self.ids(select_cards(self.entries, category="other")), [4])
        self.assertEqual(self.ids(select_cards(self.entries)), [1, 2, 3, 4])
        self.assertEqual(select_cards(self.entries, category="nope"), [])

    def test_combines_with_other_filters_and_sort(self):
        self.assertEqual(self.ids(select_cards(self.entries, category="ai", difficulty="Advanced")), [3])
        self.assertEqual(self.ids(select_cards(self.entries, category="ai", importance="high")), [3])
        self.assertEqual(self.ids(select_cards(self.entries, category="ai", sort="difficulty_desc")), [3, 1])
        self.assertEqual(self.ids(select_cards(self.entries, category="ai", ids=frozenset({1, 2}))), [1])

    def test_counts_follow_the_other_filters_and_list_every_slug(self):
        counts = count_categories(self.entries)
        self.assertEqual(list(counts), list(SLUGS))
        self.assertEqual((counts["ai"], counts["data"], counts[OTHER], counts["mobile"]), (2, 1, 1, 0))
        advanced = count_categories(self.entries, difficulty="advanced")
        self.assertEqual((advanced["ai"], advanced["data"], advanced[OTHER]), (1, 1, 0))


class CategoryRouteTests(unittest.TestCase):
    rows = [card_row(1, title="AI Prompt Tester"), card_row(2, title="Reminder App"), card_row(3, title="LLM Chatbot"),
            card_row(4, title="Untitled", stack=["web development"]), card_row(5, title="Prompt Library", difficulty="advanced")]

    def get(self, client, path):
        response = client.get(path)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_category_filter_pages_and_counts_from_one_snapshot(self):
        client = fake_db_client()
        with mock.patch("routes.briefs.list_all_briefs", return_value=self.rows) as listed:
            everything = self.get(client, "/briefs/")
            first = self.get(client, "/briefs/?category=ai&limit=2")
            more = self.get(client, "/briefs/?category=ai&limit=2&offset=2")
            combined = self.get(client, "/briefs/?category=ai&difficulty=advanced")
            empty = self.get(client, "/briefs/?category=mobile")
        self.assertEqual(listed.call_count, 1)
        self.assertEqual([c["category"] for c in everything["items"]], ["ai", "productivity", "ai", OTHER, "ai"])
        self.assertEqual(([c["id"] for c in first["items"]], first["total"], first["has_more"]), ([1, 3], 3, True))
        self.assertEqual(([c["id"] for c in more["items"]], more["has_more"]), ([5], False))
        self.assertEqual([c["id"] for c in combined["items"]], [5])
        self.assertEqual((empty["items"], empty["total"]), ([], 0))
        self.assertEqual(everything["category_counts"], first["category_counts"])
        self.assertEqual((everything["category_counts"]["ai"], everything["category_counts"]["productivity"],
                          everything["category_counts"][OTHER], sum(everything["category_counts"].values())), (3, 1, 1, 5))
        self.assertEqual(combined["category_counts"]["ai"], 1)
        self.assertEqual(sum(combined["category_counts"].values()), 1)
