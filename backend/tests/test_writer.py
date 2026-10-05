import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from db.queries import canonicalize_url, insert_raw_ideas
from tests.branch_db import RolledBackTestCase

SOURCE = "unittest"

def _item(url=None, **overrides):
    item = {"source": SOURCE, "source_url": url or f"https://unittest.example/{uuid.uuid4().hex}", "raw_title": "Title", "raw_text": "Text"}
    item.update(overrides)
    return item

class CanonicalizeUrlTests(unittest.TestCase):

    def test_examples(self):
        cases = {
            "  HTTPS://News.YCombinator.com/item?id=123  ": "https://news.ycombinator.com/item?id=123",
            "http://Example.COM/Path/To/?a=1&utm_source=x&B=2#frag": "http://example.com/Path/To?a=1&B=2",
            "https://example.com///": "https://example.com",
            "https://example.com/?&&": "https://example.com",
            "https://example.com?utm_x&UTM_Medium=2&keep=1": "https://example.com?keep=1",
            "\thttps://x.com/a/\t": "\thttps://x.com/a/\t",
        }
        for url, expected in cases.items():
            self.assertEqual(canonicalize_url(url), expected, url)

class InsertRawIdeasTests(RolledBackTestCase):

    def count(self, where="source = :source", **params):
        return self.conn.execute(text(f"select count(*) from raw_ideas where {where}"), {"source": SOURCE, **params}).scalar()

    def existing_url(self):
        url = self.conn.execute(text("select source_url from raw_ideas where source_url not like '%#%' order by id limit 1")).scalar()
        if url is None:
            self.skipTest("no existing raw_ideas rows on the branch")
        return url

    def test_valid_insert(self):
        aware = datetime.now(timezone(timedelta(hours=-6))) - timedelta(days=2)
        item = _item(raw_title="Tom &amp; Jerry " + "x" * 600, raw_text="y" * 9000, author="a" * 150,
                     source_date=aware, matched_keyword="kw", confidence_flag="high")
        result = insert_raw_ideas(self.db, [item])
        self.assertEqual(result, {"inserted": 1, "skipped_duplicate": 0, "rejected": []})
        row = self.conn.execute(text("select * from raw_ideas where source_url = :u"), {"u": item["source_url"]}).mappings().one()
        self.assertTrue(row["raw_title"].startswith("Tom & Jerry "))
        self.assertEqual(len(row["raw_title"]), 500)
        self.assertEqual(len(row["raw_text"]), 8000)
        self.assertEqual(len(row["author"]), 100)
        self.assertEqual(row["canonical_url"], canonicalize_url(item["source_url"]))
        self.assertEqual(row["source_date"], aware.astimezone(timezone.utc).replace(tzinfo=None))
        self.assertEqual((row["matched_keyword"], row["confidence_flag"]), ("kw", "high"))
        self.assertIsNotNone(row["fetched_at"])
        self.assertEqual((row["gate_status"], row["extraction_attempts"], row["ready_to_publish"]), ("pending", 0, False))
        self.assertIsNone(row["embedding"])

    def test_duplicate_url(self):
        result = insert_raw_ideas(self.db, [_item(self.existing_url())])
        self.assertEqual((result["inserted"], result["skipped_duplicate"]), (0, 1))
        self.assertEqual(self.count(), 0)

    def test_utm_variant_of_existing_url(self):
        url = self.existing_url()
        variant = url + ("&" if "?" in url else "?") + "utm_source=newsletter&utm_medium=email"
        self.assertEqual(canonicalize_url(variant), canonicalize_url(url))
        result = insert_raw_ideas(self.db, [_item(variant)])
        self.assertEqual((result["inserted"], result["skipped_duplicate"]), (0, 1))
        self.assertEqual(self.count(), 0)

    def test_duplicate_within_batch(self):
        base = f"https://unittest.example/{uuid.uuid4().hex}/page"
        items = [_item(base), _item(base.replace("unittest.example", "UNITTEST.example") + "/?utm_campaign=x#top"), _item()]
        result = insert_raw_ideas(self.db, items)
        self.assertEqual((result["inserted"], result["skipped_duplicate"], result["rejected"]), (2, 1, []))
        self.assertEqual(self.count(), 2)

    def test_future_date_rejected(self):
        item = _item(source_date=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1))
        result = insert_raw_ideas(self.db, [item])
        self.assertEqual(result["rejected"], [(item["source_url"], "source_date in future")])
        self.assertEqual(result["inserted"], 0)

    def test_too_old_date_rejected(self):
        item = _item(source_date=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3 * 365 + 1))
        result = insert_raw_ideas(self.db, [item])
        self.assertEqual(result["rejected"], [(item["source_url"], "source_date too old")])

    def test_empty_title_rejected(self):
        items = [_item(raw_title=""), _item(raw_title="   "), _item(raw_title=None), _item(raw_text=""), _item(source_url=""), "junk"]
        result = insert_raw_ideas(self.db, items)
        self.assertEqual([reason for _, reason in result["rejected"]],
                         ["missing raw_title"] * 3 + ["missing raw_text", "missing source_url", "not a dict"])
        self.assertEqual((result["inserted"], result["skipped_duplicate"]), (0, 0))
        self.assertEqual(self.count(), 0)

    def test_mixed_batch_counts(self):
        items = [_item(), _item(self.existing_url()), _item(raw_title=""), _item(source_date="2025-01-01")]
        result = insert_raw_ideas(self.db, items)
        self.assertEqual((result["inserted"], result["skipped_duplicate"]), (1, 1))
        self.assertEqual([reason for _, reason in result["rejected"]], ["missing raw_title", "invalid source_date"])

if __name__ == "__main__":
    unittest.main()
