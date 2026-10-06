import os
import subprocess
import sys
from pathlib import Path

import pytest

CODE = Path(__file__).resolve().parents[2]
STEPS = [
    CODE / "steps" / "step_01_first_request.py",
    CODE / "steps" / "step_02_inspect_response.py",
    CODE / "steps" / "step_03_classify_response.py",
    CODE / "steps" / "step_04_escalate_on_failure.py",
    CODE / "steps" / "step_05_sample_evaluation.py",
]


def _env():
    env = os.environ.copy()
    env.pop("CRAWLBASE_TOKEN", None)
    env.pop("CRAWLBASE_JS_TOKEN", None)
    env["PYTHONPATH"] = str(CODE / "final")
    return env


@pytest.mark.parametrize("script", STEPS, ids=lambda path: path.stem)
def test_step_help(script):
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=CODE,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()


@pytest.mark.parametrize("script", STEPS, ids=lambda path: path.stem)
def test_step_dry_run(script, tmp_path):
    command = [sys.executable, str(script), "--dry-run"]
    if script.stem == "step_05_sample_evaluation":
        command.extend(["--out", str(tmp_path / "sample.csv")])
    result = subprocess.run(
        command,
        cwd=CODE,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "dry-run" in result.stdout
    if script.stem == "step_03_classify_response":
        for label in ("challenged", "blocked", "invalid_content", "ok"):
            assert label in result.stdout
    if script.stem == "step_04_escalate_on_failure":
        for status in ("422", "520", "521", "522", "523", "525", "595", "599"):
            assert status in result.stdout
        assert "confirmed_block" in result.stdout
    if script.stem == "step_05_sample_evaluation":
        assert "usable_rate" in result.stdout
        assert "p50_ms" in result.stdout
        assert "p95_ms" in result.stdout
        assert "retry_overhead" in result.stdout
        assert (tmp_path / "sample.csv").is_file()
