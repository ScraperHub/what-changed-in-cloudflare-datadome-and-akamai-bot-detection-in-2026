import pytest

from bot_diag.escalation import backoff_seconds, known_statuses, plan_action, should_retry

EXPECTED = [
    (422, "fix_url_encoding", False, False, None, None),
    (520, "escalate_javascript", False, True, None, None),
    (521, "backoff_target_down", True, False, None, None),
    (522, "backoff_or_country", True, False, None, None),
    (523, "reroute_country", True, False, None, None),
    (525, "escalate_javascript", False, True, None, None),
    (595, "selector_not_found", False, False, None, None),
    (599, "retry_or_support", True, False, None, None),
]


def test_every_documented_status_is_in_the_table():
    assert known_statuses() == (422, 520, 521, 522, 523, 525, 595, 599)


@pytest.mark.parametrize("status,code,retry,javascript,page_wait,ajax_wait", EXPECTED)
def test_status_action(status, code, retry, javascript, page_wait, ajax_wait):
    plan = plan_action(status, "invalid_content", javascript=False)
    assert plan.code == code
    assert plan.retry is retry
    assert plan.escalate_javascript is javascript
    assert plan.page_wait_ms == page_wait
    assert plan.ajax_wait == ajax_wait
    assert should_retry(status, "invalid_content") is retry


@pytest.mark.parametrize("status", [422, 520, 521, 522, 523, 525, 595, 599])
def test_confirmed_block_is_never_retried(status):
    plan = plan_action(status, "blocked", javascript=False)
    assert plan.code == "stop_confirmed_block"
    assert plan.retry is False
    assert plan.escalate_javascript is False
    assert should_retry(status, "blocked") is False


def test_525_after_javascript_retries_without_escalation():
    plan = plan_action(525, "challenged", javascript=True)
    assert plan.code == "retry_javascript_or_support"
    assert plan.retry is True
    assert plan.escalate_javascript is False


def test_challenge_on_200_escalates_without_inventing_waits():
    plan = plan_action(200, "challenged", javascript=False)
    assert plan.escalate_javascript is True
    assert plan.page_wait_ms is None
    assert plan.ajax_wait is None
    assert plan.retry is False


def test_ok_is_accepted():
    plan = plan_action(200, "ok", javascript=False)
    assert plan.code == "accept"
    assert plan.retry is False


def test_backoff_is_modest():
    assert backoff_seconds(1) == 0.5
    assert backoff_seconds(2) == 1.0
    assert backoff_seconds(3) == 2.0
    assert backoff_seconds(10) == 8.0
