"""Step 6: keep easy domains on Smart AI Proxy and move failing ones to the API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "final"))

from bot_diag.routing import (  # noqa: E402
    SMART_PROXY_ENDPOINT,
    record_challenge,
    route_domain,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print proxy-versus-API routing for a domain. No network calls."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print a sample challenge counter.")
    parser.add_argument("--domain", default="example.com", help="Hostname or URL to route.")
    parser.add_argument("--challenges", type=int, default=3, help="How many challenges to record.")
    args = parser.parse_args(argv)
    if args.challenges < 0:
        raise SystemExit("--challenges must be at least 0")
    counts: dict[str, int] = {}
    print("dry-run")
    print("proxy_endpoint", SMART_PROXY_ENDPOINT)
    print("before", route_domain(args.domain, counts))
    for _ in range(args.challenges):
        record_challenge(args.domain, counts)
    print("after", route_domain(args.domain, counts), f"challenges={args.challenges}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
