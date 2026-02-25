"""Provide reusable GitHub CLI adapter helpers for workflow commands."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

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
) -> None:
    """Require that the mapped GitHub milestone title exists before write operations."""
    command = ["gh", "api", f"repos/{repo_name_with_owner}/milestones?state=all&per_page=100"]
    output = run_checked_command(
        command,
        cwd=None,
        error_prefix=f"Failed to resolve GitHub milestones for {repo_name_with_owner}",
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
    output = run_checked_command(command, cwd=None, error_prefix="Failed to create GitHub issue")
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
    run_checked_command(command, cwd=None, error_prefix=f"Failed to update GitHub issue #{issue_number}")


def gh_issue_view_body(
    repo_name_with_owner: str,
    issue_number: int,
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
    output = run_checked_command(command, cwd=None, error_prefix=f"Failed to read GitHub issue #{issue_number}")
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
    run_checked_command(command, cwd=None, error_prefix=f"Failed to update GitHub issue body #{issue_number}")


def close_github_issue(issue_number: int) -> None:
    """Close a mapped GitHub issue through gh CLI."""
    command = ["gh", "issue", "close", str(issue_number)]
    run_checked_command(command, cwd=None, error_prefix=f"Failed to close GitHub issue #{issue_number}")


def gh_issue_list_sub_issue_numbers(
    repo_name_with_owner: str,
    parent_issue_number: int,
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
) -> None:
    """Add one child sub-issue link to a parent issue via gh api."""
    command = [
        "gh",
        "api",
        "--method",
        "POST",
        f"repos/{repo_name_with_owner}/issues/{parent_issue_number}/sub_issues",
        "-f",
        f"sub_issue_id={sub_issue_number}",
    ]
    run_checked_command(
        command,
        cwd=None,
        error_prefix=(
            f"Failed to add sub-issue #{sub_issue_number} to GitHub issue #{parent_issue_number}"
        ),
    )


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
