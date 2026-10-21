"""Standalone Random builder CLI compatibility regressions."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "engine/server/db/jobs/precompute-random-index-ids.py"


def test_random_builder_help_exposes_refresh_and_not_reset() -> None:
    """Positive: the one supported force-rebuild flag is visible in the CLI contract."""
    result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "--refresh" in result.stdout
    assert "--reset" not in result.stdout


def test_random_builder_rejects_removed_reset_flag() -> None:
    """Negative: no compatibility shim silently accepts the obsolete reset flag."""
    result = subprocess.run([sys.executable, str(SCRIPT), "--reset"], capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "unrecognized arguments: --reset" in result.stderr
