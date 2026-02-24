"""Provide reusable Git branch adapter helpers for workflow commands."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import WorkflowCommandError


def run_checked_command(command: list[str], cwd: Path | None, error_prefix: str) -> str:
    """Run one subprocess command and return stdout or raise a workflow error."""
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd is not None else None,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip() or "unknown command error"
        raise WorkflowCommandError(f"{error_prefix}: {details}", exit_code=5)
    return result.stdout.strip()


def checkout_canonical_feature_branch(root_dir: Path, branch_name: str) -> str:
    """Resolve and checkout canonical feature branch using local/remote precedence."""
    if git_ref_exists(root_dir, f"refs/heads/{branch_name}"):
        run_checked_command(
            ["git", "checkout", branch_name],
            cwd=root_dir,
            error_prefix=f"Failed to checkout existing branch {branch_name}",
        )
        return "checked-out-local"

    remote_ref = f"refs/remotes/origin/{branch_name}"
    if git_ref_exists(root_dir, remote_ref):
        run_checked_command(
            ["git", "checkout", "-b", branch_name, "--track", f"origin/{branch_name}"],
            cwd=root_dir,
            error_prefix=f"Failed to create tracking branch from origin/{branch_name}",
        )
        return "created-tracking-from-local-remote-ref"

    remote_heads = run_checked_command(
        ["git", "ls-remote", "--heads", "origin", branch_name],
        cwd=root_dir,
        error_prefix="Failed to query remote branch heads",
    )
    if remote_heads:
        run_checked_command(
            ["git", "checkout", "-b", branch_name, "--track", f"origin/{branch_name}"],
            cwd=root_dir,
            error_prefix=f"Failed to create tracking branch from origin/{branch_name}",
        )
        return "created-tracking-from-remote"

    run_checked_command(
        ["git", "checkout", "-b", branch_name],
        cwd=root_dir,
        error_prefix=f"Failed to create branch {branch_name}",
    )
    return "created-local"


def plan_canonical_feature_branch(root_dir: Path, branch_name: str) -> str:
    """Plan canonical branch action without mutating repository state."""
    if git_ref_exists(root_dir, f"refs/heads/{branch_name}"):
        return "would-checkout-local"
    if git_ref_exists(root_dir, f"refs/remotes/origin/{branch_name}"):
        return "would-create-tracking-from-local-remote-ref"
    return "would-create-local"


def git_ref_exists(root_dir: Path, ref_name: str) -> bool:
    """Check whether a git ref exists locally."""
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref_name],
        check=False,
        cwd=str(root_dir),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0
