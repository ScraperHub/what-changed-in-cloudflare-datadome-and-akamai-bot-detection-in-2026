"""Choose Smart AI Proxy or the Crawling API for one domain.

Easy domains stay on the proxy. After N challenge responses for the same
hostname, later requests for that domain go to the Crawling API. This module
only counts and chooses. It does not open a proxy connection.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

PROXY = "proxy"
API = "api"
SMART_PROXY_ENDPOINT = "smartproxy.crawlbase.com:8013"
DEFAULT_CHALLENGE_THRESHOLD = 3


def domain_key(value: str) -> str:
    """Hostname used as the challenge-count key.

    Accepts a host or an absolute URL. Comparison is case-insensitive, and a
    leading ``www.`` is removed so both forms share one counter.
    """
    text = value.strip().lower()
    if "://" in text:
        text = urlparse(text).hostname or ""
    if text.startswith("www."):
        text = text[4:]
    if not text:
        raise ValueError("domain must include a hostname")
    return text


def record_challenge(domain: str, challenge_counts: dict[str, int]) -> int:
    """Increment the challenge count for ``domain`` and return the new total."""
    key = domain_key(domain)
    challenge_counts[key] = challenge_counts.get(key, 0) + 1
    return challenge_counts[key]


def route_domain(
    domain: str,
    challenge_counts: Mapping[str, int],
    *,
    threshold: int = DEFAULT_CHALLENGE_THRESHOLD,
) -> str:
    """Return ``api`` after ``threshold`` challenges, otherwise ``proxy``.

    ``proxy`` means the caller's existing HTTP client should keep using
    ``smartproxy.crawlbase.com:8013``. ``api`` means that domain should move
    to the Crawling API. Counts must already be keyed by ``domain_key``.
    """
    if threshold < 1:
        raise ValueError("threshold must be at least 1")
    key = domain_key(domain)
    if challenge_counts.get(key, 0) >= threshold:
        return API
    return PROXY
