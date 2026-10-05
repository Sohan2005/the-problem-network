import time
import unittest
from datetime import datetime, timezone
from unittest import mock

import requests

from ingestion import hn_ingest, stackexchange_ingest

def _response(payload=None, status_code=200, json_error=None):
    response = mock.Mock(status_code=status_code)
    response.raise_for_status.return_value = None
    if json_error:
        response.json.side_effect = json_error
    else:
        response.json.return_value = payload
    return response

def _clock(*values):
    """Fake time.monotonic: returns values in order, then repeats the last."""
    values = list(values)
    return lambda: values.pop(0) if len(values) > 1 else values[0]

def _utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)

HN_TS = 1700000000

def _hn_hit(object_id, **overrides):
    hit = {"objectID": str(object_id), "story_title": f"Title {object_id}", "story_text": "Body", "story_url": "",
           "author": "someone", "created_at_i": HN_TS}
    hit.update(overrides)
    return hit

class HackerNewsAdapterTests(unittest.TestCase):

    def fetch(self, side_effect, **kwargs):
        kwargs.setdefault("budget_seconds", 60)
        kwargs.setdefault("max_items", 1000)
        with mock.patch.object(hn_ingest.requests, "get", side_effect=side_effect) as get:
            return hn_ingest.fetch_candidates(**kwargs), get

    def test_keywords_unique(self):
        self.assertEqual(len(hn_ingest.KEYWORDS), len(set(hn_ingest.KEYWORDS)))
        self.assertEqual(hn_ingest.KEYWORDS.count("someone should build"), 1)

    def test_normal_response(self):
        hits = [_hn_hit(1), _hn_hit(2, story_text=""), _hn_hit(3, story_title=""), _hn_hit(1)]
        items, get = self.fetch(lambda *a, **k: _response({"hits": hits}))
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["source"], "hackernews")
        self.assertEqual(item["source_url"], "https://news.ycombinator.com/item?id=1")
        self.assertEqual(item["raw_title"], "Title 1")
        self.assertIn("POST TEXT: Body", item["raw_text"])
        self.assertEqual(item["matched_keyword"], hn_ingest.KEYWORDS[0])
        self.assertEqual(get.call_count, len(hn_ingest.KEYWORDS))
        for call in get.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 15)
            self.assertEqual(call.kwargs["params"]["tags"], "ask_hn")
            self.assertEqual(call.kwargs["params"]["tagFilters"], "-show_hn")

    def test_utc_dates(self):
        items, _ = self.fetch(lambda *a, **k: _response({"hits": [_hn_hit(1)]}))
        self.assertEqual(items[0]["source_date"], _utc(HN_TS))
        self.assertEqual(items[0]["source_date"], datetime(2023, 11, 14, 22, 13, 20))
        self.assertIsNone(items[0]["source_date"].tzinfo)

    def test_timeout_continues_with_next_keyword(self):
        calls = {"n": 0}
        def get(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.Timeout()
            return _response({"hits": [_hn_hit(calls["n"])]})
        items, mocked = self.fetch(get)
        self.assertEqual(mocked.call_count, len(hn_ingest.KEYWORDS))
        self.assertEqual(len(items), len(hn_ingest.KEYWORDS) - 1)

    def test_all_requests_time_out(self):
        items, get = self.fetch(requests.Timeout())
        self.assertEqual(items, [])
        self.assertEqual(get.call_count, len(hn_ingest.KEYWORDS))

    def test_budget_exhausted_returns_partial(self):
        counter = iter(range(1, 100))
        with mock.patch.object(hn_ingest.time, "monotonic", _clock(0, 0, 0, 1000)):
            items, get = self.fetch(lambda *a, **k: _response({"hits": [_hn_hit(next(counter))]}), budget_seconds=10)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(len(items), 2)

    def test_zero_budget_makes_no_requests(self):
        items, get = self.fetch(lambda *a, **k: _response({"hits": [_hn_hit(1)]}), budget_seconds=0)
        self.assertEqual(items, [])
        get.assert_not_called()

    def test_max_items(self):
        items, get = self.fetch(lambda *a, **k: _response({"hits": [_hn_hit(i) for i in range(10)]}), max_items=3)
        self.assertEqual(len(items), 3)
        self.assertEqual(get.call_count, 1)

    def test_malformed_json(self):
        items, _ = self.fetch(lambda *a, **k: _response(json_error=ValueError("not json")))
        self.assertEqual(items, [])
        items, _ = self.fetch(lambda *a, **k: _response(["not", "a", "dict"]))
        self.assertEqual(items, [])
        items, _ = self.fetch(lambda *a, **k: _response({"hits": ["junk", None, {"objectID": None}]}))
        self.assertEqual(items, [])

    def test_empty_response(self):
        items, _ = self.fetch(lambda *a, **k: _response({"hits": []}))
        self.assertEqual(items, [])
        items, _ = self.fetch(lambda *a, **k: _response({}))
        self.assertEqual(items, [])

    def test_http_error_is_skipped(self):
        response = _response({"hits": [_hn_hit(1)]})
        response.raise_for_status.side_effect = requests.HTTPError("503")
        items, _ = self.fetch(lambda *a, **k: response)
        self.assertEqual(items, [])

    def test_since_narrows_window(self):
        since = datetime(2026, 1, 1)
        _, get = self.fetch(lambda *a, **k: _response({"hits": []}), since=since)
        expected = int(since.replace(tzinfo=timezone.utc).timestamp())
        self.assertEqual(get.call_args.kwargs["params"]["numericFilters"], f"created_at_i>{expected}")

SE_TS = int(time.time()) - 60 * 86400

def _question(question_id, **overrides):
    question = {"question_id": question_id, "title": f"Question {question_id}", "body": "<p>Body</p>", "creation_date": SE_TS,
                "view_count": 150, "score": 1, "answer_count": 0, "owner": {"display_name": "asker"}}
    question.update(overrides)
    return question

class StackExchangeAdapterTests(unittest.TestCase):

    def fetch(self, side_effect, **kwargs):
        kwargs.setdefault("budget_seconds", 60)
        kwargs.setdefault("max_items", 1000)
        with mock.patch.object(stackexchange_ingest.requests, "get", side_effect=side_effect) as get, \
                mock.patch.dict("os.environ", {"STACKEXCHANGE_API_KEY": "test-key"}):
            return stackexchange_ingest.fetch_candidates(**kwargs), get

    @staticmethod
    def pages(*pages, answers=None):
        """Fake API: question pages in order (then empty), answers keyed by question id."""
        def get(url, params=None, timeout=None):
            if url.endswith("/answers"):
                question_id = int(url.rsplit("/", 2)[-2])
                return (answers or {}).get(question_id, _response({"items": []}))
            page = params["page"]
            return _response({"items": pages[page - 1] if page <= len(pages) else []})
        return get

    def test_normal_response(self):
        questions = [
            _question(1, title="A &amp; B &quot;tool&quot;"),
            _question(2, view_count=5),
            _question(3, accepted_answer_id=99),
            _question(4, creation_date=int(time.time()) - 86400),
            _question(5, creation_date=int(time.time()) - 4 * 365 * 86400),
            _question(6, answer_count=1),
            _question(7, answer_count=1),
        ]
        answers = {6: _response({"items": [{"score": 10}]}), 7: _response({"items": [{"score": 2}]})}
        items, get = self.fetch(self.pages(questions, answers=answers))
        self.assertEqual([i["source_url"].rsplit("/", 1)[-1] for i in items], ["1", "2", "7"])
        first = items[0]
        self.assertEqual(first["raw_title"], 'A & B "tool"')
        self.assertTrue(first["raw_text"].startswith('QUESTION: A & B "tool"'))
        self.assertEqual(first["source"], "stackexchange_softwarerecs")
        self.assertEqual(first["author"], "asker")
        self.assertEqual(first["matched_keyword"], "softwarerecs_question")
        self.assertEqual(first["confidence_flag"], "high")
        self.assertEqual(items[1]["confidence_flag"], "low")
        for call in get.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 15)
            self.assertEqual(call.kwargs["params"]["key"], "test-key")

    def test_utc_dates(self):
        items, _ = self.fetch(self.pages([_question(1)]))
        self.assertEqual(items[0]["source_date"], _utc(SE_TS))
        self.assertIsNone(items[0]["source_date"].tzinfo)

    def test_page_limit(self):
        counter = iter(range(1, 10000))
        def get(url, params=None, timeout=None):
            return _response({"items": [_question(next(counter))]})
        items, mocked = self.fetch(get)
        self.assertEqual(mocked.call_count, stackexchange_ingest.MAX_PAGES)
        self.assertEqual(len(items), stackexchange_ingest.MAX_PAGES)

    def test_timeout_on_questions_returns_collected(self):
        def get(url, params=None, timeout=None):
            if params["page"] == 1:
                return _response({"items": [_question(1)]})
            raise requests.Timeout()
        items, mocked = self.fetch(get)
        self.assertEqual(len(items), 1)
        self.assertEqual(mocked.call_count, 2)

    def test_timeout_on_answers_skips_question(self):
        pages = self.pages([_question(1, answer_count=1), _question(2)])
        def get(url, params=None, timeout=None):
            if url.endswith("/answers"):
                raise requests.Timeout()
            return pages(url, params, timeout)
        items, _ = self.fetch(get)
        self.assertEqual([i["source_url"].rsplit("/", 1)[-1] for i in items], ["2"])

    def test_budget_exhausted_returns_partial(self):
        with mock.patch.object(stackexchange_ingest.time, "monotonic", _clock(0, 0, 1000)):
            items, get = self.fetch(self.pages([_question(1), _question(2, answer_count=1)], [_question(3)]), budget_seconds=10)
        self.assertEqual([i["source_url"].rsplit("/", 1)[-1] for i in items], ["1"])
        self.assertEqual(get.call_count, 1)

    def test_zero_budget_makes_no_requests(self):
        items, get = self.fetch(self.pages([_question(1)]), budget_seconds=0)
        self.assertEqual(items, [])
        get.assert_not_called()

    def test_max_items(self):
        items, _ = self.fetch(self.pages([_question(i) for i in range(1, 11)]), max_items=4)
        self.assertEqual(len(items), 4)

    def test_malformed_json(self):
        items, get = self.fetch(lambda *a, **k: _response(json_error=ValueError("not json")))
        self.assertEqual(items, [])
        self.assertEqual(get.call_count, 1)
        items, _ = self.fetch(lambda *a, **k: _response({"items": ["junk", {"question_id": 1}, {"title": "x"}]}))
        self.assertEqual(items, [])

    def test_empty_response(self):
        items, get = self.fetch(lambda *a, **k: _response({"items": []}))
        self.assertEqual(items, [])
        self.assertEqual(get.call_count, 1)

    def test_http_error_stops(self):
        items, get = self.fetch(lambda *a, **k: _response({"items": [_question(1)]}, status_code=502))
        self.assertEqual(items, [])
        self.assertEqual(get.call_count, 1)

if __name__ == "__main__":
    unittest.main()
