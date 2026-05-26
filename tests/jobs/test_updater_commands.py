"""Characterization tests for updater command helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from engine.server.db.jobs.updater.commands import _to_cpu_cmd, run_with_cpu_fallback, systemctl_cmd


def test_to_cpu_cmd_removes_gpu_flags_and_appends_cpu() -> None:
    """GPU fallback must preserve arguments while removing GPU-only switches."""

    assert _to_cpu_cmd(["python", "job.py", "--gpu", "--gpu-device", "0", "--x", "1"]) == [
        "python",
        "job.py",
        "--x",
        "1",
        "--cpu",
    ]


def test_run_with_cpu_fallback_runs_cpu_command_once_without_gpu() -> None:
    """CPU commands do not run through fallback retry behavior."""

    seen: list[list[str]] = []

    def runner(cmd, cwd: Path | None) -> None:
        seen.append(list(cmd))

    run_with_cpu_fallback(["python", "job.py", "--cpu"], stage="job", runner=runner)
    assert seen == [["python", "job.py", "--cpu"]]


def test_run_with_cpu_fallback_retries_failed_gpu_as_cpu() -> None:
    """A failing GPU command retries once with the current CPU command shape."""

    seen: list[list[str]] = []

    def runner(cmd, cwd: Path | None) -> None:
        seen.append(list(cmd))
        if "--gpu" in cmd:
            raise subprocess.CalledProcessError(1, list(cmd))

    run_with_cpu_fallback(["python", "job.py", "--gpu"], stage="job", runner=runner)
    assert seen == [["python", "job.py", "--gpu"], ["python", "job.py", "--cpu"]]


@pytest.mark.parametrize(
    ("use_sudo", "expected"),
    [
        (False, ["systemctl", "stop", "svc"]),
        (True, ["sudo", "-n", "systemctl", "stop", "svc"]),
    ],
)
def test_systemctl_cmd_preserves_sudo_prefix(use_sudo: bool, expected: list[str]) -> None:
    """Systemctl command construction keeps current sudo behavior."""

    assert (
        systemctl_cmd(
            systemctl_bin="systemctl", service_name="svc", action="stop", use_sudo=use_sudo
        )
        == expected
    )
