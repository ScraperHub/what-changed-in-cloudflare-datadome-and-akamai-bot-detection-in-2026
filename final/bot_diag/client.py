"""Call the Crawling API and normalize the response envelope.

The official ``crawlbase`` SDK is the primary client. ``requests`` is used
when the SDK is not importable or the SDK call fails in transport. Tokens are
read from ``CRAWLBASE_TOKEN`` and ``CRAWLBASE_JS_TOKEN`` only.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_ENDPOINT = "https://api.crawlbase.com/"
TOKEN_ENV = "CRAWLBASE_TOKEN"
JS_TOKEN_ENV = "CRAWLBASE_JS_TOKEN"
_TOKEN_NAMES = frozenset({TOKEN_ENV, JS_TOKEN_ENV})
_MISSING = frozenset({"", "none", "null"})
_TOKEN_IN_TEXT = re.compile(r"(token=)[^&\s'\"]+", re.I)


class MissingTokenError(RuntimeError):
    """A required Crawlbase token is not in the environment."""


class CrawlError(RuntimeError):
    """The Crawling API request failed before a response could be parsed."""


@dataclass(frozen=True)
class ParsedResponse:
    http_status: int | None
    cb_status: int | None
    original_status: int | None
    final_url: str | None
    domain_complexity: str | None
    body: str
    headers: dict[str, str]


def build_options(
    *,
    page_wait_ms: int | None = None,
    ajax_wait: bool | None = None,
    country: str | None = None,
) -> dict[str, Any]:
    """Query options for one Crawling API call. The target URL is passed separately.

    ``format=json`` puts ``cb_status``, ``original_status``, and ``url`` in the
    body. ``page_wait`` and ``ajax_wait`` are sent only when set. ``country``
    is sent only when the caller sets it.
    """
    options: dict[str, Any] = {"format": "json"}
    if page_wait_ms is not None:
        options["page_wait"] = int(page_wait_ms)
    if ajax_wait is not None:
        options["ajax_wait"] = bool(ajax_wait)
    if country is not None:
        options["country"] = _country(country)
    return options


def parse_response(response: Mapping[str, Any], requested_url: str | None = None) -> ParsedResponse:
    """Accept an SDK result, a requests-shaped result, or a bare JSON envelope.

    SDK 1.1.0 usually returns ``status_code``, ``headers``, and ``body`` bytes.
    With ``format=json`` the body is an envelope. ``domain_complexity`` may be
    a JSON field or a ``domain_complexity`` / ``X-Domain-Complexity`` header.
    The string ``\"None\"`` that the SDK writes for a missing header is ignored.
    ``pc_status`` is used only when ``cb_status`` is absent.

    ``requested_url`` is accepted so callers can keep the URL they sent. It is
    not copied into ``final_url``.
    """
    del requested_url  # The final URL comes from the response, not the request.
    if not isinstance(response, Mapping):
        raise TypeError("response must be a mapping")

    headers = _header_map(response.get("headers"))
    status_code = _as_int(response.get("status_code")) if "status_code" in response else None
    raw_text = _body_text(response.get("body"))
    envelope = _loads_object(raw_text)
    if envelope is not None and not _is_envelope(envelope):
        envelope = None
    if envelope is None and "status_code" not in response and _is_envelope(response):
        envelope = response

    page = _page_from_envelope(envelope, raw_text)
    cb_status = _as_int(
        _first(
            _mapping_get(envelope, "cb_status"),
            headers.get("cb_status"),
            _mapping_get(envelope, "pc_status"),
            headers.get("pc_status"),
        )
    )
    if cb_status is None:
        cb_status = status_code
    return ParsedResponse(
        http_status=status_code,
        cb_status=cb_status,
        original_status=_as_int(_first(_mapping_get(envelope, "original_status"), headers.get("original_status"))),
        final_url=_first(_mapping_get(envelope, "url"), headers.get("url")),
        domain_complexity=_first(
            _mapping_get(envelope, "domain_complexity"),
            headers.get("domain_complexity"),
            headers.get("x-domain-complexity"),
        ),
        body=page,
        headers=headers,
    )


class CrawlClient:
    """Fetch one authorized URL through the Crawling API."""

    def __init__(self, token: str, js_token: str | None = None, timeout: int = 90) -> None:
        self.token = token.strip()
        self.js_token = js_token.strip() if js_token else None
        self.timeout = timeout

    def fetch(
        self,
        url: str,
        *,
        javascript: bool = False,
        page_wait_ms: int | None = None,
        ajax_wait: bool | None = None,
        country: str | None = None,
    ) -> ParsedResponse:
        token = self.js_token if javascript else self.token
        if not token:
            name = JS_TOKEN_ENV if javascript else TOKEN_ENV
            raise MissingTokenError(f"{name} is not set.")
        options = build_options(page_wait_ms=page_wait_ms, ajax_wait=ajax_wait, country=country)
        try:
            raw = _sdk_get(token, url, options, self.timeout)
        except ImportError:
            raw = _requests_get(token, url, options, self.timeout)
        except OSError as exc:
            try:
                raw = _requests_get(token, url, options, self.timeout)
            except Exception as second:
                raise CrawlError(_redact(f"Crawlbase request failed: {exc}; fallback failed: {second}")) from None
        return parse_response(raw, requested_url=url)


def normal_token() -> str:
    load_env()
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise MissingTokenError(
            "CRAWLBASE_TOKEN is not set. Copy code/.env.example to code/.env and set it."
        )
    return token


def javascript_token() -> str | None:
    load_env()
    token = os.environ.get(JS_TOKEN_ENV, "").strip()
    return token or None


def load_env() -> None:
    """Load the two token variables from a local ``.env`` without overriding the process."""
    for path in _env_candidates():
        if path.name != ".env" or not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            key = key.strip()
            if key not in _TOKEN_NAMES:
                continue
            if os.environ.get(key, "").strip():
                continue
            os.environ[key] = value.strip().strip('"').strip("'")
        return


def _env_candidates() -> list[Path]:
    package_env = Path(__file__).resolve().parents[2] / ".env"
    paths = [Path.cwd() / ".env", package_env]
    unique: list[Path] = []
    for path in paths:
        if path.name != ".env" or path in unique:
            continue
        unique.append(path)
    return unique


def _sdk_get(token: str, url: str, options: dict[str, Any], timeout: int) -> dict[str, Any]:
    try:
        from crawlbase import CrawlingAPI
    except ImportError as exc:
        raise ImportError("crawlbase SDK is not installed") from exc
    api = CrawlingAPI({"token": token, "timeout": timeout})
    # CrawlingAPI.get writes options["url"] in place. Hand it a fresh dict.
    return api.get(url, dict(options))


def _requests_get(token: str, url: str, options: Mapping[str, Any], timeout: int) -> dict[str, Any]:
    import requests

    params: dict[str, Any] = {"token": token, "url": url, **dict(options)}
    try:
        response = requests.get(API_ENDPOINT, params=params, timeout=timeout)
    except Exception as exc:
        raise CrawlError(_redact(f"Crawlbase request failed: {exc}")) from None
    return {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "body": response.content,
    }


def _country(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z]{2}", value):
        raise ValueError("country must be a two-letter code")
    return value.upper()


def _redact(message: str) -> str:
    return _TOKEN_IN_TEXT.sub(r"\1REDACTED", message)


def _body_text(body: object) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        return body
    return json.dumps(body)


def _loads_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None


def _is_envelope(data: Mapping[str, Any] | None) -> bool:
    if not isinstance(data, Mapping):
        return False
    return any(key in data for key in ("cb_status", "pc_status", "original_status"))


def _page_from_envelope(envelope: Mapping[str, Any] | None, raw_text: str) -> str:
    if not isinstance(envelope, Mapping) or not _is_envelope(envelope):
        return raw_text
    if "body" not in envelope:
        return ""
    inner = envelope.get("body")
    if isinstance(inner, (dict, list)):
        return json.dumps(inner)
    if inner is None:
        return ""
    return str(inner)


def _header_map(headers: object) -> dict[str, str]:
    if headers is None or not hasattr(headers, "items"):
        return {}
    mapped: dict[str, str] = {}
    cookies: list[str] = []
    for key, value in headers.items():
        lowered = str(key).lower()
        text = "" if value is None else str(value)
        if lowered == "set-cookie":
            cookies.append(text)
            continue
        mapped[lowered] = text
    if cookies:
        mapped["set-cookie"] = "\n".join(cookies)
    return mapped


def _mapping_get(data: Mapping[str, Any] | None, key: str) -> object:
    if not isinstance(data, Mapping):
        return None
    if key in data:
        return data.get(key)
    lowered = key.lower()
    for name, value in data.items():
        if str(name).lower() == lowered:
            return value
    return None


def _first(*values: object) -> object:
    for value in values:
        if _clean(value) is not None:
            return value
    return None


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _MISSING:
        return None
    return text


def _as_int(value: object) -> int | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None
