"""Step 4: map documented Crawlbase statuses to bounded actions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "final"))

from bot_diag.escalation import known_statuses, plan_action, should_retry  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the status-to-action policy without making network calls.")
    parser.add_argument("--dry-run", action="store_true", help="Print the policy table.")
    parser.parse_args(argv)
    print("dry-run")
    for status in known_statuses():
        plan = plan_action(status, "invalid_content", javascript=False)
        print(status, plan.code, f"retry={plan.retry}", f"javascript={plan.escalate_javascript}")
    print("confirmed_block", should_retry(599, "blocked"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
