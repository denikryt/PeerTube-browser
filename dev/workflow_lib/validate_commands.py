"""Register repository validation command routing for workflow CLI."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context import WorkflowContext
from .errors import WorkflowCommandError
from .output import emit_json
from .tracker_store import load_task_list_payload


FEATURE_ID_PATTERN = re.compile(r"^F(?P<feature_num>\d+)-M(?P<milestone_num>\d+)$")
TASK_ID_PATTERN = re.compile(r"^[0-9]+[a-z]?$")
TASK_LIST_MARKER_PATTERN = re.compile(r"^\[(?P<milestone>M\d+)\]\[(?P<owner>F\d+|SI\d+)\]$")


@dataclass(frozen=True)
class DevMapTaskOwnership:
    """Represent one task ownership mapping from DEV_MAP hierarchy."""

    owner_marker: str
    owner_path: str
    status: str
    milestone_id: str
    task_id: str


@dataclass(frozen=True)
class TaskListOwnership:
    """Represent one task heading ownership mapping from TASK_LIST."""

    line_number: int
    milestone_id: str
    owner_marker: str
    task_id: str


def register_validate_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register validate router with scope gates."""
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validation commands for tracking and repository gates.",
    )
    validate_parser.add_argument(
        "--scope",
        choices=["tracking", "repo"],
        required=True,
        help="Validation scope to execute.",
    )
    validate_parser.add_argument("--feature", help="Optional feature ID filter.")
    validate_parser.add_argument("--strict", action="store_true", help="Enable strict validation mode.")
    validate_parser.set_defaults(handler=_handle_validate)


def _handle_validate(args: Namespace, context: WorkflowContext) -> int:
    """Run tracking or repository validations and return deterministic JSON."""
    feature_id = _normalize_feature_filter(args.feature)
    tracking_result = _run_tracking_validation(context=context, feature_id=feature_id)
    repo_errors: list[str] = []
    repo_warnings: list[str] = []
    if args.scope == "repo":
        repo_result = _run_repo_validation(context=context, strict=bool(args.strict))
        repo_errors.extend(repo_result["errors"])
        repo_warnings.extend(repo_result["warnings"])

    errors = tracking_result["errors"] + repo_errors
    warnings = tracking_result["warnings"] + repo_warnings
    payload = {
        "command": "validate.run",
        "errors": errors,
        "feature_id": feature_id,
        "scope": args.scope,
        "strict": bool(args.strict),
        "valid": not errors,
        "warnings": warnings,
    }
    emit_json(payload)
    return 0 if not errors else 4


def _normalize_feature_filter(raw_feature: str | None) -> str | None:
    """Normalize and validate optional feature ID filter."""
    if raw_feature is None:
        return None
    feature_id = raw_feature.strip().upper()
    if FEATURE_ID_PATTERN.fullmatch(feature_id) is None:
        raise WorkflowCommandError(
            f"Invalid --feature value {raw_feature!r}; expected F<local>-M<milestone>.",
            exit_code=4,
        )
    return feature_id


def _run_tracking_validation(context: WorkflowContext, feature_id: str | None) -> dict[str, list[str]]:
    """Validate tracker consistency for feature/issue runtime entities."""
    errors: list[str] = []
    warnings: list[str] = []
    dev_map = _load_json(context.dev_map_path)
    if feature_id is not None and _find_feature_status(dev_map, feature_id) is None:
        errors.append(f"Feature {feature_id} not found in DEV_MAP.")
        return {"errors": errors, "warnings": warnings}

    seen_feature_ids: set[str] = set()
    seen_issue_ids: set[str] = set()
    for milestone in dev_map.get("milestones", []):
        milestone_id = str(milestone.get("id", "")).strip()
        for feature in milestone.get("features", []):
            current_feature_id = str(feature.get("id", "")).strip()
            if not current_feature_id:
                continue
            if current_feature_id in seen_feature_ids:
                errors.append(f"Duplicate feature id in DEV_MAP: {current_feature_id}")
            seen_feature_ids.add(current_feature_id)
            if feature_id is not None and current_feature_id.upper() != feature_id:
                continue
            feature_milestone_id = str(feature.get("milestone_id", "")).strip()
            if feature_milestone_id and feature_milestone_id != milestone_id:
                errors.append(
                    f"Feature {current_feature_id} milestone_id mismatch: node={feature_milestone_id}, parent={milestone_id}."
                )
            for issue in feature.get("issues", []):
                issue_id = str(issue.get("id", "")).strip()
                if not issue_id:
                    continue
                if issue_id in seen_issue_ids:
                    errors.append(f"Duplicate issue id in DEV_MAP: {issue_id}")
                seen_issue_ids.add(issue_id)
                issue_feature_id = str(issue.get("feature_id", "")).strip()
                issue_milestone_id = str(issue.get("milestone_id", "")).strip()
                if issue_feature_id and issue_feature_id != current_feature_id:
                    errors.append(
                        f"Issue {issue_id} feature_id mismatch: node={issue_feature_id}, owner={current_feature_id}."
                    )
                if issue_milestone_id and issue_milestone_id != milestone_id:
                    errors.append(
                        f"Issue {issue_id} milestone_id mismatch: node={issue_milestone_id}, parent={milestone_id}."
                    )

    if context.task_list_path.exists():
        load_task_list_payload(context)

    return {"errors": errors, "warnings": warnings}


def _run_repo_validation(context: WorkflowContext, strict: bool) -> dict[str, list[str]]:
    """Validate repository-level gates in addition to tracking checks."""
    errors: list[str] = []
    warnings: list[str] = []
    workflow_entry = context.root_dir / "dev" / "workflow"
    if not workflow_entry.exists():
        errors.append("Missing workflow CLI entrypoint: dev/workflow.")
    elif not workflow_entry.is_file():
        errors.append("Workflow CLI entrypoint exists but is not a file: dev/workflow.")
    elif not workflow_entry.stat().st_mode & 0o111:
        warnings.append("Workflow CLI entrypoint is not executable by any user class.")

    if strict:
        git_status = subprocess.run(
            ["git", "status", "--short"],
            check=False,
            capture_output=True,
            cwd=context.root_dir,
            text=True,
        )
        if git_status.returncode != 0:
            stderr = (git_status.stderr or "").strip()
            errors.append(f"Unable to run git status for strict repo validation: {stderr or 'unknown error'}.")
        elif git_status.stdout.strip():
            errors.append("Strict repo validation requires a clean working tree (git status --short is not empty).")

    return {"errors": errors, "warnings": warnings}


def _load_json(path: Path) -> dict[str, Any]:
    """Read JSON document from path with deterministic error mapping."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise WorkflowCommandError(f"Required file not found: {path}", exit_code=4) from error
    except json.JSONDecodeError as error:
        raise WorkflowCommandError(f"Invalid JSON in {path}: {error}", exit_code=4) from error


def _find_feature_status(dev_map: dict[str, Any], feature_id: str) -> str | None:
    """Return feature status by ID from DEV_MAP."""
    for milestone in dev_map.get("milestones", []):
        for feature in milestone.get("features", []):
            if str(feature.get("id", "")).upper() == feature_id:
                return str(feature.get("status", ""))
    return None


def _collect_dev_map_task_ownership(
    dev_map: dict[str, Any],
    feature_id: str | None,
) -> tuple[dict[str, DevMapTaskOwnership], list[str]]:
    """Collect DEV_MAP task ownership for full map or one feature subtree."""
    ownership: dict[str, DevMapTaskOwnership] = {}
    duplicates: list[str] = []
    target_feature_id = feature_id.upper() if feature_id else None
    for milestone in dev_map.get("milestones", []):
        milestone_id = str(milestone.get("id", ""))
        for feature in milestone.get("features", []):
            current_feature_id = str(feature.get("id", "")).upper()
            if target_feature_id and current_feature_id != target_feature_id:
                continue
            owner_marker = _feature_owner_marker(str(feature.get("id", "")))
            for issue in feature.get("issues", []):
                issue_id = str(issue.get("id", ""))
                for task in issue.get("tasks", []):
                    task_id = str(task.get("id", ""))
                    if task_id in ownership:
                        duplicates.append(task_id)
                        continue
                    ownership[task_id] = DevMapTaskOwnership(
                        task_id=task_id,
                        milestone_id=milestone_id,
                        owner_marker=owner_marker,
                        owner_path=issue_id,
                        status=str(task.get("status", "")),
                    )
        if target_feature_id is not None:
            continue
        for standalone_issue in milestone.get("standalone_issues", []):
            owner_marker = _standalone_owner_marker(str(standalone_issue.get("id", "")))
            standalone_id = str(standalone_issue.get("id", ""))
            for task in standalone_issue.get("tasks", []):
                task_id = str(task.get("id", ""))
                if task_id in ownership:
                    duplicates.append(task_id)
                    continue
                ownership[task_id] = DevMapTaskOwnership(
                    task_id=task_id,
                    milestone_id=milestone_id,
                    owner_marker=owner_marker,
                    owner_path=standalone_id,
                    status=str(task.get("status", "")),
                )
    return ownership, duplicates


def _feature_owner_marker(feature_id: str) -> str:
    """Convert feature ID to TASK_LIST owner marker value."""
    match = FEATURE_ID_PATTERN.fullmatch(feature_id.upper())
    if match is None:
        return "F?"
    return f"F{int(match.group('feature_num'))}"


def _standalone_owner_marker(standalone_id: str) -> str:
    """Convert standalone issue ID to TASK_LIST owner marker value."""
    match = re.fullmatch(r"SI(?P<si_num>\d+)-M\d+", standalone_id.upper())
    if match is None:
        return "SI?"
    return f"SI{int(match.group('si_num'))}"


def _parse_task_list_ownership(task_list_payload: dict[str, Any]) -> tuple[dict[str, TaskListOwnership], list[str]]:
    """Parse task-list JSON marker ownership mappings."""
    entries: dict[str, TaskListOwnership] = {}
    duplicates: list[str] = []
    tasks = task_list_payload.get("tasks", [])
    if not isinstance(tasks, list):
        raise WorkflowCommandError("TASK_LIST payload tasks must be a list.", exit_code=4)
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id", "")).strip()
        marker = str(task.get("marker", "")).strip()
        if not task_id:
            continue
        marker_match = TASK_LIST_MARKER_PATTERN.fullmatch(marker)
        if marker_match is None:
            continue
        if task_id in entries:
            duplicates.append(task_id)
            continue
        entries[task_id] = TaskListOwnership(
            task_id=task_id,
            line_number=index,
            milestone_id=marker_match.group("milestone"),
            owner_marker=marker_match.group("owner"),
        )
    return entries, duplicates


def _validate_task_count(dev_map: dict[str, Any], ownership: dict[str, DevMapTaskOwnership]) -> list[str]:
    """Validate task_count metadata against numeric task IDs."""
    errors: list[str] = []
    task_count = dev_map.get("task_count")
    if not isinstance(task_count, int):
        errors.append("DEV_MAP task_count must be an integer.")
        return errors
    for task_id in ownership:
        if TASK_ID_PATTERN.fullmatch(task_id) is None:
            continue
        numeric_part = re.match(r"^\d+", task_id)
        if numeric_part is None:
            continue
        value = int(numeric_part.group(0))
        if value > task_count:
            errors.append(f"Task {task_id} exceeds task_count={task_count}.")
    return errors
