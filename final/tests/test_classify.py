from pathlib import Path

import pytest

from bot_diag.classify import LABELS, classify_response

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIELDS = ["price", "title"]


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_cloudflare_challenge():
    label = classify_response(
        403,
        _text("cloudflare_challenge.html"),
        {"cf-mitigated": "challenge", "cf-ray": "8abc123-SJC"},
        FIELDS,
    )
    assert label == "challenged"


def test_datadome_challenge():
    label = classify_response(
        403,
        _text("datadome_challenge.html"),
        {"x-datadome": "protected", "set-cookie": "datadome=abc"},
        FIELDS,
    )
    assert label == "challenged"


def test_akamai_block():
    label = classify_response(
        403,
        _text("akamai_block.html"),
        {"set-cookie": "_abck=abc; bm_sz=xyz"},
        FIELDS,
    )
    assert label == "blocked"


def test_akamai_reference_page_is_blocked_without_a_403():
    assert classify_response(200, _text("akamai_block.html"), None, FIELDS) == "blocked"


def test_missing_fields_on_200():
    label = classify_response(200, _text("missing_fields.json"), None, FIELDS)
    assert label == "invalid_content"


def test_valid_page():
    label = classify_response(200, _text("valid_page.json"), None, FIELDS)
    assert label == "ok"


def test_fixture_labels_are_the_four_outcomes():
    labels = {
        "challenged",
        "challenged",
        "blocked",
        "invalid_content",
        "ok",
    }
    assert labels <= set(LABELS)
    assert set(LABELS) == {"blocked", "challenged", "invalid_content", "ok"}


def test_challenge_wins_over_missing_fields_and_403():
    assert classify_response(403, _text("cloudflare_challenge.html"), None, FIELDS) == "challenged"


def test_akamai_cookies_on_a_valid_page_are_ok():
    body = _text("valid_page.json")
    assert classify_response(200, body, {"set-cookie": "_abck=1; bm_sz=2"}, FIELDS) == "ok"


def test_cf_ray_alone_is_not_a_block():
    assert classify_response(200, _text("valid_page.json"), {"cf-ray": "abc"}, FIELDS) == "ok"


def test_bare_503_is_not_a_confirmed_block():
    assert classify_response(503, "upstream unavailable", None, FIELDS) == "invalid_content"


def test_html_attributes_satisfy_fields():
    body = '<html><h1 id="title">Widget</h1><span itemprop="price">12.00</span></html>'
    assert classify_response(200, body, None, FIELDS) == "ok"


def test_blank_price_is_invalid_content():
    assert classify_response(200, '{"title": "Widget", "price": ""}', None, FIELDS) == "invalid_content"


@pytest.mark.parametrize("status", [401, 403, 429])
def test_explicit_block_statuses(status):
    assert classify_response(status, "nope", None, FIELDS) == "blocked"


def test_blank_body_is_not_a_confirmed_block():
    assert classify_response(403, "  ", None, FIELDS) == "invalid_content"
