"""Provide reusable GitHub CLI adapter helpers for workflow commands."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .errors import WorkflowCommandError


TRANSIENT_ERROR_PATTERNS = (
    "error connecting to api.github.com",
    "timed out",
    "timeout",
    "connection reset",
    "temporary failure",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "tls handshake",
    "api rate limit exceeded",
    "secondary rate limit",
)


def run_checked_command(
    command: list[str],
    cwd: Path | None,
    error_prefix: str,
    *,
    max_retries: int = 0,
    retry_pause_seconds: float = 0.0,
    timeout_seconds: float | None = None,
) -> str:
    """Run one subprocess command with optional retry policy and return stdout."""
    if max_retries < 0:
        raise WorkflowCommandError(
            f"{error_prefix}: invalid retry policy max_retries={max_retries}; expected >= 0.",
            exit_code=4,
        )
    if retry_pause_seconds < 0:
        raise WorkflowCommandError(
            f"{error_prefix}: invalid retry policy retry_pause_seconds={retry_pause_seconds}; expected >= 0.",
            exit_code=4,
        )
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise WorkflowCommandError(
            f"{error_prefix}: invalid timeout_seconds={timeout_seconds}; expected > 0.",
            exit_code=4,
        )

    attempt = 0
    while True:
        timed_out = False
        timeout_details = ""
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                cwd=str(cwd) if cwd is not None else None,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            timeout_details = (
                f"command timed out after {timeout_seconds:.1f}s"
                if timeout_seconds is not None
                else "command timed out"
            )
            result = None

        if not timed_out and result is not None and result.returncode == 0:
            return result.stdout.strip()

        if timed_out or result is None:
            details = timeout_details
        else:
            details = (result.stderr or result.stdout).strip() or "unknown command error"

        is_transient = timed_out or _is_transient_command_error(details)
        if attempt >= max_retries or not is_transient:
            raise WorkflowCommandError(f"{error_prefix}: {details}", exit_code=5)

        attempt += 1
        if retry_pause_seconds > 0:
            time.sleep(retry_pause_seconds)


def resolve_github_repository(root_dir: Path) -> dict[str, str]:
    """Resolve GitHub repository metadata from gh CLI context."""
    command = ["gh", "repo", "view", "--json", "nameWithOwner,url"]
    output = run_checked_command(command, cwd=root_dir, error_prefix="Failed to resolve GitHub repository")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise WorkflowCommandError(f"Invalid JSON from gh repo view: {error}", exit_code=5) from error
    name_with_owner = str(payload.get("nameWithOwner", "")).strip()
    url = str(payload.get("url", "")).strip()
    if not name_with_owner:
        raise WorkflowCommandError("gh repo view did not return nameWithOwner.", exit_code=5)
    return {"name_with_owner": name_with_owner, "url": url}


def ensure_github_milestone_exists(
    repo_name_with_owner: str,
    milestone_title: str,
    milestone_id: str,
    *,
    max_retries: int = 0,
    retry_pause_seconds: float = 0.0,
    timeout_seconds: float | None = None,
) -> None:
    """Require that the mapped GitHub milestone title exists before write operations."""
    command = ["gh", "api", f"repos/{repo_name_with_owner}/milestones?state=all&per_page=100"]
    output = run_checked_command(
        command,
        cwd=None,
        error_prefix=f"Failed to resolve GitHub milestones for {repo_name_with_owner}",
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        timeout_seconds=timeout_seconds,
    )
    try:
        milestones = json.loads(output)
    except json.JSONDecodeError as error:
        raise WorkflowCommandError(f"Invalid milestones payload from gh api: {error}", exit_code=5) from error
    if not isinstance(milestones, list):
        raise WorkflowCommandError("Unexpected milestones payload format from gh api.", exit_code=5)
    for milestone in milestones:
        if str(milestone.get("title", "")).strip() == milestone_title:
            return
    raise WorkflowCommandError(
        f"GitHub milestone title {milestone_title!r} (from {milestone_id}) was not found for {repo_name_with_owner}; "
        "create/select it before materialize.",
        exit_code=4,
    )


def gh_issue_create(
    repo_name_with_owner: str,
    title: str,
    body: str,
    milestone_title: str,
    *,
    max_retries: int = 0,
    retry_pause_seconds: float = 0.0,
    timeout_seconds: float | None = None,
) -> str:
    """Create a GitHub issue and return the created issue URL."""
    command = [
        "gh",
        "issue",
        "create",
        "--repo",
        repo_name_with_owner,
        "--title",
        title,
        "--body",
        body,
        "--milestone",
        milestone_title,
    ]
    output = run_checked_command(
        command,
        cwd=None,
        error_prefix="Failed to create GitHub issue",
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        timeout_seconds=timeout_seconds,
    )
    created_url = output.strip().splitlines()[-1].strip() if output.strip() else ""
    if not created_url:
        raise WorkflowCommandError("gh issue create returned empty output.", exit_code=5)
    return created_url


def gh_issue_edit(
    repo_name_with_owner: str,
    issue_number: int,
    title: str,
    body: str,
    milestone_title: str,
    *,
    max_retries: int = 0,
    retry_pause_seconds: float = 0.0,
    timeout_seconds: float | None = None,
) -> None:
    """Update an existing GitHub issue title/body/milestone."""
    command = [
        "gh",
        "issue",
        "edit",
        str(issue_number),
        "--repo",
        repo_name_with_owner,
        "--title",
        title,
        "--body",
        body,
        "--milestone",
        milestone_title,
    ]
    run_checked_command(
        command,
        cwd=None,
        error_prefix=f"Failed to update GitHub issue #{issue_number}",
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        timeout_seconds=timeout_seconds,
    )


def gh_issue_view_body(
    repo_name_with_owner: str,
    issue_number: int,
    *,
    max_retries: int = 0,
    retry_pause_seconds: float = 0.0,
    timeout_seconds: float | None = None,
) -> str:
    """Read one GitHub issue body text via gh CLI."""
    command = [
        "gh",
        "issue",
        "view",
        str(issue_number),
        "--repo",
        repo_name_with_owner,
        "--json",
        "body",
    ]
    output = run_checked_command(
        command,
        cwd=None,
        error_prefix=f"Failed to read GitHub issue #{issue_number}",
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        timeout_seconds=timeout_seconds,
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise WorkflowCommandError(f"Invalid JSON from gh issue view #{issue_number}: {error}", exit_code=5) from error
    if not isinstance(payload, dict):
        raise WorkflowCommandError(f"Unexpected gh issue view payload for #{issue_number}.", exit_code=5)
    return str(payload.get("body", ""))


def gh_issue_edit_body(
    repo_name_with_owner: str,
    issue_number: int,
    body: str,
    *,
    max_retries: int = 0,
    retry_pause_seconds: float = 0.0,
    timeout_seconds: float | None = None,
) -> None:
    """Update only issue body text for one GitHub issue."""
    command = [
        "gh",
        "issue",
        "edit",
        str(issue_number),
        "--repo",
        repo_name_with_owner,
        "--body",
        body,
    ]
    run_checked_command(
        command,
        cwd=None,
        error_prefix=f"Failed to update GitHub issue body #{issue_number}",
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        timeout_seconds=timeout_seconds,
    )


def gh_issue_get_id(
    repo_name_with_owner: str,
    issue_number: int,
    *,
    max_retries: int = 0,
    retry_pause_seconds: float = 0.0,
    timeout_seconds: float | None = None,
) -> int:
    """Resolve numeric GitHub issue database ID for one issue number."""
    command = [
        "gh",
        "api",
        f"repos/{repo_name_with_owner}/issues/{issue_number}",
    ]
    output = run_checked_command(
        command,
        cwd=None,
        error_prefix=f"Failed to resolve GitHub issue ID for issue #{issue_number}",
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        timeout_seconds=timeout_seconds,
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise WorkflowCommandError(
            f"Invalid issue payload for GitHub issue #{issue_number}: {error}",
            exit_code=5,
        ) from error
    if not isinstance(payload, dict):
        raise WorkflowCommandError(
            f"Unexpected issue payload type while resolving GitHub issue #{issue_number}.",
            exit_code=5,
        )
    raw_id = payload.get("id")
    if isinstance(raw_id, int):
        return raw_id
    raw_id_text = str(raw_id or "").strip()
    if raw_id_text.isdigit():
        return int(raw_id_text)
    raise WorkflowCommandError(
        f"GitHub issue #{issue_number} payload is missing numeric id field.",
        exit_code=5,
    )


def close_github_issue(
    issue_number: int,
    *,
    max_retries: int = 0,
    retry_pause_seconds: float = 0.0,
    timeout_seconds: float | None = None,
) -> None:
    """Close a mapped GitHub issue through gh CLI."""
    command = ["gh", "issue", "close", str(issue_number)]
    run_checked_command(
        command,
        cwd=None,
        error_prefix=f"Failed to close GitHub issue #{issue_number}",
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        timeout_seconds=timeout_seconds,
    )


def gh_issue_list_sub_issue_numbers(
    repo_name_with_owner: str,
    parent_issue_number: int,
    *,
    max_retries: int = 0,
    retry_pause_seconds: float = 0.0,
    timeout_seconds: float | None = None,
) -> list[int]:
    """List child sub-issue numbers for one parent issue via gh api."""
    command = [
        "gh",
        "api",
        f"repos/{repo_name_with_owner}/issues/{parent_issue_number}/sub_issues?per_page=100",
    ]
    output = run_checked_command(
        command,
        cwd=None,
        error_prefix=f"Failed to list sub-issues for GitHub issue #{parent_issue_number}",
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        timeout_seconds=timeout_seconds,
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise WorkflowCommandError(
            f"Invalid sub-issues payload for GitHub issue #{parent_issue_number}: {error}",
            exit_code=5,
        ) from error
    return _extract_sub_issue_numbers(payload=payload, parent_issue_number=parent_issue_number)


def gh_issue_add_sub_issue(
    repo_name_with_owner: str,
    parent_issue_number: int,
    sub_issue_number: int,
    *,
    max_retries: int = 0,
    retry_pause_seconds: float = 0.0,
    timeout_seconds: float | None = None,
) -> None:
    """Add one child sub-issue link to a parent issue via gh api."""
    sub_issue_id = gh_issue_get_id(
        repo_name_with_owner=repo_name_with_owner,
        issue_number=sub_issue_number,
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        timeout_seconds=timeout_seconds,
    )
    command = [
        "gh",
        "api",
        "--method",
        "POST",
        f"repos/{repo_name_with_owner}/issues/{parent_issue_number}/sub_issues",
        "-F",
        f"sub_issue_id={sub_issue_id}",
    ]
    run_checked_command(
        command,
        cwd=None,
        error_prefix=(
            f"Failed to add sub-issue #{sub_issue_number} to GitHub issue #{parent_issue_number}"
        ),
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        timeout_seconds=timeout_seconds,
    )


def _is_transient_command_error(message: str) -> bool:
    """Return whether gh CLI error text matches transient network/rate-limit classes."""
    normalized = message.lower()
    return any(pattern in normalized for pattern in TRANSIENT_ERROR_PATTERNS)


def _extract_sub_issue_numbers(payload: Any, parent_issue_number: int) -> list[int]:
    """Extract child sub-issue numbers from supported gh api payload shapes."""
    raw_items: Any
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("sub_issues"), list):
            raw_items = payload.get("sub_issues")
        elif isinstance(payload.get("items"), list):
            raw_items = payload.get("items")
        elif isinstance(payload.get("nodes"), list):
            raw_items = payload.get("nodes")
        else:
            raise WorkflowCommandError(
                "Unsupported sub-issues payload shape for "
                f"GitHub issue #{parent_issue_number}: expected list or object with sub_issues/items/nodes.",
                exit_code=5,
            )
    else:
        raise WorkflowCommandError(
            f"Unsupported sub-issues payload type for GitHub issue #{parent_issue_number}.",
            exit_code=5,
        )

    numbers: list[int] = []
    seen: set[int] = set()
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise WorkflowCommandError(
                f"Unsupported sub-issues payload item at index {index} for GitHub issue #{parent_issue_number}.",
                exit_code=5,
            )
        raw_number = item.get("number")
        if not isinstance(raw_number, int):
            number_text = str(raw_number or "").strip()
            if not number_text.isdigit():
                raise WorkflowCommandError(
                    "Unsupported sub-issues payload item at index "
                    f"{index} for GitHub issue #{parent_issue_number}: missing numeric number field.",
                    exit_code=5,
                )
            raw_number = int(number_text)
        if raw_number in seen:
            continue
        seen.add(raw_number)
        numbers.append(raw_number)
    return numbers
