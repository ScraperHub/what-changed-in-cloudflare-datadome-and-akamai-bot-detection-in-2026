import json
import os
from pathlib import Path

import pytest

from bot_diag.classify import classify_response
from bot_diag.client import (
    TOKEN_ENV,
    CrawlClient,
    CrawlError,
    MissingTokenError,
    build_options,
    load_env,
    parse_response,
)

FIELDS = ["price", "title"]


def test_parse_sdk_envelope_ignores_none_headers():
    envelope = {
        "cb_status": 200,
        "original_status": 200,
        "url": "https://example.com/item",
        "domain_complexity": "moderate",
        "body": json.dumps({"title": "Widget", "price": "12.00"}),
    }
    parsed = parse_response(
        {
            "status_code": 200,
            "headers": {"cb_status": "None", "original_status": "None", "url": "None"},
            "body": json.dumps(envelope).encode(),
        }
    )
    assert parsed.cb_status == 200
    assert parsed.original_status == 200
    assert parsed.final_url == "https://example.com/item"
    assert parsed.domain_complexity == "moderate"
    assert classify_response(parsed.original_status, parsed.body, parsed.headers, FIELDS) == "ok"


@pytest.mark.parametrize(
    "header_name",
    ["X-Domain-Complexity", "domain_complexity"],
)
def test_domain_complexity_headers(header_name):
    parsed = parse_response(
        {
            "status_code": 200,
            "headers": {
                "cb_status": "200",
                "original_status": "200",
                "url": "https://example.com/",
                header_name: "complex",
            },
            "body": b"<html>ok</html>",
        }
    )
    assert parsed.domain_complexity == "complex"
    assert parsed.final_url == "https://example.com/"


def test_pc_status_fallback():
    envelope = {
        "pc_status": 200,
        "original_status": 204,
        "url": "https://example.com/",
        "body": "hi",
    }
    parsed = parse_response({"status_code": 200, "headers": {}, "body": json.dumps(envelope).encode()})
    assert parsed.cb_status == 200
    assert parsed.original_status == 204
    assert parsed.body == "hi"


def test_target_json_is_not_an_envelope():
    body = b'{"title": "Widget", "price": "9"}'
    parsed = parse_response(
        {
            "status_code": 200,
            "headers": {
                "cb_status": "200",
                "original_status": "200",
                "url": "https://example.com/",
            },
            "body": body,
        }
    )
    assert parsed.body == '{"title": "Widget", "price": "9"}'
    assert classify_response(parsed.original_status, parsed.body, parsed.headers, FIELDS) == "ok"


def test_http_error_shape_uses_status_code():
    parsed = parse_response({"status_code": 422, "body": ""})
    assert parsed.cb_status == 422
    assert parsed.original_status is None
    assert parsed.domain_complexity is None


def test_bare_envelope():
    parsed = parse_response(
        {
            "cb_status": 200,
            "original_status": 200,
            "url": "https://example.com/",
            "domain_complexity": "standard",
            "body": json.dumps({"title": "Widget", "price": "1"}),
        }
    )
    assert parsed.cb_status == 200
    assert parsed.domain_complexity == "standard"
    assert "Widget" in parsed.body


def test_build_options_is_format_json_without_waits():
    assert build_options() == {"format": "json"}
    assert build_options(page_wait_ms=2000, ajax_wait=True, country="us") == {
        "format": "json",
        "page_wait": 2000,
        "ajax_wait": True,
        "country": "US",
    }


def test_sdk_path_is_used(monkeypatch):
    def fake_sdk(token, url, options, timeout):
        assert token == "normal-token"
        assert url == "https://example.com/"
        assert options == {"format": "json"}
        assert timeout == 90
        envelope = {
            "cb_status": 200,
            "original_status": 200,
            "url": url,
            "domain_complexity": "standard",
            "body": json.dumps({"title": "Widget", "price": "1"}),
        }
        return {"status_code": 200, "headers": {}, "body": json.dumps(envelope).encode()}

    def fail_requests(*_args, **_kwargs):
        raise AssertionError("requests fallback used")

    monkeypatch.setattr("bot_diag.client._sdk_get", fake_sdk)
    monkeypatch.setattr("bot_diag.client._requests_get", fail_requests)
    parsed = CrawlClient("normal-token", "js-token").fetch("https://example.com/")
    assert parsed.cb_status == 200
    assert parsed.domain_complexity == "standard"


def test_requests_fallback_when_sdk_missing(monkeypatch):
    def missing(*_args, **_kwargs):
        raise ImportError("no sdk")

    calls = {}

    def fake_requests(token, url, options, timeout):
        calls["token"] = token
        calls["url"] = url
        calls["options"] = dict(options)
        calls["timeout"] = timeout
        return {
            "status_code": 200,
            "headers": {
                "cb_status": "200",
                "original_status": "200",
                "url": url,
                "domain_complexity": "standard",
            },
            "body": b"<html>ok</html>",
        }

    monkeypatch.setattr("bot_diag.client._sdk_get", missing)
    monkeypatch.setattr("bot_diag.client._requests_get", fake_requests)
    parsed = CrawlClient("normal-token").fetch("https://example.com/")
    assert calls["options"]["format"] == "json"
    assert calls["token"] == "normal-token"
    assert calls["url"] == "https://example.com/"
    assert "page_wait" not in calls["options"]
    assert parsed.domain_complexity == "standard"


def test_transport_error_falls_back_and_redacts_token(monkeypatch):
    def boom(*_args, **_kwargs):
        raise TimeoutError("timed out https://api.crawlbase.com/?token=super-secret&url=https://example.com/")

    def also_boom(*_args, **_kwargs):
        raise OSError("fallback token=super-secret failed")

    monkeypatch.setattr("bot_diag.client._sdk_get", boom)
    monkeypatch.setattr("bot_diag.client._requests_get", also_boom)
    with pytest.raises(CrawlError) as caught:
        CrawlClient("super-secret").fetch("https://example.com/")
    message = str(caught.value)
    assert "super-secret" not in message
    assert "REDACTED" in message


def test_javascript_fetch_uses_js_token(monkeypatch):
    seen = {}

    def fake_sdk(token, url, options, timeout):
        del url, timeout
        seen["token"] = token
        seen["options"] = dict(options)
        return {"status_code": 200, "headers": {"cb_status": "200"}, "body": b"ok"}

    monkeypatch.setattr("bot_diag.client._sdk_get", fake_sdk)
    CrawlClient("normal", "javascript").fetch(
        "https://example.com/",
        javascript=True,
        page_wait_ms=2000,
        ajax_wait=True,
    )
    assert seen["token"] == "javascript"
    assert seen["options"]["page_wait"] == 2000
    assert seen["options"]["ajax_wait"] is True


def test_missing_javascript_token():
    with pytest.raises(MissingTokenError) as caught:
        CrawlClient("normal", None).fetch("https://example.com/", javascript=True)
    assert TOKEN_ENV not in str(caught.value) or "CRAWLBASE_JS_TOKEN" in str(caught.value)
    assert "CRAWLBASE_JS_TOKEN" in str(caught.value)


def test_env_file_loads_only_token_names(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "CRAWLBASE_TOKEN=abc\nCRAWLBASE_JS_TOKEN=def\nOTHER_SECRET=nope\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("CRAWLBASE_TOKEN", raising=False)
    monkeypatch.delenv("CRAWLBASE_JS_TOKEN", raising=False)
    monkeypatch.delenv("OTHER_SECRET", raising=False)
    monkeypatch.setattr("bot_diag.client._env_candidates", lambda: [env])
    load_env()
    assert os.environ["CRAWLBASE_TOKEN"] == "abc"
    assert os.environ["CRAWLBASE_JS_TOKEN"] == "def"
    assert "OTHER_SECRET" not in os.environ


def test_env_file_does_not_override_process(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("CRAWLBASE_TOKEN=from-file\n", encoding="utf-8")
    monkeypatch.setenv("CRAWLBASE_TOKEN", "from-env")
    monkeypatch.setattr("bot_diag.client._env_candidates", lambda: [env])
    load_env()
    assert os.environ["CRAWLBASE_TOKEN"] == "from-env"


def test_package_does_not_reference_keys_file():
    root = Path(__file__).resolve().parents[1] / "bot_diag"
    for path in root.rglob("*.py"):
        assert "keys.md" not in path.read_text(encoding="utf-8")


def test_country_must_be_two_letters():
    with pytest.raises(ValueError):
        build_options(country="usa")
