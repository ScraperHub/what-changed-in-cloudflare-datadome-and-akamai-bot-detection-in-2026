"""Command line for the diagnostic package.

From ``code/final``:

    python -m bot_diag evaluate urls.example.txt --fields price,title --dry-run
    python -m bot_diag evaluate urls.txt --fields price,title
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bot_diag.client import CrawlClient, javascript_token, normal_token
from bot_diag.evaluate import DryRunClient, evaluate_urls, format_summary, read_urls, summarize, write_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bot_diag",
        description=(
            "Classify Crawlbase responses for URLs you are authorized to collect, "
            "then measure the usable-data rate."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate = sub.add_parser(
        "evaluate",
        help="Sample a URL list and write a CSV plus usable-rate, p50/p95, and retry overhead.",
    )
    evaluate.add_argument("urls", type=Path, help="Text file with one http(s) URL per line.")
    evaluate.add_argument(
        "--fields",
        required=True,
        help="Comma-separated fields that must be present, for example price,title.",
    )
    evaluate.add_argument(
        "--out",
        type=Path,
        default=Path("sample_results.csv"),
        help="CSV path. Default: sample_results.csv in the working directory.",
    )
    evaluate.add_argument("--concurrency", type=int, default=4, help="Modest concurrency. Capped at 8.")
    evaluate.add_argument("--max-retries", type=int, default=2, help="Retries for fetch-layer failures only.")
    evaluate.add_argument("--country", default=None, help="Optional two-letter country code. Not rotated.")
    evaluate.add_argument(
        "--dry-run",
        action="store_true",
        help="Use canned responses. No token and no network.",
    )
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        return _evaluate(args)
    parser.error(f"unknown command {args.command}")
    return 2


def _evaluate(args: argparse.Namespace) -> int:
    fields = [part.strip() for part in args.fields.split(",") if part.strip()]
    if not fields:
        raise SystemExit("--fields must name at least one field, for example price,title")
    urls = read_urls(args.urls)
    if args.dry_run:
        client: object = DryRunClient()
    else:
        client = CrawlClient(normal_token(), javascript_token())
    rows = evaluate_urls(
        client,
        urls,
        fields,
        concurrency=args.concurrency,
        max_retries=args.max_retries,
        country=args.country,
        sleeper=(lambda _seconds: None) if args.dry_run else None,
    )
    write_csv(args.out, rows)
    print(format_summary(summarize(rows)))
    print(f"csv: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
