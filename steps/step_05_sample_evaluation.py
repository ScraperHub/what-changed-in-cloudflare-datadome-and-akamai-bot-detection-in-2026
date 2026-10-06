"""Step 5: evaluate a sample and report usable rate, latency, and retry overhead."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "final"))

from bot_diag.evaluate import DryRunClient, evaluate_urls, format_summary, read_urls, summarize, write_csv  # noqa: E402

EXAMPLE = Path(__file__).resolve().parents[1] / "final" / "urls.example.txt"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate authorized URLs with modest concurrency.")
    parser.add_argument("--dry-run", action="store_true", help="Use synthetic responses; no token or network.")
    parser.add_argument("--urls", type=Path, help="File containing one authorized URL per line.")
    parser.add_argument("--fields", default="price,title", help="Comma-separated required fields.")
    parser.add_argument("--out", type=Path, default=Path("sample_results.csv"))
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args(argv)
    fields = [field.strip() for field in args.fields.split(",") if field.strip()]
    if args.dry_run or not args.urls:
        client = DryRunClient()
    else:
        from bot_diag.client import CrawlClient, javascript_token, normal_token

        client = CrawlClient(normal_token(), javascript_token())
    rows = evaluate_urls(client, read_urls(args.urls or EXAMPLE), fields, concurrency=args.concurrency)
    write_csv(args.out, rows)
    print("dry-run" if args.dry_run or not args.urls else "live")
    print(format_summary(summarize(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
