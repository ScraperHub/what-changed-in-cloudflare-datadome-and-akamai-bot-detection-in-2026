"""Step 2: inspect cb_status, original_status, final URL, and domain complexity."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "final"))

from bot_diag.client import parse_response  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the fetch and target layers of a response.")
    parser.add_argument("--dry-run", action="store_true", help="Parse a synthetic response; no token or network.")
    parser.parse_args(argv)
    envelope = {
        "cb_status": 200,
        "original_status": 200,
        "url": "https://example.com/item",
        "domain_complexity": "moderate",
        "body": "<html>ok</html>",
    }
    parsed = parse_response({"status_code": 200, "headers": {}, "body": json.dumps(envelope).encode()})
    print("dry-run")
    print("cb_status", parsed.cb_status)
    print("original_status", parsed.original_status)
    print("url", parsed.final_url)
    print("domain_complexity", parsed.domain_complexity)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
