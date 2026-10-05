import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from sqlalchemy import text

from pipeline import ingest
from tests.branch_db import RolledBackTestCase

def _adapter(source, fetch):
    return SimpleNamespace(SOURCE=source, DEFAULT_MAX_ITEMS=100, fetch_candidates=mock.Mock(side_effect=fetch))

def _items(n):
    return [{"source": "unittest", "source_url": f"https://unittest.example/{uuid.uuid4().hex}", "raw_title": "T", "raw_text": "B"} for _ in range(n)]

class SafeErrorTests(unittest.TestCase):

    def test_redacts_credentials_and_truncates(self):
        exc = RuntimeError('could not connect to server at "db.internal.example" postgresql://user:pw@db.internal.example/app '
                           "https://api.example/q?key=abc123&page=2 password=hunter2 " + "x" * 1000)
        message = ingest.safe_error(exc)
        self.assertTrue(message.startswith("RuntimeError: "))
        self.assertLessEqual(len(message), ingest.ERROR_MAX)
        for leaked in ("user:pw", "abc123", "hunter2", "db.internal.example"):
            self.assertNotIn(leaked, message)

class RunIngestionTests(RolledBackTestCase):

    def runs(self):
        return self.conn.execute(text(
            "select stage, rows_in, rows_out, status, error, started_at, finished_at from pipeline_runs "
            "where stage like 'ingest:unittest_%' order by id")).mappings().all()

    def test_failing_adapter_does_not_stop_others(self):
        bad = _adapter("unittest_bad", RuntimeError("boom key=SECRET123"))
        good = _adapter("unittest_good", lambda **kwargs: _items(2))
        with mock.patch.object(ingest, "ADAPTERS", [bad, good]):
            summary = ingest.run_ingestion(self.db, total_budget_seconds=100)

        self.assertEqual(summary["unittest_bad"]["status"], "error")
        self.assertEqual(summary["unittest_good"], {"status": "ok", "fetched": 2, "inserted": 2, "skipped_duplicate": 0, "rejected": 0, "error": None})
        for adapter in (bad, good):
            adapter.fetch_candidates.assert_called_once_with(budget_seconds=50, max_items=100)

        runs = self.runs()
        self.assertEqual([r["stage"] for r in runs], ["ingest:unittest_bad", "ingest:unittest_good"])
        self.assertEqual((runs[0]["status"], runs[0]["rows_in"], runs[0]["rows_out"]), ("error", 0, 0))
        self.assertIn("RuntimeError: boom", runs[0]["error"])
        self.assertNotIn("SECRET123", runs[0]["error"])
        self.assertEqual((runs[1]["status"], runs[1]["rows_in"], runs[1]["rows_out"], runs[1]["error"]), ("ok", 2, 2, None))
        for run in runs:
            self.assertLessEqual(run["started_at"], run["finished_at"])

    def test_writer_failure_is_logged(self):
        good = _adapter("unittest_writer", lambda **kwargs: _items(1))
        with mock.patch.object(ingest, "ADAPTERS", [good]), \
                mock.patch.object(ingest, "insert_raw_ideas", side_effect=ValueError("db down")):
            summary = ingest.run_ingestion(self.db, total_budget_seconds=10)
        self.assertEqual(summary["unittest_writer"]["status"], "error")
        runs = self.runs()
        self.assertEqual((runs[0]["status"], runs[0]["rows_in"], runs[0]["rows_out"]), ("error", 1, 0))
        self.assertEqual(runs[0]["error"], "ValueError: db down")

if __name__ == "__main__":
    unittest.main()
