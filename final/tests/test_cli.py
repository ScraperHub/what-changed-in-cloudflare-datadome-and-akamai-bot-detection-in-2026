import csv
import os
from pathlib import Path

import pytest

from bot_diag.__main__ import main
from bot_diag.classify import LABELS


def test_help_exits_without_token(monkeypatch):
    monkeypatch.delenv("CRAWLBASE_TOKEN", raising=False)
    monkeypatch.delenv("CRAWLBASE_JS_TOKEN", raising=False)
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0


def test_evaluate_dry_run_writes_csv(tmp_path, monkeypatch):
    monkeypatch.delenv("CRAWLBASE_TOKEN", raising=False)
    monkeypatch.delenv("CRAWLBASE_JS_TOKEN", raising=False)
    monkeypatch.setattr(
        "bot_diag.client._sdk_get",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")),
    )
    monkeypatch.setattr(
        "bot_diag.client._requests_get",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")),
    )
    urls = tmp_path / "urls.txt"
    urls.write_text(
        "\n".join(
            [
                "# comment",
                "https://example.com/",
                "https://example.com/pricing",
                "https://example.com/docs",
                "https://example.com/products/widget",
            ]
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.csv"
    code = main(
        [
            "evaluate",
            str(urls),
            "--fields",
            "price,title",
            "--dry-run",
            "--out",
            str(out),
            "--concurrency",
            "4",
        ]
    )
    assert code == 0
    assert "CRAWLBASE_TOKEN" not in os.environ or os.environ.get("CRAWLBASE_TOKEN", "") == ""
    with out.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert {row["classification"] for row in rows} <= set(LABELS)


def test_evaluate_help():
    with pytest.raises(SystemExit) as caught:
        main(["evaluate", "--help"])
    assert caught.value.code == 0


def test_package_invocation_path_exists():
    package = Path(__file__).resolve().parents[1] / "bot_diag" / "__main__.py"
    assert package.is_file()
