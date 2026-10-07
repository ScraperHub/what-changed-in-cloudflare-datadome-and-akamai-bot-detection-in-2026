import pytest

from bot_diag.routing import (
    API,
    DEFAULT_CHALLENGE_THRESHOLD,
    PROXY,
    SMART_PROXY_ENDPOINT,
    domain_key,
    record_challenge,
    route_domain,
)


def test_proxy_endpoint_is_the_documented_host():
    assert SMART_PROXY_ENDPOINT == "smartproxy.crawlbase.com:8013"


def test_www_and_url_share_one_hostname():
    assert domain_key("WWW.Example.com") == "example.com"
    assert domain_key("https://www.example.com/item") == "example.com"
    assert domain_key("https://Example.com") == "example.com"


def test_empty_domain_is_rejected():
    with pytest.raises(ValueError):
        domain_key("https:///missing-host")


def test_domain_stays_on_proxy_until_threshold():
    counts: dict[str, int] = {}
    assert route_domain("example.com", counts) == PROXY
    for _ in range(DEFAULT_CHALLENGE_THRESHOLD - 1):
        record_challenge("https://www.example.com/page", counts)
        assert route_domain("example.com", counts) == PROXY
    record_challenge("example.com", counts)
    assert counts["example.com"] == DEFAULT_CHALLENGE_THRESHOLD
    assert route_domain("https://www.example.com/other", counts) == API


def test_threshold_is_overridable():
    counts = {"example.com": 1}
    assert route_domain("example.com", counts, threshold=1) == API
    assert route_domain("example.com", counts, threshold=2) == PROXY


def test_threshold_must_be_positive():
    with pytest.raises(ValueError):
        route_domain("example.com", {}, threshold=0)


def test_other_domains_are_independent():
    counts = {"hard.example": DEFAULT_CHALLENGE_THRESHOLD}
    assert route_domain("hard.example", counts) == API
    assert route_domain("easy.example", counts) == PROXY
