import csv
import threading
from pathlib import Path

import pytest

from bot_diag.client import ParsedResponse
from bot_diag.evaluate import (
    CSV_COLUMNS,
    SampleRow,
    evaluate_urls,
    normalize_concurrency,
    percentile,
    summarize,
    write_csv,
)

FIELDS = ["price", "title"]
AKAMAI = (Path(__file__).resolve().parent / "fixtures" / "akamai_block.html").read_text(encoding="utf-8")


def _row(url, classification, latency, fetch_retries, js_escalations):
    return SampleRow(
        url=url,
        cb_status=200,
        original_status=200,
        final_url=url,
        domain_complexity="standard",
        classification=classification,
        latency_ms=latency,
        fetch_retries=fetch_retries,
        js_escalations=js_escalations,
        usable=classification == "ok",
        action="accept" if classification == "ok" else "stop",
    )


def test_fixed_sample_stats():
    rows = [
        _row("https://example.com/1", "ok", 100, 1, 0),
        _row("https://example.com/2", "ok", 200, 0, 1),
        _row("https://example.com/3", "ok", 300, 2, 0),
        _row("https://example.com/4", "invalid_content", 400, 0, 0),
        _row("https://example.com/5", "blocked", 500, 0, 0),
    ]
    summary = summarize(rows)
    assert summary["requests"] == 5
    assert summary["usable"] == 3
    assert summary["usable_rate"] == 3 / 5
    assert summary["p50_ms"] == 300
    assert summary["p95_ms"] == 500
    assert summary["fetch_retries"] == 3
    assert summary["js_escalations"] == 1
    assert summary["retry_overhead"] == 4 / 3


def test_percentile_nearest_rank():
    values = [10, 20, 30, 40, 50]
    assert percentile(values, 50) == 30
    assert percentile(values, 95) == 50
    assert percentile([], 50) is None


def test_empty_summary():
    summary = summarize([])
    assert summary["usable_rate"] == 0.0
    assert summary["p50_ms"] is None
    assert summary["p95_ms"] is None
    assert summary["retry_overhead"] is None


def test_csv_columns(tmp_path):
    path = tmp_path / "out.csv"
    write_csv(path, [_row("https://example.com/", "ok", 10, 0, 0)])
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(CSV_COLUMNS)
        row = next(reader)
    assert row["classification"] == "ok"
    assert row["usable"] == "true"
    assert row["url"] == "https://example.com/"


class Scripted:
    def __init__(self, scripts):
        self.scripts = {url: list(items) for url, items in scripts.items()}
        self.calls = []
        self._lock = threading.Lock()

    def fetch(self, url, **kwargs):
        with self._lock:
            self.calls.append((url, kwargs))
            return self.scripts[url].pop(0)


def _parsed(url, *, cb_status, original_status, body, complexity="standard"):
    return ParsedResponse(
        http_status=cb_status,
        cb_status=cb_status,
        original_status=original_status,
        final_url=url,
        domain_complexity=complexity,
        body=body,
        headers={},
    )


def _ok(url):
    return _parsed(
        url,
        cb_status=200,
        original_status=200,
        body='{"title": "Widget", "price": "12.00"}',
    )


def test_blocked_url_is_not_retried(monkeypatch):
    monkeypatch.setattr("bot_diag.client._sdk_get", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")))
    monkeypatch.setattr(
        "bot_diag.client._requests_get",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")),
    )
    url = "https://example.com/blocked"
    page = _parsed(url, cb_status=599, original_status=403, body=AKAMAI, complexity="complex")
    client = Scripted({url: [page, _ok(url)]})
    sleeps = []
    rows = evaluate_urls(client, [url], FIELDS, max_retries=2, sleeper=sleeps.append)
    assert len(client.calls) == 1
    assert rows[0].classification == "blocked"
    assert rows[0].usable is False
    assert rows[0].action == "stop_confirmed_block"
    assert rows[0].fetch_retries == 0
    assert sleeps == []


def test_521_retries_then_stops(monkeypatch):
    monkeypatch.setattr("bot_diag.client._sdk_get", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")))
    url = "https://example.com/flaky"
    failure = _parsed(url, cb_status=521, original_status=None, body="", complexity=None)
    client = Scripted({url: [failure, failure, failure]})
    sleeps = []
    rows = evaluate_urls(
        client,
        [url],
        FIELDS,
        max_retries=2,
        country="DE",
        sleeper=sleeps.append,
    )
    assert len(client.calls) == 3
    assert [call[1]["country"] for call in client.calls] == ["DE", "DE", "DE"]
    assert sleeps == [0.5, 1.0]
    assert rows[0].fetch_retries == 2
    assert rows[0].usable is False
    assert rows[0].action == "backoff_target_down"


def test_422_does_not_retry():
    url = "https://example.com/bad-encoding"
    failure = _parsed(url, cb_status=422, original_status=None, body="", complexity=None)
    client = Scripted({url: [failure, _ok(url)]})
    rows = evaluate_urls(client, [url], FIELDS, sleeper=lambda _seconds: None)
    assert len(client.calls) == 1
    assert rows[0].action == "fix_url_encoding"
    assert rows[0].fetch_retries == 0


def test_520_with_empty_403_still_escalates():
    url = "https://example.com/empty-403"
    empty = _parsed(url, cb_status=520, original_status=403, body="", complexity=None)
    client = Scripted({url: [empty, _ok(url)]})
    rows = evaluate_urls(client, [url], FIELDS, sleeper=lambda _seconds: None)
    assert len(client.calls) == 2
    assert client.calls[1][1]["javascript"] is True
    assert rows[0].usable is True
    assert rows[0].js_escalations == 1


def test_520_escalates_once_without_waits():
    url = "https://example.com/shell"
    empty = _parsed(url, cb_status=520, original_status=200, body="", complexity="moderate")
    client = Scripted({url: [empty, empty, empty]})
    rows = evaluate_urls(client, [url], FIELDS, sleeper=lambda _seconds: None)
    assert len(client.calls) == 2
    assert client.calls[0][1]["javascript"] is False
    assert client.calls[1][1]["javascript"] is True
    assert client.calls[1][1]["page_wait_ms"] is None
    assert client.calls[1][1]["ajax_wait"] is None
    assert rows[0].js_escalations == 1
    assert rows[0].action == "stop_after_javascript"


def test_525_escalates_without_automatic_waits():
    url = "https://example.com/challenge"
    challenge = (
        "<html><script src='/cdn-cgi/challenge-platform/h/g/orchestrate/jsch/v1'></script></html>"
    )
    first = _parsed(url, cb_status=525, original_status=403, body=challenge, complexity="complex")
    client = Scripted({url: [first, _ok(url)]})
    rows = evaluate_urls(client, [url], FIELDS, sleeper=lambda _seconds: None)
    assert len(client.calls) == 2
    assert client.calls[1][1]["javascript"] is True
    assert client.calls[1][1]["page_wait_ms"] is None
    assert client.calls[1][1]["ajax_wait"] is None
    assert rows[0].usable is True
    assert rows[0].js_escalations == 1
    assert rows[0].classification == "ok"


def test_persistent_525_retries_javascript_once_then_stops():
    url = "https://example.com/persistent-challenge"
    challenge = "<html><script src='/cdn-cgi/challenge-platform/orchestrate'></script></html>"
    failure = _parsed(url, cb_status=525, original_status=403, body=challenge, complexity="complex")
    client = Scripted({url: [failure, failure, failure, failure]})
    rows = evaluate_urls(client, [url], FIELDS, max_retries=2, sleeper=lambda _seconds: None)
    assert len(client.calls) == 3
    assert rows[0].fetch_retries == 1
    assert rows[0].js_escalations == 1
    assert rows[0].action == "retry_javascript_or_support"


def test_595_does_not_retry():
    url = "https://example.com/selector"
    failure = _parsed(url, cb_status=595, original_status=200, body='{"title": "Widget"}', complexity="standard")
    client = Scripted({url: [failure, _ok(url)]})
    rows = evaluate_urls(client, [url], FIELDS, sleeper=lambda _seconds: None)
    assert len(client.calls) == 1
    assert rows[0].action == "selector_not_found"


def test_sample_keeps_url_order():
    urls = [f"https://example.com/{index}" for index in range(4)]
    client = Scripted({url: [_ok(url)] for url in urls})
    rows = evaluate_urls(client, urls, FIELDS, concurrency=4, sleeper=lambda _seconds: None)
    assert [row.url for row in rows] == urls
    assert all(row.usable for row in rows)


def test_concurrency_cap():
    assert normalize_concurrency(4) == 4
    assert normalize_concurrency(100) == 8
    with pytest.raises(ValueError):
        normalize_concurrency(0)
