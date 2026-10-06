"""Step 3: classify synthetic responses as blocked, challenged, invalid_content, or ok."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "final"))

from bot_diag.classify import classify_response  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "final" / "tests" / "fixtures"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify local fixture pages without making network calls.")
    parser.add_argument("--dry-run", action="store_true", help="Classify the bundled fixtures.")
    parser.parse_args(argv)
    cases = [
        ("cloudflare", 403, "cloudflare_challenge.html", {"cf-mitigated": "challenge"}),
        ("datadome", 403, "datadome_challenge.html", {"x-datadome": "protected"}),
        ("akamai", 403, "akamai_block.html", {"set-cookie": "_abck=x; bm_sz=y"}),
        ("missing", 200, "missing_fields.json", {}),
        ("valid", 200, "valid_page.json", {}),
    ]
    print("dry-run")
    for name, status, fixture, headers in cases:
        body = (FIXTURES / fixture).read_text(encoding="utf-8")
        print(name, classify_response(status, body, headers, ["price", "title"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
