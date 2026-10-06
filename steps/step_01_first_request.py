"""Step 1: make one Crawling API request with the normal token and format=json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "final"))

from bot_diag.client import CrawlClient, build_options, javascript_token, normal_token, parse_response  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make one Crawling API request for an authorized URL.")
    parser.add_argument("--dry-run", action="store_true", help="Print a synthetic response; no token or network.")
    parser.add_argument("--url", help="HTTPS URL you are authorized to collect.")
    args = parser.parse_args(argv)
    if args.dry_run or not args.url:
        envelope = {
            "cb_status": 200,
            "original_status": 200,
            "url": "https://example.com/",
            "domain_complexity": "standard",
            "body": json.dumps({"title": "Example Domain"}),
        }
        parsed = parse_response({"status_code": 200, "headers": {}, "body": json.dumps(envelope).encode()})
        print("dry-run", build_options())
    else:
        parsed = CrawlClient(normal_token(), javascript_token()).fetch(args.url)
    print("cb_status", parsed.cb_status)
    print("original_status", parsed.original_status)
    print("url", parsed.final_url)
    print("domain_complexity", parsed.domain_complexity)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
