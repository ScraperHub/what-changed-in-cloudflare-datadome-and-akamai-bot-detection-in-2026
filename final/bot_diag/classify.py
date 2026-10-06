"""Classify a target response as blocked, challenged, invalid_content, or ok.

Vendor strings below are commonly observed markers, not a stable contract.
A 403 from an ordinary login wall can land in ``blocked``; rule that out
before treating the label as bot protection.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

LABEL_BLOCKED = "blocked"
LABEL_CHALLENGED = "challenged"
LABEL_INVALID_CONTENT = "invalid_content"
LABEL_OK = "ok"
LABELS = (LABEL_BLOCKED, LABEL_CHALLENGED, LABEL_INVALID_CONTENT, LABEL_OK)

_MAX_BODY = 2_000_000
_CF_CHALLENGE_MARKERS = (
    "/cdn-cgi/challenge-platform/",
    "cf-challenge",
    "cf-browser-verification",
    "challenge-platform",
)
_CF_BLOCK_MARKERS = (
    "sorry, you have been blocked",
    "you have been blocked",
    "error 1020",
    "error 1015",
    "error 1010",
)
_AKAMAI_REFERENCE = re.compile(r"reference\s*#\s*\d", re.I)
_ATTR_RE = re.compile(
    r"<[^>]*?\b(?:id|class|itemprop|name|property|data-field)\s*=\s*['\"]([^'\"]+)['\"][^>]*>([^<]*)",
    re.I,
)
_EMBEDDED_JSON = re.compile(r"\{[^{}]{1,20000}\}")


def classify_response(
    status: int | None,
    body: str,
    headers: Mapping[str, str] | None = None,
    expected_fields: Sequence[str] | None = None,
) -> str:
    header_map = _header_map(headers)
    text = body or ""
    lowered = text.lower()
    if _is_cloudflare_challenge(lowered, header_map) or _is_datadome_challenge(lowered, header_map):
        return LABEL_CHALLENGED
    is_blocked = (
        _is_akamai_block(text, lowered)
        or _is_cloudflare_block(lowered, header_map)
        or _is_datadome_block(status, lowered, header_map)
        or (status in {401, 403, 429} and bool(text.strip()))
    )
    if is_blocked:
        return LABEL_BLOCKED
    return _content_label(status, text, expected_fields)


def missing_fields(body: str, expected_fields: Sequence[str] | None) -> list[str]:
    """Field names that are absent or blank. Empty ``expected_fields`` checks nothing."""
    if not expected_fields:
        return []
    extracted = extract_fields(body)
    missing: list[str] = []
    for name in expected_fields:
        value = _field_value(extracted, name)
        if value is None or value == "":
            missing.append(name)
    return missing


def extract_fields(body: str) -> dict[str, str]:
    """Pull flat field names from a JSON document or simple HTML attributes."""
    text = (body or "")[:_MAX_BODY]
    found: dict[str, str] = {}
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            _flatten(data, found)
            return found
    for match in _EMBEDDED_JSON.finditer(text):
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            _flatten(data, found)
    for match in _ATTR_RE.finditer(text):
        raw_name, value = match.group(1), match.group(2).strip()
        for token in raw_name.split():
            found.setdefault(token, value)
    return found


def _content_label(status: int | None, body: str, expected_fields: Sequence[str] | None) -> str:
    if expected_fields and missing_fields(body, expected_fields):
        return LABEL_INVALID_CONTENT
    if not expected_fields and not body.strip():
        return LABEL_INVALID_CONTENT
    if status is not None and status >= 400:
        return LABEL_INVALID_CONTENT
    return LABEL_OK


def _header_map(headers: Mapping[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    mapped: dict[str, str] = {}
    cookies: list[str] = []
    for key, value in headers.items():
        if value is None:
            continue
        lowered = str(key).lower()
        text = str(value)
        if lowered == "set-cookie":
            cookies.append(text)
            continue
        mapped[lowered] = text
    if cookies:
        mapped["set-cookie"] = "\n".join(cookies)
    return mapped


def _is_cloudflare_challenge(body: str, headers: Mapping[str, str]) -> bool:
    mitigated = headers.get("cf-mitigated", "").lower()
    if "challenge" in mitigated:
        return True
    if any(marker in body for marker in _CF_CHALLENGE_MARKERS):
        return True
    if "just a moment" in body and (headers.get("cf-ray") or mitigated):
        return True
    return False


def _is_datadome_challenge(body: str, headers: Mapping[str, str]) -> bool:
    if "captcha-delivery.com" in body:
        return True
    cookie = headers.get("set-cookie", "").lower()
    has_signal = "datadome=" in cookie or bool(headers.get("x-datadome"))
    return has_signal and "captcha" in body


def _is_cloudflare_block(body: str, headers: Mapping[str, str]) -> bool:
    mitigated = headers.get("cf-mitigated", "").lower()
    if "block" in mitigated and "challenge" not in mitigated:
        return True
    return any(marker in body for marker in _CF_BLOCK_MARKERS)


def _is_datadome_block(status: int | None, body: str, headers: Mapping[str, str]) -> bool:
    if _is_datadome_challenge(body, headers):
        return False
    cookie = headers.get("set-cookie", "").lower()
    has_signal = "datadome=" in cookie or bool(headers.get("x-datadome"))
    return has_signal and status in {401, 403, 429, 503}


def _is_akamai_block(body: str, lowered: str) -> bool:
    if "errors.edgesuite.net" in lowered:
        return True
    return "access denied" in lowered and _AKAMAI_REFERENCE.search(body) is not None


def _flatten(data: object, found: dict[str, str]) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                _flatten(value, found)
            else:
                found.setdefault(str(key), _stringify(value))
        return
    if isinstance(data, list):
        for item in data:
            _flatten(item, found)


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _field_value(extracted: Mapping[str, str], name: str) -> str | None:
    if name in extracted:
        return extracted[name]
    lowered = name.lower()
    for key, value in extracted.items():
        if key.lower() == lowered:
            return value
    return None
