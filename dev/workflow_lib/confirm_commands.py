"""Register and execute confirm command routing for workflow CLI."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from typing import Any

from .context import WorkflowContext
from .errors import WorkflowCommandError
from .output import emit_json
from .placeholders import run_not_implemented


def register_confirm_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register confirm router with completion target subcommands."""
    confirm_parser = subparsers.add_parser(
        "confirm",
        help="Completion confirmation workflow commands.",
    )
    confirm_subparsers = confirm_parser.add_subparsers(dest="confirm_target", required=True)

    _register_confirm_target(confirm_subparsers, "task", "Confirm one task completion.")
    _register_confirm_target(confirm_subparsers, "issue", "Confirm one issue completion.")
    _register_confirm_target(confirm_subparsers, "feature", "Confirm one feature completion.")
    _register_confirm_target(
        confirm_subparsers,
        "standalone-issue",
        "Confirm one standalone issue completion.",
    )


def _register_confirm_target(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    target: str,
    help_text: str,
) -> None:
    """Register a single confirm target parser."""
    parser = subparsers.add_parser(target, help=help_text)
    parser.add_argument("--id", required=True, help=f"{target} identifier.")
    parser.add_argument("state", choices=["done"], help="Confirmation state keyword.")
    parser.add_argument("--write", action="store_true", help="Persist completion updates.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip interactive extra confirmation for pending child tasks.",
    )
    parser.add_argument(
        "--close-github",
        dest="close_github",
        action="store_true",
        default=True,
        help="Close mapped GitHub issue in the same run.",
    )
    parser.add_argument(
        "--no-close-github",
        dest="close_github",
        action="store_false",
        help="Skip GitHub issue closing.",
    )
    parser.set_defaults(handler=_handle_confirm)


def _handle_confirm(args: Namespace, context: WorkflowContext) -> int:
    """Dispatch confirm command by target type."""
    if args.confirm_target == "issue":
        return _handle_confirm_issue_done(args, context)
    command_name = f"confirm.{args.confirm_target}"
    return run_not_implemented(command_name, args, context)


def _handle_confirm_issue_done(args: Namespace, context: WorkflowContext) -> int:
    """Confirm issue completion with optional child-task cascade."""
    issue_id = str(args.id).strip().upper()
    dev_map = _load_json(context.dev_map_path)
    issue_ref = _find_issue(dev_map, issue_id)
    if issue_ref is None:
        raise WorkflowCommandError(f"Issue {issue_id} not found in DEV_MAP.", exit_code=4)

    issue_node = issue_ref["issue"]
    child_tasks = issue_node.get("tasks", [])
    pending_child_ids = [str(task.get("id", "")) for task in child_tasks if str(task.get("status", "")) != "Done"]
    needs_extra_confirmation = bool(pending_child_ids)
    if needs_extra_confirmation and not bool(args.force):
        if not _ask_pending_tasks_confirmation(issue_id, pending_child_ids):
            raise WorkflowCommandError(
                f"Confirmation cancelled for {issue_id}; pending child tasks were not accepted for cascade.",
                exit_code=4,
            )

    github_issue_number = issue_node.get("gh_issue_number")
    github_issue_url = issue_node.get("gh_issue_url")
    if bool(args.close_github) and (github_issue_number is None or not github_issue_url):
        raise WorkflowCommandError(
            f"Issue {issue_id} has no mapped GitHub issue metadata (gh_issue_number/gh_issue_url).",
            exit_code=4,
        )

    github_closed = False
    if bool(args.write):
        for task in child_tasks:
            task["status"] = "Done"
        issue_node["status"] = "Done"
        _touch_updated_at(dev_map)
        _write_json(context.dev_map_path, dev_map)
        if bool(args.close_github):
            _close_github_issue(int(github_issue_number))
            github_closed = True

    emit_json(
        {
            "child_tasks_marked_done": len(pending_child_ids) if bool(args.write) else 0,
            "close_github": bool(args.close_github),
            "command": "confirm.issue",
            "extra_confirmation_required": needs_extra_confirmation,
            "github_closed": github_closed,
            "issue_id": issue_id,
            "issue_status_after": "Done" if bool(args.write) else str(issue_node.get("status", "")),
            "pending_child_tasks": pending_child_ids,
            "write": bool(args.write),
        }
    )
    return 0


def _ask_pending_tasks_confirmation(issue_id: str, pending_child_ids: list[str]) -> bool:
    """Ask for explicit user confirmation before cascading pending child tasks."""
    if not sys.stdin.isatty():
        ids_csv = ", ".join(pending_child_ids)
        raise WorkflowCommandError(
            f"Issue {issue_id} has pending child tasks ({ids_csv}); rerun with --force in non-interactive mode.",
            exit_code=4,
        )
    ids_csv = ", ".join(pending_child_ids)
    prompt = f"Issue {issue_id} has pending child tasks ({ids_csv}). Mark them Done and continue? [y/N]: "
    answer = input(prompt).strip().lower()
    return answer in {"y", "yes"}


def _close_github_issue(issue_number: int) -> None:
    """Close mapped GitHub issue through gh CLI."""
    command = ["gh", "issue", "close", str(issue_number)]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip() or "unknown gh error"
        raise WorkflowCommandError(f"Failed to close GitHub issue #{issue_number}: {message}", exit_code=5)


def _load_json(path: Path) -> dict[str, Any]:
    """Read JSON document from path."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise WorkflowCommandError(f"Required file not found: {path}", exit_code=4) from error
    except json.JSONDecodeError as error:
        raise WorkflowCommandError(f"Invalid JSON in {path}: {error}", exit_code=4) from error


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist JSON document using deterministic formatting."""
    path.write_text(f"{json.dumps(payload, indent=2, ensure_ascii=False)}\n", encoding="utf-8")


def _touch_updated_at(dev_map: dict[str, Any]) -> None:
    """Update map-level timestamp to local ISO-8601 representation."""
    dev_map["updated_at"] = datetime.now().astimezone().replace(microsecond=0).isoformat()


def _find_issue(dev_map: dict[str, Any], issue_id: str) -> dict[str, Any] | None:
    """Find issue node and parent metadata by issue ID."""
    for milestone in dev_map.get("milestones", []):
        for feature in milestone.get("features", []):
            for issue in feature.get("issues", []):
                if str(issue.get("id", "")).upper() == issue_id:
                    return {
                        "feature": feature,
                        "issue": issue,
                        "milestone": milestone,
                    }
    return None
