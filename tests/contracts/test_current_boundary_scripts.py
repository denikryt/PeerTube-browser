"""Run current shell boundary checks through pytest.

These tests keep the existing shell scripts visible in the Python regression
baseline without replacing the scripts as the project-level boundary contracts.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _run_boundary_script(relative_path: str) -> str:
    """Run one boundary script and return stdout for additional assertions."""
    result = subprocess.run(
        ["bash", relative_path],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_client_backend_does_not_depend_on_engine_internals() -> None:
    """Client backend must keep using HTTP rather than Engine imports or DB paths."""
    output = _run_boundary_script("tests/check-client-engine-boundary.sh")
    assert "PASS" in output


def test_frontend_reads_only_through_client_gateway() -> None:
    """Frontend code must not call Engine base URLs or internal routes directly."""
    output = _run_boundary_script("tests/check-frontend-client-gateway.sh")
    assert "PASS" in output
