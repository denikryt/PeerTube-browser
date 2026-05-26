"""Command execution helpers for the updater pipeline.

The module keeps subprocess behavior, logging, GPU-to-CPU fallback, and systemctl
command construction compatible with the historical updater worker.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

CommandRun = Callable[[Sequence[str], Path | None], None]


def _default_subprocess_runner(cmd: Sequence[str], cwd: Path | None) -> None:
    """Run a command with the current updater subprocess semantics."""

    subprocess.run(list(cmd), cwd=cwd, check=True)


def run_cmd(cmd: list[str], *, cwd: Path | None = None, runner: CommandRun | None = None) -> None:
    """Run a command, logging command text and elapsed time as before."""

    logging.info("run: %s", " ".join(shlex.quote(part) for part in cmd))
    start = time.monotonic()
    (runner or _default_subprocess_runner)(cmd, cwd)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logging.info("done: %s (%dms)", cmd[0], elapsed_ms)


def _to_cpu_cmd(cmd: list[str]) -> list[str]:
    """Return the current CPU fallback command for a GPU command."""

    out: list[str] = []
    skip_next = False
    for part in cmd:
        if skip_next:
            skip_next = False
            continue
        if part == "--gpu":
            continue
        if part == "--gpu-device":
            skip_next = True
            continue
        out.append(part)
    if "--cpu" not in out:
        out.append("--cpu")
    return out


def run_with_cpu_fallback(
    cmd: list[str], *, stage: str, cwd: Path | None = None, runner: CommandRun | None = None
) -> None:
    """Run a command and retry once as CPU when the current GPU command fails."""

    if "--gpu" not in cmd:
        run_cmd(cmd, cwd=cwd, runner=runner)
        return
    try:
        run_cmd(cmd, cwd=cwd, runner=runner)
    except subprocess.CalledProcessError:
        cpu_cmd = _to_cpu_cmd(cmd)
        logging.warning("%s GPU failed; retrying CPU: %s", stage, cpu_cmd)
        run_cmd(cpu_cmd, cwd=cwd, runner=runner)


def systemctl_cmd(
    *, systemctl_bin: str, service_name: str, action: str, use_sudo: bool
) -> list[str]:
    """Build the current systemctl command with optional non-interactive sudo."""

    cmd = [systemctl_bin, action, service_name]
    if use_sudo:
        return ["sudo", "-n", *cmd]
    return cmd
