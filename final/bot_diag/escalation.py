"""Map Crawlbase cb_status values to a next action.

Status meanings follow the Crawling API guidance checked for this article:
422 fix URL encoding and do not retry; 520 switch to the JavaScript token;
521 retry with backoff; 522 retry with backoff and consider country only for
geo-dependent targets; 523 remove or change country; 525 switch to the
JavaScript token, then retry or contact support; 595 fix the selector;
599 retry or contact support with the request ID.

Retry applies to those fetch-layer failures only. A confirmed block is never
retried, whatever ``cb_status`` arrived with it.
"""

from __future__ import annotations

from dataclasses import dataclass

FETCH_RETRY_STATUSES = frozenset({521, 522, 523, 599})
JAVASCRIPT_STATUSES = frozenset({520, 525})
NO_RETRY_STATUSES = frozenset({422, 595})


@dataclass(frozen=True)
class Plan:
    code: str
    retry: bool
    escalate_javascript: bool
    page_wait_ms: int | None
    ajax_wait: bool | None
    detail: str


@dataclass(frozen=True)
class _StatusAction:
    code: str
    retry: bool
    escalate_javascript: bool
    page_wait_ms: int | None
    ajax_wait: bool | None
    detail: str


_STATUS_ACTIONS: dict[int, _StatusAction] = {
    422: _StatusAction(
        "fix_url_encoding",
        False,
        False,
        None,
        None,
        "Fix URL encoding. Do not retry the same request.",
    ),
    520: _StatusAction(
        "escalate_javascript",
        False,
        True,
        None,
        None,
        "Empty response. Switch to the JavaScript token.",
    ),
    521: _StatusAction(
        "backoff_target_down",
        True,
        False,
        None,
        None,
        "Target unreachable. Retry with backoff; if it persists, verify the target is up.",
    ),
    522: _StatusAction(
        "backoff_or_country",
        True,
        False,
        None,
        None,
        "Connection timeout. Retry with backoff; consider country only for a geo-dependent target.",
    ),
    523: _StatusAction(
        "reroute_country",
        True,
        False,
        None,
        None,
        "Origin unreachable from this exit. Retry without country or choose another country.",
    ),
    525: _StatusAction(
        "escalate_javascript",
        False,
        True,
        None,
        None,
        "Challenge unsolved. Switch to the JavaScript token; then retry or contact support if it persists.",
    ),
    595: _StatusAction(
        "selector_not_found",
        False,
        False,
        None,
        None,
        "CSS selector was not found. Correct it or add a documented fallback; do not retry unchanged.",
    ),
    599: _StatusAction(
        "retry_or_support",
        True,
        False,
        None,
        None,
        "Internal Crawlbase error. Retry, or contact support with the request ID if it persists.",
    ),
}


def known_statuses() -> tuple[int, ...]:
    return tuple(sorted(_STATUS_ACTIONS))


def plan_action(cb_status: int | None, classification: str, *, javascript: bool) -> Plan:
    """Choose the next step for one response.

    ``classification`` comes from ``classify_response``. ``javascript`` is true
    when this response was already fetched with the JavaScript token.
    """
    if classification == "blocked":
        return Plan(
            "stop_confirmed_block",
            False,
            False,
            None,
            None,
            "Confirmed block. Do not retry.",
        )
    if classification == "ok":
        return Plan(
            "accept",
            False,
            False,
            None,
            None,
            "Expected fields are present.",
        )
    known = _STATUS_ACTIONS.get(cb_status) if cb_status is not None else None
    if known is not None:
        if cb_status == 525 and javascript:
            return Plan(
                "retry_javascript_or_support",
                True,
                False,
                None,
                None,
                "Challenge persisted on JavaScript. Retry with backoff, then contact support with the request ID.",
            )
        if known.escalate_javascript and javascript:
            return Plan(
                "stop_after_javascript",
                False,
                False,
                None,
                None,
                "JavaScript token already used. Do not retry this outcome.",
            )
        return Plan(
            known.code,
            known.retry,
            known.escalate_javascript,
            known.page_wait_ms if known.escalate_javascript else None,
            known.ajax_wait if known.escalate_javascript else None,
            known.detail,
        )
    if classification == "challenged" and not javascript:
        return Plan(
            "escalate_javascript",
            False,
            True,
            None,
            None,
            "Challenge document. Switch to the JavaScript token.",
        )
    if classification == "challenged" and javascript:
        return Plan(
            "stop_after_javascript",
            False,
            False,
            None,
            None,
            "JavaScript token already used. Do not retry this outcome.",
        )
    if classification == "invalid_content":
        return Plan(
            "invalid_content",
            False,
            False,
            None,
            None,
            "Response is missing expected fields. Do not retry the same request.",
        )
    return Plan("stop", False, False, None, None, "No retry for this outcome.")


def should_retry(cb_status: int | None, classification: str) -> bool:
    """True only for a documented fetch-layer retry, and never for a confirmed block."""
    return plan_action(cb_status, classification, javascript=False).retry


def backoff_seconds(attempt: int) -> float:
    """Modest exponential backoff. ``attempt`` starts at 1."""
    if attempt < 1:
        return 0.0
    return min(8.0, 0.5 * (2 ** (attempt - 1)))
