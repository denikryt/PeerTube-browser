"""Register and execute task command routing for workflow CLI."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from argparse import Namespace
from pathlib import Path
from typing import Any

from .context import WorkflowContext
from .errors import WorkflowCommandError
from .output import emit_json
from .tracker_store import load_task_list_payload


TASK_ID_PATTERN = re.compile(r"^[0-9]+[a-z]?$")


def register_task_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register task router with preflight/validate subcommands."""
    task_parser = subparsers.add_parser(
        "task",
        help="Task-level workflow commands.",
    )
    task_subparsers = task_parser.add_subparsers(dest="task_command", required=True)

    preflight_parser = task_subparsers.add_parser(
        "preflight",
        help="Run task preflight checks before implementation.",
    )
    preflight_parser.add_argument("--id", required=True, help="Task ID.")
    preflight_parser.set_defaults(handler=_handle_task_preflight)

    validate_parser = task_subparsers.add_parser(
        "validate",
        help="Run task validation checks after implementation.",
    )
    validate_parser.add_argument("--id", required=True, help="Task ID.")
    validate_parser.add_argument("--run-checks", action="store_true", help="Run checks for changed paths.")
    validate_parser.set_defaults(handler=_handle_task_validate)


def _handle_task_preflight(args: Namespace, context: WorkflowContext) -> int:
    """Run deterministic task preflight checks before implementation starts."""
    task_id = _normalize_task_id(args.id)
    dev_map = _load_json(context.dev_map_path)
    task_ref = _find_task(dev_map, task_id)
    if task_ref is None:
        raise WorkflowCommandError(f"Task {task_id} not found in DEV_MAP.", exit_code=4)

    task_node = task_ref["task"]
    task_status = str(task_node.get("status", ""))
    if task_status == "Done":
        raise WorkflowCommandError(
            f"Task {task_id} is already Done; execute flow supports pending tasks only.",
            exit_code=4,
        )

    parent_node = task_ref["parent"]
    parent_issue_number = parent_node.get("gh_issue_number")
    parent_issue_url = str(parent_node.get("gh_issue_url", "")).strip()
    if parent_issue_number is None or not parent_issue_url:
        raise WorkflowCommandError(
            f"Task {task_id} parent {task_ref['parent_id']} has no materialization metadata "
            "(gh_issue_number/gh_issue_url).",
            exit_code=4,
        )

    task_list_present = _task_exists_in_task_list(context, task_id)
    if not task_list_present:
        raise WorkflowCommandError(
            f"Task {task_id} is missing in TASK_LIST headings; sync issues to task list before execute.",
            exit_code=4,
        )

    emit_json(
        {
            "command": "task.preflight",
            "feature_id": task_ref.get("feature_id"),
            "materialization_gate_passed": True,
            "parent_id": task_ref["parent_id"],
            "parent_type": task_ref["parent_type"],
            "task_id": task_id,
            "task_list_present": task_list_present,
            "task_status": task_status,
        }
    )
    return 0


def _handle_task_validate(args: Namespace, context: WorkflowContext) -> int:
    """Run deterministic task validation checks after implementation work."""
    task_id = _normalize_task_id(args.id)
    dev_map = _load_json(context.dev_map_path)
    task_ref = _find_task(dev_map, task_id)
    if task_ref is None:
        raise WorkflowCommandError(f"Task {task_id} not found in DEV_MAP.", exit_code=4)

    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "name": "task_exists",
            "status": "passed",
            "task_id": task_id,
        }
    )

    task_list_present = _task_exists_in_task_list(context, task_id)
    if not task_list_present:
        raise WorkflowCommandError(
            f"Task {task_id} is missing in TASK_LIST headings; sync consistency check failed.",
            exit_code=4,
        )
    checks.append({"name": "task_list_heading_present", "status": "passed"})

    if bool(args.run_checks):
        smoke_command = ["bash", "tests/check-workflow-cli-smoke.sh"]
        smoke_result = subprocess.run(
            smoke_command,
            check=False,
            capture_output=True,
            text=True,
            cwd=str(context.root_dir),
        )
        if smoke_result.returncode != 0:
            details = (smoke_result.stderr or smoke_result.stdout).strip() or "unknown smoke failure"
            raise WorkflowCommandError(
                f"Task validation checks failed for {task_id}: {details}",
                exit_code=4,
            )
        checks.append({"name": "workflow_cli_smoke", "status": "passed"})

    emit_json(
        {
            "checks": checks,
            "command": "task.validate",
            "feature_id": task_ref.get("feature_id"),
            "run_checks": bool(args.run_checks),
            "task_id": task_id,
            "task_status": str(task_ref["task"].get("status", "")),
            "valid": True,
        }
    )
    return 0


def _normalize_task_id(raw_task_id: str) -> str:
    """Normalize task ID and enforce global task format."""
    task_id = str(raw_task_id).strip()
    if TASK_ID_PATTERN.fullmatch(task_id) is None:
        raise WorkflowCommandError(
            f"Invalid task ID {raw_task_id!r}; expected numeric format like 76 or 9b.",
            exit_code=4,
        )
    return task_id


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file and map decode errors to workflow command errors."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise WorkflowCommandError(f"Required file not found: {path}", exit_code=4) from error
    except json.JSONDecodeError as error:
        raise WorkflowCommandError(f"Invalid JSON in {path}: {error}", exit_code=4) from error


def _find_task(dev_map: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    """Find task node with parent ownership metadata in DEV_MAP."""
    for milestone in dev_map.get("milestones", []):
        milestone_id = str(milestone.get("id", ""))
        for feature in milestone.get("features", []):
            feature_id = str(feature.get("id", ""))
            for issue in feature.get("issues", []):
                issue_id = str(issue.get("id", ""))
                for task in issue.get("tasks", []):
                    if str(task.get("id", "")).strip() != task_id:
                        continue
                    return {
                        "feature_id": feature_id,
                        "milestone_id": milestone_id,
                        "parent": issue,
                        "parent_id": issue_id,
                        "parent_type": "issue",
                        "task": task,
                    }
        for standalone_issue in milestone.get("standalone_issues", []):
            standalone_id = str(standalone_issue.get("id", ""))
            for task in standalone_issue.get("tasks", []):
                if str(task.get("id", "")).strip() != task_id:
                    continue
                return {
                    "feature_id": None,
                    "milestone_id": milestone_id,
                    "parent": standalone_issue,
                    "parent_id": standalone_id,
                    "parent_type": "standalone-issue",
                    "task": task,
                }
    return None


def _task_exists_in_task_list(context: WorkflowContext, task_id: str) -> bool:
    """Check whether task-list JSON payload contains the given task ID."""
    task_list_payload = load_task_list_payload(context)
    for task in task_list_payload.get("tasks", []):
        if not isinstance(task, dict):
            continue
        if str(task.get("id", "")).strip() == task_id:
            return True
    return False
