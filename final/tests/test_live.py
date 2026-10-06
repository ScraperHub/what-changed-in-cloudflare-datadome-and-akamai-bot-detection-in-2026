import os
from urllib.parse import urlsplit

import pytest

from bot_diag.client import CrawlClient


@pytest.mark.live
def test_live_example_com():
    token = os.environ.get("CRAWLBASE_TOKEN", "").strip()
    url = os.environ.get("BOT_DIAG_LIVE_URL", "https://example.com/")
    host = urlsplit(url).hostname
    if not token or host != "example.com":
        pytest.skip("CRAWLBASE_TOKEN and an example.com URL are required")
    parsed = CrawlClient(token, os.environ.get("CRAWLBASE_JS_TOKEN")).fetch(url)
    assert parsed.cb_status is not None
    assert parsed.final_url is None or "example.com" in parsed.final_url
