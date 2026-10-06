"""Sample authorized URLs and summarize usable data.

Usable means ``classify_response`` returned ``ok``. Latency percentiles use
the nearest-rank method on the sum of attempt durations, excluding backoff
sleep. Retry overhead is fetch-layer retries plus JavaScript escalations,
divided by the number of usable rows.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from bot_diag.classify import classify_response
from bot_diag.client import CrawlError, MissingTokenError, ParsedResponse
from bot_diag.escalation import backoff_seconds, plan_action

MAX_CONCURRENCY = 8
CSV_COLUMNS = (
    "url",
    "cb_status",
    "original_status",
    "final_url",
    "domain_complexity",
    "classification",
    "latency_ms",
    "fetch_retries",
    "js_escalations",
    "usable",
    "action",
)


@dataclass
class SampleRow:
    url: str
    cb_status: int | None
    original_status: int | None
    final_url: str | None
    domain_complexity: str | None
    classification: str
    latency_ms: float
    fetch_retries: int
    js_escalations: int
    usable: bool
    action: str


def normalize_concurrency(value: int) -> int:
    if value < 1:
        raise ValueError("concurrency must be at least 1")
    return min(value, MAX_CONCURRENCY)


def percentile(values: Sequence[float], percent: float) -> float | None:
    """Nearest-rank percentile. ``percent`` is 50 for p50 and 95 for p95."""
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if percent <= 0:
        return ordered[0]
    if percent >= 100:
        return ordered[-1]
    rank = math.ceil(percent / 100 * len(ordered))
    index = min(len(ordered), max(1, rank)) - 1
    return ordered[index]


def summarize(rows: Sequence[SampleRow]) -> dict[str, object]:
    requests = len(rows)
    usable = sum(1 for row in rows if row.usable)
    fetch_retries = sum(row.fetch_retries for row in rows)
    js_escalations = sum(row.js_escalations for row in rows)
    extra = fetch_retries + js_escalations
    return {
        "requests": requests,
        "usable": usable,
        "usable_rate": (usable / requests) if requests else 0.0,
        "p50_ms": percentile([row.latency_ms for row in rows], 50),
        "p95_ms": percentile([row.latency_ms for row in rows], 95),
        "fetch_retries": fetch_retries,
        "js_escalations": js_escalations,
        "retry_overhead": (extra / usable) if usable else None,
    }


def format_summary(summary: dict[str, object]) -> str:
    overhead = summary["retry_overhead"]
    overhead_text = "n/a" if overhead is None else f"{float(overhead):.2f}"
    return "\n".join(
        [
            f"requests: {summary['requests']}",
            f"usable_rate: {float(summary['usable_rate']):.4f}",
            f"p50_ms: {_num(summary['p50_ms'])}",
            f"p95_ms: {_num(summary['p95_ms'])}",
            f"retry_overhead: {overhead_text}",
            f"fetch_retries: {summary['fetch_retries']}",
            f"js_escalations: {summary['js_escalations']}",
        ]
    )


def read_urls(path: Path) -> list[str]:
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if not text.startswith(("http://", "https://")):
            raise ValueError(f"URL must start with http:// or https://: {text}")
        urls.append(text)
    if not urls:
        raise ValueError(f"No URLs in {path}")
    return urls


def write_csv(path: Path, rows: Sequence[SampleRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "url": row.url,
                    "cb_status": _cell(row.cb_status),
                    "original_status": _cell(row.original_status),
                    "final_url": row.final_url or "",
                    "domain_complexity": row.domain_complexity or "",
                    "classification": row.classification,
                    "latency_ms": f"{row.latency_ms:.3f}",
                    "fetch_retries": row.fetch_retries,
                    "js_escalations": row.js_escalations,
                    "usable": "true" if row.usable else "false",
                    "action": row.action,
                }
            )


def evaluate_urls(
    client: object,
    urls: Sequence[str],
    expected_fields: Sequence[str],
    *,
    concurrency: int = 4,
    max_retries: int = 2,
    country: str | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> list[SampleRow]:
    """Fetch each URL with modest concurrency and apply the status actions."""
    if not expected_fields:
        raise ValueError("expected_fields must name at least one field")
    if max_retries < 0:
        raise ValueError("max_retries must be at least 0")
    workers = normalize_concurrency(min(concurrency, max(1, len(urls))))
    pause = sleeper or time.sleep
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                collect_one,
                client,
                url,
                expected_fields,
                max_retries=max_retries,
                country=country,
                sleeper=pause,
            )
            for url in urls
        ]
        return [future.result() for future in futures]


def collect_one(
    client: object,
    url: str,
    expected_fields: Sequence[str],
    *,
    max_retries: int,
    country: str | None,
    sleeper: Callable[[float], None],
) -> SampleRow:
    javascript = False
    page_wait_ms: int | None = None
    ajax_wait: bool | None = None
    fetch_retries = 0
    js_escalations = 0
    latency_ms = 0.0
    # One JavaScript escalation plus the initial attempt and the retry budget.
    attempt_cap = max_retries + 2
    last: SampleRow | None = None
    for _ in range(attempt_cap):
        started = time.perf_counter()
        try:
            parsed = client.fetch(  # type: ignore[attr-defined]
                url,
                javascript=javascript,
                page_wait_ms=page_wait_ms,
                ajax_wait=ajax_wait,
                country=country,
            )
        except MissingTokenError as exc:
            latency_ms += (time.perf_counter() - started) * 1000
            return _failed_row(url, latency_ms, fetch_retries, js_escalations, "missing_token", str(exc))
        except CrawlError as exc:
            latency_ms += (time.perf_counter() - started) * 1000
            return _failed_row(url, latency_ms, fetch_retries, js_escalations, "request_failed", str(exc))
        latency_ms += (time.perf_counter() - started) * 1000
        classification = classify_response(
            parsed.original_status,
            parsed.body,
            parsed.headers,
            expected_fields,
        )
        plan = plan_action(parsed.cb_status, classification, javascript=javascript)
        last = SampleRow(
            url=url,
            cb_status=parsed.cb_status,
            original_status=parsed.original_status,
            final_url=parsed.final_url,
            domain_complexity=parsed.domain_complexity,
            classification=classification,
            latency_ms=latency_ms,
            fetch_retries=fetch_retries,
            js_escalations=js_escalations,
            usable=classification == "ok",
            action=plan.code,
        )
        if classification == "ok":
            break
        if plan.escalate_javascript:
            javascript = True
            page_wait_ms = plan.page_wait_ms
            ajax_wait = plan.ajax_wait
            js_escalations += 1
            continue
        retry_limit = min(max_retries, 1) if parsed.cb_status == 525 and javascript else max_retries
        if plan.retry and fetch_retries < retry_limit:
            fetch_retries += 1
            sleeper(backoff_seconds(fetch_retries))
            continue
        break
    if last is None:
        return _failed_row(url, latency_ms, fetch_retries, js_escalations, "request_failed", "no response")
    last.fetch_retries = fetch_retries
    last.js_escalations = js_escalations
    return last


class DryRunClient:
    """Offline stand-in used by ``--dry-run``. It never calls the network."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self._lock = threading.Lock()

    def fetch(
        self,
        url: str,
        *,
        javascript: bool = False,
        page_wait_ms: int | None = None,
        ajax_wait: bool | None = None,
        country: str | None = None,
    ) -> ParsedResponse:
        del ajax_wait, country
        with self._lock:
            attempt = self._seen.get(url, 0)
            self._seen[url] = attempt + 1
        bucket = int(hashlib.sha256(url.encode("utf-8")).hexdigest()[:8], 16) % 4
        return _dry_payload(
            url,
            bucket,
            attempt,
            javascript=javascript,
            page_wait_ms=page_wait_ms,
        )


def _dry_payload(
    url: str,
    bucket: int,
    attempt: int,
    *,
    javascript: bool,
    page_wait_ms: int | None,
) -> ParsedResponse:
    if bucket == 0 or attempt > 0 or javascript:
        body = json.dumps({"title": "Widget", "price": "12.00"})
        return _envelope(url, 200, 200, "standard", body)
    if bucket == 1:
        return _envelope(url, 521, None, None, "")
    if bucket == 2:
        # The follow-up JavaScript attempt succeeds so the dry run can finish.
        del page_wait_ms
        challenge = (
            "<html><title>Just a moment...</title>"
            "<script src='/cdn-cgi/challenge-platform/h/g/orchestrate/jsch/v1'></script></html>"
        )
        return _envelope(url, 525, 403, "complex", challenge)
    return _envelope(url, 200, 200, "moderate", json.dumps({"title": "Widget"}))


def _envelope(
    url: str,
    cb_status: int,
    original_status: int | None,
    complexity: str | None,
    page: str,
) -> ParsedResponse:
    return ParsedResponse(
        http_status=cb_status,
        cb_status=cb_status,
        original_status=original_status,
        final_url=url,
        domain_complexity=complexity,
        body=page,
        headers={},
    )


def _failed_row(
    url: str,
    latency_ms: float,
    fetch_retries: int,
    js_escalations: int,
    action: str,
    detail: str,
) -> SampleRow:
    del detail
    return SampleRow(
        url=url,
        cb_status=None,
        original_status=None,
        final_url=None,
        domain_complexity=None,
        classification="invalid_content",
        latency_ms=latency_ms,
        fetch_retries=fetch_retries,
        js_escalations=js_escalations,
        usable=False,
        action=action,
    )


def _cell(value: int | None) -> str:
    return "" if value is None else str(value)


def _num(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.1f}"
