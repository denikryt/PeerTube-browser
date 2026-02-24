"""Register and execute feature workflow commands."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from typing import Any

from .context import WorkflowContext
from .errors import WorkflowCommandError
from .output import emit_json


FEATURE_ID_PATTERN = re.compile(r"^F(?P<feature_num>\d+)-M(?P<milestone_num>\d+)$")
ISSUE_ID_PATTERN = re.compile(r"^I(?P<issue_num>\d+)-F(?P<feature_num>\d+)-M(?P<milestone_num>\d+)$")
MILESTONE_ID_PATTERN = re.compile(r"^M(?P<milestone_num>\d+)$")
TASK_ID_PATTERN = re.compile(r"^[0-9]+[a-z]?$")
TASK_TOKEN_PATTERN = re.compile(r"^\$[A-Za-z][A-Za-z0-9_-]*$")
TASK_REFERENCE_PATTERN = re.compile(r"^(?:[0-9]+[a-z]?|\$[A-Za-z][A-Za-z0-9_-]*)$")
TASK_LIST_HEADING_PATTERN = re.compile(r"^###\s+(?P<task_id>[0-9]+[a-z]?)\)\s+")
SECTION_H2_PATTERN = re.compile(r"^##\s+([^#].*?)\s*$")
SECTION_H3_PATTERN = re.compile(r"^###\s+([^#].*?)\s*$")
REQUIRED_PLAN_HEADINGS = (
    "Dependencies",
    "Decomposition",
    "Issue/Task Decomposition Assessment",
)


def register_feature_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register feature router and its base subcommands."""
    feature_parser = subparsers.add_parser(
        "feature",
        help="Feature-level workflow commands.",
    )
    feature_subparsers = feature_parser.add_subparsers(
        dest="feature_command",
        required=True,
    )

    create_parser = feature_subparsers.add_parser(
        "create",
        help="Create or validate a feature registration contract.",
    )
    create_parser.add_argument("--id", required=True, help="Feature ID (for example, F1-M1).")
    create_parser.add_argument("--milestone", help="Milestone ID (for example, M1).")
    create_parser.add_argument("--title", help="Feature title when creating a new node.")
    create_parser.add_argument("--track", default="System/Test", help="Track label for feature node.")
    create_parser.add_argument("--write", action="store_true", help="Write local tracker updates.")
    create_parser.add_argument("--github", action="store_true", help="Enable GitHub sync wiring.")
    create_parser.set_defaults(handler=_handle_feature_create)

    plan_init_parser = feature_subparsers.add_parser(
        "plan-init",
        help="Initialize feature section scaffold in FEATURE_PLANS.",
    )
    plan_init_parser.add_argument("--id", required=True, help="Feature ID.")
    plan_init_parser.add_argument("--write", action="store_true", help="Write scaffold to file.")
    plan_init_parser.set_defaults(handler=_handle_feature_plan_init)

    plan_lint_parser = feature_subparsers.add_parser(
        "plan-lint",
        help="Validate feature plan section structure.",
    )
    plan_lint_parser.add_argument("--id", required=True, help="Feature ID.")
    plan_lint_parser.add_argument("--strict", action="store_true", help="Enable strict lint checks.")
    plan_lint_parser.set_defaults(handler=_handle_feature_plan_lint)

    approve_parser = feature_subparsers.add_parser(
        "approve",
        help="Approve feature plan and update feature status gate.",
    )
    approve_parser.add_argument("--id", required=True, help="Feature ID.")
    approve_parser.add_argument("--write", action="store_true", help="Write status update to tracker.")
    approve_parser.add_argument("--strict", action="store_true", help="Require strict plan lint pass.")
    approve_parser.set_defaults(handler=_handle_feature_approve)

    sync_parser = feature_subparsers.add_parser(
        "sync",
        help="Sync manual decomposition delta to DEV_MAP/TASK_LIST/PIPELINE.",
    )
    sync_parser.add_argument("--id", required=True, help="Feature ID.")
    sync_parser.add_argument(
        "--delta-file",
        required=True,
        help="Path to JSON delta describing issue/task and tracker updates.",
    )
    sync_parser.add_argument("--write", action="store_true", help="Persist tracker updates.")
    sync_parser.add_argument(
        "--allocate-task-ids",
        action="store_true",
        help="Allocate numeric IDs from DEV_MAP task_count for token IDs ($token).",
    )
    sync_parser.add_argument(
        "--update-pipeline",
        action="store_true",
        help="Apply pipeline section updates from the delta payload.",
    )
    sync_parser.set_defaults(handler=_handle_feature_sync)

    materialize_parser = feature_subparsers.add_parser(
        "materialize",
        help="Materialize local feature issues to GitHub and apply canonical branch policy.",
    )
    materialize_parser.add_argument("--id", required=True, help="Feature ID.")
    materialize_parser.add_argument("--write", action="store_true", help="Persist tracker updates and side effects.")
    materialize_parser.add_argument(
        "--github",
        dest="github",
        action="store_true",
        default=True,
        help="Create or update mapped GitHub issues.",
    )
    materialize_parser.add_argument(
        "--no-github",
        dest="github",
        action="store_false",
        help="Skip GitHub issue create/update calls.",
    )
    materialize_parser.set_defaults(handler=_handle_feature_materialize)

    execution_plan_parser = feature_subparsers.add_parser(
        "execution-plan",
        help="Return ordered execution plan for one feature subtree.",
    )
    execution_plan_parser.add_argument("--id", required=True, help="Feature ID.")
    execution_plan_parser.add_argument(
        "--only-pending",
        action="store_true",
        help="Filter to pending tasks only.",
    )
    execution_plan_parser.add_argument(
        "--from-pipeline",
        action="store_true",
        help="Apply pipeline ordering before issue-local order.",
    )
    execution_plan_parser.set_defaults(only_pending=True, from_pipeline=True)
    execution_plan_parser.set_defaults(handler=_handle_feature_execution_plan)


def _handle_feature_create(args: Namespace, context: WorkflowContext) -> int:
    """Create feature node and optionally sync feature-level GitHub issue metadata."""
    feature_id, feature_milestone_num = _parse_feature_id(args.id)
    milestone_id = _normalize_id(args.milestone or f"M{feature_milestone_num}")
    milestone_num = _parse_milestone_id(milestone_id)
    if milestone_num != feature_milestone_num:
        raise WorkflowCommandError(
            f"Milestone mismatch: feature {feature_id} belongs to M{feature_milestone_num}, got {milestone_id}.",
            exit_code=4,
        )

    dev_map = _load_json(context.dev_map_path)
    milestone_node = _find_milestone(dev_map, milestone_id)
    if milestone_node is None:
        raise WorkflowCommandError(f"Milestone {milestone_id} not found in DEV_MAP.", exit_code=4)
    milestone_title = _resolve_github_milestone_title(milestone_node, milestone_id)

    feature_ref = _find_feature(dev_map, feature_id)
    feature_exists = feature_ref is not None
    wrote_changes = False
    if feature_ref is not None:
        existing_milestone = feature_ref["milestone"]["id"]
        if existing_milestone != milestone_id:
            raise WorkflowCommandError(
                f"Feature {feature_id} already exists under {existing_milestone}, not {milestone_id}.",
                exit_code=4,
            )
        feature_node = feature_ref["feature"]
    else:
        feature_node = _build_feature_node(
            feature_id=feature_id,
            title=(args.title or f"Feature {feature_id}"),
            track=args.track,
        )
        if bool(args.write):
            milestone_node.setdefault("features", []).append(feature_node)
            wrote_changes = True

    github_issue: dict[str, Any] | None = None
    if bool(args.github):
        if bool(args.write):
            github_repo = _resolve_github_repository(context.root_dir)
            _ensure_github_milestone_exists(
                repo_name_with_owner=github_repo["name_with_owner"],
                milestone_title=milestone_title,
                milestone_id=milestone_id,
            )
            github_issue = _materialize_feature_registration_issue(
                feature_node=feature_node,
                milestone_title=milestone_title,
                repo_name_with_owner=github_repo["name_with_owner"],
                repo_url=_normalize_repository_url(str(github_repo.get("url", ""))),
            )
            wrote_changes = True
        else:
            existing_issue_number = _coerce_issue_number(
                feature_node.get("gh_issue_number"),
                feature_node.get("gh_issue_url"),
            )
            github_issue = {
                "action": "would-update" if existing_issue_number is not None else "would-create",
                "gh_issue_number": existing_issue_number,
                "gh_issue_url": str(feature_node.get("gh_issue_url", "")).strip() or None,
                "milestone_title": milestone_title,
            }

    if bool(args.write) and wrote_changes:
        _touch_updated_at(dev_map)
        _write_json(context.dev_map_path, dev_map)

    emit_json(
        {
            "action": "already-exists" if feature_exists else ("created" if bool(args.write) else "would-create"),
            "command": "feature.create",
            "feature_id": feature_id,
            "gh_issue_number": feature_node.get("gh_issue_number"),
            "gh_issue_url": feature_node.get("gh_issue_url"),
            "github_enabled": bool(args.github),
            "github_issue": github_issue,
            "milestone_title": milestone_title,
            "milestone_id": milestone_id,
            "write_applied": bool(args.write) and wrote_changes,
            "write": bool(args.write),
        }
    )
    return 0


def _handle_feature_plan_init(args: Namespace, context: WorkflowContext) -> int:
    """Initialize a feature plan section scaffold in FEATURE_PLANS."""
    feature_id, _ = _parse_feature_id(args.id)
    _require_feature_exists(context, feature_id)
    plan_text = context.feature_plans_path.read_text(encoding="utf-8")
    if _find_h2_section_bounds(plan_text, feature_id) is not None:
        emit_json(
            {
                "action": "already-exists",
                "command": "feature.plan-init",
                "feature_id": feature_id,
                "write": bool(args.write),
            }
        )
        return 0

    if args.write:
        scaffold = _build_feature_plan_scaffold(feature_id)
        suffix = "" if plan_text.endswith("\n") else "\n"
        updated_text = f"{plan_text}{suffix}\n{scaffold}"
        context.feature_plans_path.write_text(updated_text, encoding="utf-8")
    emit_json(
        {
            "action": "created" if args.write else "would-create",
            "command": "feature.plan-init",
            "feature_id": feature_id,
            "write": bool(args.write),
        }
    )
    return 0


def _handle_feature_plan_lint(args: Namespace, context: WorkflowContext) -> int:
    """Lint feature plan section shape and required headings/content."""
    feature_id, _ = _parse_feature_id(args.id)
    section_text = _extract_feature_plan_section(context.feature_plans_path, feature_id)
    lint_result = _lint_plan_section(section_text, strict=bool(args.strict))
    emit_json(
        {
            "command": "feature.plan-lint",
            "feature_id": feature_id,
            "messages": lint_result["messages"],
            "strict": bool(args.strict),
            "valid": True,
        }
    )
    return 0


def _handle_feature_approve(args: Namespace, context: WorkflowContext) -> int:
    """Approve a feature plan after lint checks and update DEV_MAP status."""
    feature_id, _ = _parse_feature_id(args.id)
    section_text = _extract_feature_plan_section(context.feature_plans_path, feature_id)
    _lint_plan_section(section_text, strict=bool(args.strict))
    dev_map = _load_json(context.dev_map_path)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)

    feature_node = feature_ref["feature"]
    previous_status = str(feature_node.get("status", ""))
    if previous_status == "Done":
        raise WorkflowCommandError(f"Feature {feature_id} is already Done and cannot be re-approved.", exit_code=4)

    action = "already-approved"
    if previous_status != "Approved":
        action = "approved" if args.write else "would-approve"
        if args.write:
            feature_node["status"] = "Approved"
            _touch_updated_at(dev_map)
            _write_json(context.dev_map_path, dev_map)

    emit_json(
        {
            "action": action,
            "command": "feature.approve",
            "feature_id": feature_id,
            "strict": bool(args.strict),
            "status_after": "Approved" if action != "would-approve" else previous_status,
            "status_before": previous_status,
            "write": bool(args.write),
        }
    )
    return 0


def _handle_feature_sync(args: Namespace, context: WorkflowContext) -> int:
    """Apply a manual decomposition delta to all local tracker files."""
    feature_id, feature_milestone_num = _parse_feature_id(args.id)
    feature_local_num = _parse_feature_local_num(feature_id)
    dev_map = _load_json(context.dev_map_path)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)

    feature_node = feature_ref["feature"]
    if bool(args.write) and str(feature_node.get("status", "")) != "Approved":
        raise WorkflowCommandError(
            f"feature sync --write requires status Approved; got {feature_node.get('status')!r} for {feature_id}.",
            exit_code=4,
        )

    delta = _load_sync_delta(Path(args.delta_file))
    existing_task_locations = _collect_task_locations(dev_map)
    resolved_delta, allocation = _resolve_sync_delta_references(
        delta=delta,
        dev_map=dev_map,
        existing_task_locations=existing_task_locations,
        allocate_task_ids=bool(args.allocate_task_ids),
    )
    issue_counts = _apply_issue_delta(
        feature_node=feature_node,
        feature_id=feature_id,
        feature_milestone_num=feature_milestone_num,
        feature_local_num=feature_local_num,
        statuses=set(dev_map.get("statuses", [])),
        issue_payloads=resolved_delta.get("issues", []),
        existing_task_locations=existing_task_locations,
    )

    original_task_list_text = context.task_list_path.read_text(encoding="utf-8")
    updated_task_list_text, task_list_count = _apply_task_list_delta(
        task_list_text=original_task_list_text,
        entries=resolved_delta.get("task_list_entries", []),
        expected_marker=f"[M{feature_milestone_num}][F{feature_local_num}]",
    )

    original_pipeline_text = context.pipeline_path.read_text(encoding="utf-8")
    updated_pipeline_text, pipeline_counts = _apply_pipeline_delta(
        pipeline_text=original_pipeline_text,
        pipeline_payload=resolved_delta.get("pipeline", {}),
        update_pipeline=bool(args.update_pipeline),
    )

    task_count_before = int(dev_map.get("task_count", 0))
    if bool(args.write):
        if allocation["task_count_after"] != task_count_before:
            dev_map["task_count"] = allocation["task_count_after"]
        _touch_updated_at(dev_map)
        _write_json(context.dev_map_path, dev_map)
        context.task_list_path.write_text(updated_task_list_text, encoding="utf-8")
        context.pipeline_path.write_text(updated_pipeline_text, encoding="utf-8")

    emit_json(
        {
            "action": "synced" if bool(args.write) else "would-sync",
            "allocate_task_ids": bool(args.allocate_task_ids),
            "allocated_task_ids": allocation["allocated_ids"],
            "command": "feature.sync",
            "delta_file": str(Path(args.delta_file)),
            "dev_map_issues_upserted": issue_counts["issues_upserted"],
            "dev_map_tasks_upserted": issue_counts["tasks_upserted"],
            "feature_id": feature_id,
            "pipeline_blocks_added": pipeline_counts["blocks_added"],
            "pipeline_execution_rows_added": pipeline_counts["sequence_rows_added"],
            "pipeline_overlaps_added": pipeline_counts["overlaps_added"],
            "task_count_after": allocation["task_count_after"] if bool(args.write) else task_count_before,
            "task_count_before": task_count_before,
            "task_list_entries_added": task_list_count,
            "update_pipeline": bool(args.update_pipeline),
            "write": bool(args.write),
        }
    )
    return 0


def _handle_feature_materialize(args: Namespace, context: WorkflowContext) -> int:
    """Materialize local feature issue nodes to GitHub with canonical branch policy."""
    feature_id, feature_milestone_num = _parse_feature_id(args.id)
    milestone_id = f"M{feature_milestone_num}"
    dev_map = _load_json(context.dev_map_path)
    milestone_node = _find_milestone(dev_map, milestone_id)
    if milestone_node is None:
        raise WorkflowCommandError(f"Milestone {milestone_id} not found in DEV_MAP.", exit_code=4)
    milestone_title = _resolve_github_milestone_title(milestone_node, milestone_id)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)

    feature_node = feature_ref["feature"]
    feature_status = str(feature_node.get("status", ""))
    if feature_status != "Approved":
        raise WorkflowCommandError(
            f"Feature {feature_id} has status {feature_status}; expected Approved before materialize.",
            exit_code=4,
        )

    issue_nodes = feature_node.get("issues", [])
    if not issue_nodes:
        raise WorkflowCommandError(
            f"Feature {feature_id} has no local issue nodes to materialize.",
            exit_code=4,
        )

    branch_name = f"feature/{feature_id}"
    repo_url = _resolve_repository_url(context.root_dir, feature_node)
    branch_url = _build_branch_url(repo_url, branch_name)
    if bool(args.write):
        branch_action = _checkout_canonical_feature_branch(context.root_dir, branch_name)
    else:
        branch_action = _plan_canonical_feature_branch(context.root_dir, branch_name)

    materialized_issues: list[dict[str, Any]] = []
    if bool(args.write) and bool(args.github):
        github_repo = _resolve_github_repository(context.root_dir)
        _ensure_github_milestone_exists(
            repo_name_with_owner=github_repo["name_with_owner"],
            milestone_title=milestone_title,
            milestone_id=milestone_id,
        )
        for issue_node in issue_nodes:
            materialized = _materialize_feature_issue_node(
                issue_node=issue_node,
                milestone_title=milestone_title,
                repo_name_with_owner=github_repo["name_with_owner"],
                repo_url=_normalize_repository_url(str(github_repo.get("url", ""))),
            )
            materialized_issues.append(materialized)
    else:
        for issue_node in issue_nodes:
            issue_id = str(issue_node.get("id", ""))
            issue_number = issue_node.get("gh_issue_number")
            issue_url = str(issue_node.get("gh_issue_url", "")).strip() or None
            materialized_issues.append(
                {
                    "action": "would-update" if issue_number else "would-create",
                    "issue_id": issue_id,
                    "gh_issue_number": issue_number,
                    "gh_issue_url": issue_url,
                }
            )

    if bool(args.write):
        feature_node["branch_name"] = branch_name
        feature_node["branch_url"] = branch_url
        _touch_updated_at(dev_map)
        _write_json(context.dev_map_path, dev_map)

    active_branch_message = f"Active feature branch: {branch_name}"
    emit_json(
        {
            "active_feature_branch": branch_name,
            "active_feature_branch_message": active_branch_message,
            "branch_action": branch_action,
            "branch_url": branch_url,
            "command": "feature.materialize",
            "feature_id": feature_id,
            "feature_status": feature_status,
            "github_enabled": bool(args.github),
            "issues_materialized": materialized_issues,
            "github_milestone_title": milestone_title,
            "milestone_id": milestone_id,
            "write": bool(args.write),
        }
    )
    return 0


def _handle_feature_execution_plan(args: Namespace, context: WorkflowContext) -> int:
    """Build ordered task execution plan for one feature subtree."""
    feature_id, _ = _parse_feature_id(args.id)
    dev_map = _load_json(context.dev_map_path)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)
    feature_node = feature_ref["feature"]
    feature_status = str(feature_node.get("status", ""))
    if feature_status not in {"Approved", "Done"}:
        raise WorkflowCommandError(
            f"Feature {feature_id} has status {feature_status}; expected Approved before execution-plan.",
            exit_code=4,
        )

    ordered_tasks = _collect_feature_tasks(feature_node, only_pending=bool(args.only_pending))
    if bool(args.from_pipeline):
        pipeline_order = _parse_pipeline_execution_order(context.pipeline_path)
        ordered_tasks = _apply_pipeline_order(ordered_tasks, pipeline_order)

    emit_json(
        {
            "command": "feature.execution-plan",
            "feature_id": feature_id,
            "feature_status": feature_status,
            "from_pipeline": bool(args.from_pipeline),
            "only_pending": bool(args.only_pending),
            "task_count": len(ordered_tasks),
            "tasks": ordered_tasks,
        }
    )
    return 0


def _load_sync_delta(delta_path: Path) -> dict[str, Any]:
    """Load and validate the top-level shape of a feature sync delta file."""
    try:
        payload = json.loads(delta_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise WorkflowCommandError(f"Sync delta file not found: {delta_path}", exit_code=4) from error
    except json.JSONDecodeError as error:
        raise WorkflowCommandError(f"Invalid JSON in sync delta {delta_path}: {error}", exit_code=4) from error
    if not isinstance(payload, dict):
        raise WorkflowCommandError("Sync delta root must be a JSON object.", exit_code=4)
    allowed = {"issues", "task_list_entries", "pipeline"}
    unknown = sorted(key for key in payload if key not in allowed)
    if unknown:
        joined = ", ".join(unknown)
        raise WorkflowCommandError(
            f"Sync delta contains unsupported top-level key(s): {joined}. Allowed: issues, task_list_entries, pipeline.",
            exit_code=4,
        )
    return payload


def _parse_feature_local_num(feature_id: str) -> int:
    """Extract the local feature number from an already validated feature ID."""
    match = FEATURE_ID_PATTERN.fullmatch(feature_id)
    if match is None:
        raise WorkflowCommandError(f"Cannot parse feature local number from {feature_id}.", exit_code=4)
    return int(match.group("feature_num"))


def _collect_task_locations(dev_map: dict[str, Any]) -> dict[str, str]:
    """Collect global task ID ownership locations from DEV_MAP."""
    locations: dict[str, str] = {}
    for milestone in dev_map.get("milestones", []):
        for feature in milestone.get("features", []):
            for issue in feature.get("issues", []):
                issue_id = str(issue.get("id", ""))
                for task in issue.get("tasks", []):
                    task_id = str(task.get("id", ""))
                    if not task_id:
                        continue
                    locations[task_id] = issue_id
        for standalone_issue in milestone.get("standalone_issues", []):
            standalone_id = str(standalone_issue.get("id", ""))
            for task in standalone_issue.get("tasks", []):
                task_id = str(task.get("id", ""))
                if not task_id:
                    continue
                locations[task_id] = standalone_id
    return locations


def _resolve_sync_delta_references(
    delta: dict[str, Any],
    dev_map: dict[str, Any],
    existing_task_locations: dict[str, str],
    allocate_task_ids: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve task references in delta payload and allocate IDs from task_count tokens."""
    resolved = json.loads(json.dumps(delta))
    tokens_in_order: list[str] = []
    explicit_ids: list[str] = []

    def collect_reference(raw_value: Any, location: str) -> str:
        """Normalize and register one task reference from delta payload."""
        normalized = _normalize_task_reference(raw_value, location)
        if TASK_TOKEN_PATTERN.fullmatch(normalized):
            if normalized not in tokens_in_order:
                tokens_in_order.append(normalized)
        else:
            explicit_ids.append(normalized)
        return normalized

    for issue_index, issue in enumerate(resolved.get("issues", [])):
        if not isinstance(issue, dict):
            raise WorkflowCommandError(f"issues[{issue_index}] must be an object.", exit_code=4)
        tasks = issue.get("tasks", [])
        if not isinstance(tasks, list):
            raise WorkflowCommandError(f"issues[{issue_index}].tasks must be a list.", exit_code=4)
        for task_index, task in enumerate(tasks):
            if not isinstance(task, dict):
                raise WorkflowCommandError(f"issues[{issue_index}].tasks[{task_index}] must be an object.", exit_code=4)
            task["id"] = collect_reference(
                task.get("id"),
                f"issues[{issue_index}].tasks[{task_index}].id",
            )

    for entry_index, entry in enumerate(resolved.get("task_list_entries", [])):
        if not isinstance(entry, dict):
            raise WorkflowCommandError(f"task_list_entries[{entry_index}] must be an object.", exit_code=4)
        entry["id"] = collect_reference(
            entry.get("id"),
            f"task_list_entries[{entry_index}].id",
        )

    pipeline_payload = resolved.get("pipeline", {})
    if pipeline_payload and not isinstance(pipeline_payload, dict):
        raise WorkflowCommandError("pipeline payload must be an object.", exit_code=4)
    for item_index, item in enumerate(pipeline_payload.get("execution_sequence_append", [])):
        if not isinstance(item, dict):
            raise WorkflowCommandError(
                f"pipeline.execution_sequence_append[{item_index}] must be an object.",
                exit_code=4,
            )
        tasks = item.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            raise WorkflowCommandError(
                f"pipeline.execution_sequence_append[{item_index}].tasks must be a non-empty list.",
                exit_code=4,
            )
        item["tasks"] = [
            collect_reference(
                task_ref,
                f"pipeline.execution_sequence_append[{item_index}].tasks[{task_index}]",
            )
            for task_index, task_ref in enumerate(tasks)
        ]
    for block_index, block in enumerate(pipeline_payload.get("functional_blocks_append", [])):
        if not isinstance(block, dict):
            raise WorkflowCommandError(
                f"pipeline.functional_blocks_append[{block_index}] must be an object.",
                exit_code=4,
            )
        tasks = block.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            raise WorkflowCommandError(
                f"pipeline.functional_blocks_append[{block_index}].tasks must be a non-empty list.",
                exit_code=4,
            )
        block["tasks"] = [
            collect_reference(
                task_ref,
                f"pipeline.functional_blocks_append[{block_index}].tasks[{task_index}]",
            )
            for task_index, task_ref in enumerate(tasks)
        ]
    for overlap_index, overlap in enumerate(pipeline_payload.get("overlaps_append", [])):
        if not isinstance(overlap, dict):
            raise WorkflowCommandError(f"pipeline.overlaps_append[{overlap_index}] must be an object.", exit_code=4)
        overlap["left"] = collect_reference(
            overlap.get("left"),
            f"pipeline.overlaps_append[{overlap_index}].left",
        )
        overlap["right"] = collect_reference(
            overlap.get("right"),
            f"pipeline.overlaps_append[{overlap_index}].right",
        )

    if tokens_in_order and not allocate_task_ids:
        joined = ", ".join(tokens_in_order)
        raise WorkflowCommandError(
            f"Found token task IDs without --allocate-task-ids: {joined}.",
            exit_code=4,
        )

    try:
        task_count_before = int(dev_map.get("task_count", 0))
    except (TypeError, ValueError) as error:
        raise WorkflowCommandError("DEV_MAP task_count must be an integer.", exit_code=4) from error

    token_to_id: dict[str, str] = {}
    next_numeric_id = task_count_before
    for token in tokens_in_order:
        next_numeric_id += 1
        token_to_id[token] = str(next_numeric_id)

    seen_explicit_ids: set[str] = set()
    for explicit_id in explicit_ids:
        if explicit_id in seen_explicit_ids:
            continue
        seen_explicit_ids.add(explicit_id)
        if explicit_id not in existing_task_locations:
            raise WorkflowCommandError(
                f"New task ID {explicit_id!r} must be allocated from task_count via token + --allocate-task-ids.",
                exit_code=4,
            )

    _replace_task_reference_tokens(resolved, token_to_id)
    return (
        resolved,
        {
            "allocated_ids": token_to_id,
            "task_count_after": next_numeric_id,
            "task_count_before": task_count_before,
        },
    )


def _normalize_task_reference(raw_value: Any, location: str) -> str:
    """Normalize one task reference and validate supported token/ID format."""
    value = str(raw_value or "").strip()
    if TASK_REFERENCE_PATTERN.fullmatch(value) is None:
        raise WorkflowCommandError(
            f"Invalid task reference at {location}: {raw_value!r}. Use task ID or $token.",
            exit_code=4,
        )
    return value


def _replace_task_reference_tokens(payload: dict[str, Any], token_to_id: dict[str, str]) -> None:
    """Replace all token task references in-place using allocation map."""
    for issue in payload.get("issues", []):
        for task in issue.get("tasks", []):
            task_id = str(task.get("id", ""))
            if task_id in token_to_id:
                task["id"] = token_to_id[task_id]
    for entry in payload.get("task_list_entries", []):
        task_id = str(entry.get("id", ""))
        if task_id in token_to_id:
            entry["id"] = token_to_id[task_id]
    pipeline_payload = payload.get("pipeline", {})
    for item in pipeline_payload.get("execution_sequence_append", []):
        item["tasks"] = [token_to_id.get(task_id, task_id) for task_id in item.get("tasks", [])]
    for block in pipeline_payload.get("functional_blocks_append", []):
        block["tasks"] = [token_to_id.get(task_id, task_id) for task_id in block.get("tasks", [])]
    for overlap in pipeline_payload.get("overlaps_append", []):
        overlap["left"] = token_to_id.get(str(overlap.get("left", "")), str(overlap.get("left", "")))
        overlap["right"] = token_to_id.get(str(overlap.get("right", "")), str(overlap.get("right", "")))


def _apply_issue_delta(
    feature_node: dict[str, Any],
    feature_id: str,
    feature_milestone_num: int,
    feature_local_num: int,
    statuses: set[str],
    issue_payloads: list[dict[str, Any]],
    existing_task_locations: dict[str, str],
) -> dict[str, int]:
    """Upsert issue/task nodes from sync payload into feature subtree."""
    issues = feature_node.setdefault("issues", [])
    issues_by_id = {str(issue.get("id", "")): issue for issue in issues}
    issue_upsert_count = 0
    task_upsert_count = 0
    now_date, now_time = _now_date_and_time()
    for issue_index, issue_payload in enumerate(issue_payloads):
        issue_id = _required_string_field(issue_payload, "id", f"issues[{issue_index}]")
        _assert_issue_belongs_to_feature(
            issue_id=issue_id,
            feature_id=feature_id,
            feature_milestone_num=feature_milestone_num,
            feature_local_num=feature_local_num,
        )
        issue_node = issues_by_id.get(issue_id)
        issue_created = False
        if issue_node is None:
            issue_node = {
                "id": issue_id,
                "title": issue_payload.get("title", issue_id),
                "status": "Planned",
                "gh_issue_number": None,
                "gh_issue_url": None,
                "tasks": [],
            }
            issues.append(issue_node)
            issues_by_id[issue_id] = issue_node
            issue_created = True
        issue_upsert_count += 1 if issue_created else 0

        if "title" in issue_payload:
            issue_node["title"] = _required_string_field(issue_payload, "title", f"issues[{issue_index}]")
        if "status" in issue_payload:
            status_value = _required_string_field(issue_payload, "status", f"issues[{issue_index}]")
            _validate_status_value(status_value, statuses, f"issues[{issue_index}].status")
            issue_node["status"] = status_value

        task_payloads = issue_payload.get("tasks", [])
        if not isinstance(task_payloads, list):
            raise WorkflowCommandError(f"issues[{issue_index}].tasks must be a list.", exit_code=4)
        tasks = issue_node.setdefault("tasks", [])
        tasks_by_id = {str(task.get("id", "")): task for task in tasks}
        for task_index, task_payload in enumerate(task_payloads):
            if not isinstance(task_payload, dict):
                raise WorkflowCommandError(
                    f"issues[{issue_index}].tasks[{task_index}] must be an object.",
                    exit_code=4,
                )
            task_id = _required_string_field(task_payload, "id", f"issues[{issue_index}].tasks[{task_index}]")
            existing_location = existing_task_locations.get(task_id)
            if existing_location is not None and existing_location != issue_id:
                raise WorkflowCommandError(
                    f"Task ID {task_id} already belongs to {existing_location}; cannot rebind to {issue_id}.",
                    exit_code=4,
                )
            task_node = tasks_by_id.get(task_id)
            if task_node is None:
                task_node = {"id": task_id}
                tasks.append(task_node)
                tasks_by_id[task_id] = task_node
                existing_task_locations[task_id] = issue_id
            task_node["title"] = _required_string_field(
                task_payload,
                "title",
                f"issues[{issue_index}].tasks[{task_index}]",
            )
            task_node["summary"] = _required_string_field(
                task_payload,
                "summary",
                f"issues[{issue_index}].tasks[{task_index}]",
            )
            status_value = str(task_payload.get("status", task_node.get("status", "Planned"))).strip() or "Planned"
            _validate_status_value(
                status_value,
                statuses,
                f"issues[{issue_index}].tasks[{task_index}].status",
            )
            task_node["status"] = status_value
            task_node["date"] = str(task_payload.get("date", task_node.get("date", now_date))).strip() or now_date
            task_node["time"] = str(task_payload.get("time", task_node.get("time", now_time))).strip() or now_time
            task_upsert_count += 1
    return {"issues_upserted": issue_upsert_count, "tasks_upserted": task_upsert_count}


def _assert_issue_belongs_to_feature(
    issue_id: str,
    feature_id: str,
    feature_milestone_num: int,
    feature_local_num: int,
) -> None:
    """Validate issue ID parent chain against target feature."""
    match = ISSUE_ID_PATTERN.fullmatch(issue_id)
    if match is None:
        raise WorkflowCommandError(
            f"Invalid issue ID {issue_id!r}; expected I<local>-F<feature_local>-M<milestone>.",
            exit_code=4,
        )
    issue_feature_num = int(match.group("feature_num"))
    issue_milestone_num = int(match.group("milestone_num"))
    if issue_feature_num != feature_local_num or issue_milestone_num != feature_milestone_num:
        raise WorkflowCommandError(
            f"Issue {issue_id} does not belong to feature {feature_id}.",
            exit_code=4,
        )


def _validate_status_value(status: str, allowed_statuses: set[str], location: str) -> None:
    """Validate one status value against DEV_MAP status enum."""
    if status not in allowed_statuses:
        allowed = ", ".join(sorted(allowed_statuses))
        raise WorkflowCommandError(f"Invalid status at {location}: {status!r}. Allowed: {allowed}.", exit_code=4)


def _now_date_and_time() -> tuple[str, str]:
    """Return date/time strings in DEV_MAP task-node format."""
    now = datetime.now().astimezone().replace(microsecond=0)
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")


def _apply_task_list_delta(task_list_text: str, entries: list[dict[str, Any]], expected_marker: str) -> tuple[str, int]:
    """Append new task list entries from sync payload."""
    existing_ids = {
        match.group("task_id")
        for match in TASK_LIST_HEADING_PATTERN.finditer(task_list_text)
    }
    rendered_entries: list[str] = []
    for entry_index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise WorkflowCommandError(f"task_list_entries[{entry_index}] must be an object.", exit_code=4)
        task_id = _required_string_field(entry, "id", f"task_list_entries[{entry_index}]")
        if task_id in existing_ids:
            raise WorkflowCommandError(
                f"Task {task_id} already exists in TASK_LIST; sync currently supports append-only task entries.",
                exit_code=4,
            )
        marker = str(entry.get("marker", expected_marker)).strip()
        if marker != expected_marker:
            raise WorkflowCommandError(
                f"task_list_entries[{entry_index}].marker must be {expected_marker}; got {marker}.",
                exit_code=4,
            )
        rendered_entries.append(_format_task_list_entry(task_id=task_id, marker=marker, entry=entry, entry_index=entry_index))
        existing_ids.add(task_id)

    if not rendered_entries:
        return task_list_text, 0
    suffix = "" if task_list_text.endswith("\n") else "\n"
    updated = f"{task_list_text}{suffix}\n{'\n\n'.join(rendered_entries)}\n"
    return updated, len(rendered_entries)


def _format_task_list_entry(task_id: str, marker: str, entry: dict[str, Any], entry_index: int) -> str:
    """Render one TASK_LIST markdown entry from structured sync payload."""
    title = _required_string_field(entry, "title", f"task_list_entries[{entry_index}]")
    problem = _required_string_field(entry, "problem", f"task_list_entries[{entry_index}]")
    solution_option = _required_string_field(entry, "solution_option", f"task_list_entries[{entry_index}]")
    concrete_steps = _required_list_field(entry, "concrete_steps", f"task_list_entries[{entry_index}]")
    lines = [f"### {task_id}) {marker} {title}", f"**Problem:** {problem}", "", f"**Solution option:** {solution_option}", "", "#### **Concrete steps:**"]
    for step_index, step in enumerate(concrete_steps, start=1):
        lines.append(f"{step_index}. {step}")
    return "\n".join(lines)


def _required_string_field(payload: dict[str, Any], key: str, location: str) -> str:
    """Read and validate a required non-empty string field."""
    value = str(payload.get(key, "")).strip()
    if not value:
        raise WorkflowCommandError(f"Missing required field {location}.{key}.", exit_code=4)
    return value


def _required_list_field(payload: dict[str, Any], key: str, location: str) -> list[str]:
    """Read and validate a required non-empty list[str] field."""
    raw_list = payload.get(key)
    if not isinstance(raw_list, list) or not raw_list:
        raise WorkflowCommandError(f"Field {location}.{key} must be a non-empty list.", exit_code=4)
    normalized: list[str] = []
    for index, value in enumerate(raw_list):
        item = str(value).strip()
        if not item:
            raise WorkflowCommandError(f"Field {location}.{key}[{index}] must be a non-empty string.", exit_code=4)
        normalized.append(item)
    return normalized


def _apply_pipeline_delta(
    pipeline_text: str,
    pipeline_payload: dict[str, Any],
    update_pipeline: bool,
) -> tuple[str, dict[str, int]]:
    """Append execution-order, functional block, and overlap entries to pipeline."""
    if not pipeline_payload:
        return pipeline_text, {"blocks_added": 0, "overlaps_added": 0, "sequence_rows_added": 0}
    if not update_pipeline:
        raise WorkflowCommandError(
            "Delta contains pipeline payload but --update-pipeline was not provided.",
            exit_code=4,
        )

    execution_items = pipeline_payload.get("execution_sequence_append", [])
    block_items = pipeline_payload.get("functional_blocks_append", [])
    overlap_items = pipeline_payload.get("overlaps_append", [])
    if not isinstance(execution_items, list):
        raise WorkflowCommandError("pipeline.execution_sequence_append must be a list.", exit_code=4)
    if not isinstance(block_items, list):
        raise WorkflowCommandError("pipeline.functional_blocks_append must be a list.", exit_code=4)
    if not isinstance(overlap_items, list):
        raise WorkflowCommandError("pipeline.overlaps_append must be a list.", exit_code=4)

    lines = pipeline_text.splitlines()
    sequence_bounds = _find_section_bounds(lines, "### Execution sequence")
    blocks_bounds = _find_section_bounds(lines, "### Functional blocks")
    overlaps_bounds = _find_section_bounds(lines, "### Cross-task overlaps and dependencies")
    if sequence_bounds is None or blocks_bounds is None or overlaps_bounds is None:
        raise WorkflowCommandError("Pipeline file is missing required sections for sync append.", exit_code=4)

    sequence_start, sequence_end = sequence_bounds
    existing_numbers = []
    for line in lines[sequence_start:sequence_end]:
        match = re.match(r"^\s*(\d+)\.\s", line)
        if match is not None:
            existing_numbers.append(int(match.group(1)))
    next_number = max(existing_numbers, default=0) + 1
    sequence_lines: list[str] = []
    for item_index, item in enumerate(execution_items):
        if not isinstance(item, dict):
            raise WorkflowCommandError(
                f"pipeline.execution_sequence_append[{item_index}] must be an object.",
                exit_code=4,
            )
        tasks = _required_list_field(
            item,
            "tasks",
            f"pipeline.execution_sequence_append[{item_index}]",
        )
        description = str(item.get("description", "")).strip()
        sequence_lines.append(_render_sequence_line(next_number, tasks, description))
        next_number += 1
    lines = lines[:sequence_end] + sequence_lines + lines[sequence_end:]

    blocks_bounds = _find_section_bounds(lines, "### Functional blocks")
    if blocks_bounds is None:
        raise WorkflowCommandError("Pipeline functional blocks section is missing after sequence update.", exit_code=4)
    _, blocks_end = blocks_bounds
    block_lines: list[str] = []
    for block_index, block in enumerate(block_items):
        if not isinstance(block, dict):
            raise WorkflowCommandError(
                f"pipeline.functional_blocks_append[{block_index}] must be an object.",
                exit_code=4,
            )
        title = _required_string_field(
            block,
            "title",
            f"pipeline.functional_blocks_append[{block_index}]",
        )
        tasks = _required_list_field(
            block,
            "tasks",
            f"pipeline.functional_blocks_append[{block_index}]",
        )
        scope = _required_string_field(
            block,
            "scope",
            f"pipeline.functional_blocks_append[{block_index}]",
        )
        outcome = _required_string_field(
            block,
            "outcome",
            f"pipeline.functional_blocks_append[{block_index}]",
        )
        task_chain = " -> ".join(tasks)
        block_lines.extend(
            [
                f"- **{title}**",
                f"  - Tasks: **{task_chain}**",
                f"  - Scope: {scope}",
                f"  - Outcome: {outcome}",
            ]
        )
    lines = lines[:blocks_end] + block_lines + lines[blocks_end:]

    overlaps_bounds = _find_section_bounds(lines, "### Cross-task overlaps and dependencies")
    if overlaps_bounds is None:
        raise WorkflowCommandError("Pipeline overlaps section is missing after block update.", exit_code=4)
    _, overlaps_end = overlaps_bounds
    overlap_lines: list[str] = []
    for overlap_index, overlap in enumerate(overlap_items):
        if not isinstance(overlap, dict):
            raise WorkflowCommandError(
                f"pipeline.overlaps_append[{overlap_index}] must be an object.",
                exit_code=4,
            )
        left = _required_string_field(
            overlap,
            "left",
            f"pipeline.overlaps_append[{overlap_index}]",
        )
        right = _required_string_field(
            overlap,
            "right",
            f"pipeline.overlaps_append[{overlap_index}]",
        )
        description = _required_string_field(
            overlap,
            "description",
            f"pipeline.overlaps_append[{overlap_index}]",
        )
        overlap_lines.append(f"- **{left} <-> {right}**: {description}")
    lines = lines[:overlaps_end] + overlap_lines + lines[overlaps_end:]

    updated = "\n".join(lines)
    if not updated.endswith("\n"):
        updated = f"{updated}\n"
    return (
        updated,
        {
            "blocks_added": len(block_lines) // 4,
            "overlaps_added": len(overlap_lines),
            "sequence_rows_added": len(sequence_lines),
        },
    )


def _find_section_bounds(lines: list[str], section_heading_prefix: str) -> tuple[int, int] | None:
    """Return [start,end) line bounds for one level-3 markdown section."""
    start_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip().startswith(section_heading_prefix):
            start_index = index
            break
    if start_index is None:
        return None
    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if re.match(r"^#{1,6}\s+", lines[index].strip()):
            end_index = index
            break
    return start_index, end_index


def _render_sequence_line(number: int, tasks: list[str], description: str) -> str:
    """Render one execution sequence line from ordered task IDs."""
    task_text = " then ".join(f"**{task_id}**" for task_id in tasks)
    if description:
        return f"{number}. {task_text} ({description})"
    return f"{number}. {task_text}"


def _materialize_feature_issue_node(
    issue_node: dict[str, Any],
    milestone_title: str,
    repo_name_with_owner: str,
    repo_url: str | None,
) -> dict[str, Any]:
    """Create or update one GitHub issue from a local DEV_MAP issue node."""
    issue_id = str(issue_node.get("id", "")).strip()
    if not issue_id:
        raise WorkflowCommandError("Feature issue node is missing required id during materialize.", exit_code=4)
    title = str(issue_node.get("title", "")).strip() or issue_id
    body = _build_materialized_issue_body(issue_node)
    issue_number = _coerce_issue_number(issue_node.get("gh_issue_number"), issue_node.get("gh_issue_url"))
    action = "updated" if issue_number is not None else "created"

    if issue_number is None:
        created_url = _gh_issue_create(
            repo_name_with_owner=repo_name_with_owner,
            title=title,
            body=body,
            milestone_title=milestone_title,
        )
        parsed_number = _parse_issue_number_from_url(created_url)
        if parsed_number is None:
            raise WorkflowCommandError(
                f"Failed to parse created GitHub issue number from URL: {created_url}",
                exit_code=5,
            )
        issue_number = parsed_number
        issue_url = created_url
    else:
        _gh_issue_edit(
            repo_name_with_owner=repo_name_with_owner,
            issue_number=issue_number,
            title=title,
            body=body,
            milestone_title=milestone_title,
        )
        issue_url = _build_issue_url(repo_url, issue_number) or str(issue_node.get("gh_issue_url", "")).strip() or None

    issue_node["gh_issue_number"] = issue_number
    issue_node["gh_issue_url"] = issue_url
    return {
        "action": action,
        "gh_issue_number": issue_number,
        "gh_issue_url": issue_url,
        "issue_id": issue_id,
    }


def _build_materialized_issue_body(issue_node: dict[str, Any]) -> str:
    """Build issue-focused GitHub body from local issue title and mapped tasks."""
    issue_title = str(issue_node.get("title", "")).strip() or str(issue_node.get("id", "")).strip()
    tasks = issue_node.get("tasks", [])
    lines = [
        "## Scope",
        issue_title,
        "",
        "## Planned work/tasks",
    ]
    if isinstance(tasks, list) and tasks:
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id", "")).strip()
            task_title = str(task.get("title", "")).strip()
            task_summary = str(task.get("summary", "")).strip()
            checkbox = "x" if str(task.get("status", "")) == "Done" else " "
            task_label = f"Task {task_id}: {task_title}" if task_id else task_title
            if task_summary:
                task_label = f"{task_label} - {task_summary}" if task_label else task_summary
            lines.append(f"- [{checkbox}] {task_label or 'Task details pending local sync.'}")
    else:
        lines.append("- [ ] Local issue has no mapped tasks yet.")
    return "\n".join(lines).strip() + "\n"


def _materialize_feature_registration_issue(
    feature_node: dict[str, Any],
    milestone_title: str,
    repo_name_with_owner: str,
    repo_url: str | None,
) -> dict[str, Any]:
    """Create or update feature-level GitHub issue and persist metadata on feature node."""
    feature_id = str(feature_node.get("id", "")).strip()
    if not feature_id:
        raise WorkflowCommandError("Feature node is missing required id during feature.create GitHub sync.", exit_code=4)
    title = str(feature_node.get("title", "")).strip() or feature_id
    body = _build_feature_registration_issue_body(feature_node)
    issue_number = _coerce_issue_number(feature_node.get("gh_issue_number"), feature_node.get("gh_issue_url"))
    action = "updated" if issue_number is not None else "created"

    if issue_number is None:
        created_url = _gh_issue_create(
            repo_name_with_owner=repo_name_with_owner,
            title=title,
            body=body,
            milestone_title=milestone_title,
        )
        parsed_number = _parse_issue_number_from_url(created_url)
        if parsed_number is None:
            raise WorkflowCommandError(
                f"Failed to parse created feature issue number from URL: {created_url}",
                exit_code=5,
            )
        issue_number = parsed_number
        issue_url = created_url
    else:
        _gh_issue_edit(
            repo_name_with_owner=repo_name_with_owner,
            issue_number=issue_number,
            title=title,
            body=body,
            milestone_title=milestone_title,
        )
        issue_url = _build_issue_url(repo_url, issue_number) or str(feature_node.get("gh_issue_url", "")).strip() or None

    feature_node["gh_issue_number"] = issue_number
    feature_node["gh_issue_url"] = issue_url
    return {
        "action": action,
        "gh_issue_number": issue_number,
        "gh_issue_url": issue_url,
        "feature_id": feature_id,
        "milestone_title": milestone_title,
    }


def _build_feature_registration_issue_body(feature_node: dict[str, Any]) -> str:
    """Build issue-focused body for feature-level GitHub issue registration/update."""
    feature_title = str(feature_node.get("title", "")).strip() or str(feature_node.get("id", "")).strip()
    lines = [
        "## Scope",
        feature_title,
        "",
        "## Planned work/issues",
    ]
    issues = feature_node.get("issues", [])
    if isinstance(issues, list) and issues:
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            issue_id = str(issue.get("id", "")).strip()
            issue_title = str(issue.get("title", "")).strip()
            issue_label = f"{issue_id}: {issue_title}" if issue_id else issue_title
            checkbox = "x" if str(issue.get("status", "")) == "Done" else " "
            lines.append(f"- [{checkbox}] {issue_label or 'Issue details pending local sync.'}")
    else:
        lines.append("- [ ] Local feature has no mapped issues yet.")
    return "\n".join(lines).strip() + "\n"


def _resolve_github_repository(root_dir: Path) -> dict[str, str]:
    """Resolve GitHub repository metadata from gh CLI context."""
    command = ["gh", "repo", "view", "--json", "nameWithOwner,url"]
    output = _run_checked_command(command, cwd=root_dir, error_prefix="Failed to resolve GitHub repository")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise WorkflowCommandError(f"Invalid JSON from gh repo view: {error}", exit_code=5) from error
    name_with_owner = str(payload.get("nameWithOwner", "")).strip()
    url = str(payload.get("url", "")).strip()
    if not name_with_owner:
        raise WorkflowCommandError("gh repo view did not return nameWithOwner.", exit_code=5)
    return {"name_with_owner": name_with_owner, "url": url}


def _ensure_github_milestone_exists(
    repo_name_with_owner: str,
    milestone_title: str,
    milestone_id: str,
) -> None:
    """Require that the mapped GitHub milestone title exists before materialization."""
    command = ["gh", "api", f"repos/{repo_name_with_owner}/milestones?state=all&per_page=100"]
    output = _run_checked_command(
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


def _gh_issue_create(
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
    output = _run_checked_command(command, cwd=None, error_prefix="Failed to create GitHub issue")
    created_url = output.strip().splitlines()[-1].strip() if output.strip() else ""
    if not created_url:
        raise WorkflowCommandError("gh issue create returned empty output.", exit_code=5)
    return created_url


def _gh_issue_edit(
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
    _run_checked_command(command, cwd=None, error_prefix=f"Failed to update GitHub issue #{issue_number}")


def _run_checked_command(command: list[str], cwd: Path | None, error_prefix: str) -> str:
    """Run one subprocess command and return stdout or raise workflow error."""
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


def _checkout_canonical_feature_branch(root_dir: Path, branch_name: str) -> str:
    """Resolve and checkout the canonical feature branch using protocol branch order."""
    if _git_ref_exists(root_dir, f"refs/heads/{branch_name}"):
        _run_checked_command(
            ["git", "checkout", branch_name],
            cwd=root_dir,
            error_prefix=f"Failed to checkout existing branch {branch_name}",
        )
        return "checked-out-local"

    remote_ref = f"refs/remotes/origin/{branch_name}"
    if _git_ref_exists(root_dir, remote_ref):
        _run_checked_command(
            ["git", "checkout", "-b", branch_name, "--track", f"origin/{branch_name}"],
            cwd=root_dir,
            error_prefix=f"Failed to create tracking branch from origin/{branch_name}",
        )
        return "created-tracking-from-local-remote-ref"

    remote_heads = _run_checked_command(
        ["git", "ls-remote", "--heads", "origin", branch_name],
        cwd=root_dir,
        error_prefix="Failed to query remote branch heads",
    )
    if remote_heads:
        _run_checked_command(
            ["git", "checkout", "-b", branch_name, "--track", f"origin/{branch_name}"],
            cwd=root_dir,
            error_prefix=f"Failed to create tracking branch from origin/{branch_name}",
        )
        return "created-tracking-from-remote"

    _run_checked_command(
        ["git", "checkout", "-b", branch_name],
        cwd=root_dir,
        error_prefix=f"Failed to create branch {branch_name}",
    )
    return "created-local"


def _plan_canonical_feature_branch(root_dir: Path, branch_name: str) -> str:
    """Plan canonical branch action without mutating repository state."""
    if _git_ref_exists(root_dir, f"refs/heads/{branch_name}"):
        return "would-checkout-local"
    if _git_ref_exists(root_dir, f"refs/remotes/origin/{branch_name}"):
        return "would-create-tracking-from-local-remote-ref"
    return "would-create-local"


def _git_ref_exists(root_dir: Path, ref_name: str) -> bool:
    """Check whether a Git ref exists locally."""
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref_name],
        check=False,
        cwd=str(root_dir),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _resolve_repository_url(root_dir: Path, feature_node: dict[str, Any]) -> str | None:
    """Resolve canonical repository URL for branch linkage persistence."""
    feature_issue_url = str(feature_node.get("gh_issue_url", "")).strip()
    url_from_feature = _extract_repo_url_from_issue_url(feature_issue_url)
    if url_from_feature is not None:
        return url_from_feature
    for issue in feature_node.get("issues", []):
        issue_url = str(issue.get("gh_issue_url", "")).strip()
        url_from_issue = _extract_repo_url_from_issue_url(issue_url)
        if url_from_issue is not None:
            return url_from_issue
    result = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(root_dir),
    )
    if result.returncode != 0:
        return None
    return _normalize_repository_url(result.stdout.strip())


def _extract_repo_url_from_issue_url(issue_url: str) -> str | None:
    """Extract repository web URL from a GitHub issue URL."""
    match = re.match(r"^(https?://github\.com/[^/]+/[^/]+)/issues/\d+\s*$", issue_url)
    if match is None:
        return None
    return _normalize_repository_url(match.group(1))


def _normalize_repository_url(raw_url: str) -> str | None:
    """Normalize repository remote URL to canonical web URL when possible."""
    value = raw_url.strip()
    if not value:
        return None
    ssh_match = re.match(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", value)
    if ssh_match is not None:
        owner = ssh_match.group("owner")
        repo = ssh_match.group("repo")
        return f"https://github.com/{owner}/{repo}"
    https_match = re.match(r"^(https?://[^ ]+)$", value)
    if https_match is not None:
        cleaned = https_match.group(1)
        if cleaned.endswith(".git"):
            cleaned = cleaned[:-4]
        return cleaned.rstrip("/")
    return None


def _build_branch_url(repo_url: str | None, branch_name: str) -> str | None:
    """Build canonical branch URL from repository URL and branch name."""
    if not repo_url:
        return None
    return f"{repo_url}/tree/{branch_name}"


def _coerce_issue_number(raw_number: Any, raw_url: Any) -> int | None:
    """Normalize issue number from integer field or issue URL fallback."""
    if isinstance(raw_number, int):
        return raw_number
    number_text = str(raw_number or "").strip()
    if number_text.isdigit():
        return int(number_text)
    parsed = _parse_issue_number_from_url(str(raw_url or "").strip())
    return parsed


def _parse_issue_number_from_url(issue_url: str) -> int | None:
    """Parse trailing issue number from a GitHub issue URL."""
    match = re.search(r"/issues/(?P<number>\d+)\s*$", issue_url)
    if match is None:
        return None
    return int(match.group("number"))


def _build_issue_url(repo_url: str | None, issue_number: int) -> str | None:
    """Build issue URL from repository URL and issue number."""
    if not repo_url:
        return None
    return f"{repo_url}/issues/{issue_number}"


def _normalize_id(raw_id: str) -> str:
    """Normalize identifier casing and surrounding whitespace."""
    return raw_id.strip().upper()


def _parse_feature_id(raw_feature_id: str) -> tuple[str, int]:
    """Validate feature ID against schema format and return normalized values."""
    feature_id = _normalize_id(raw_feature_id)
    match = FEATURE_ID_PATTERN.fullmatch(feature_id)
    if match is None:
        raise WorkflowCommandError(
            f"Invalid feature ID {raw_feature_id!r}; expected format F<local>-M<milestone>.",
            exit_code=4,
        )
    return feature_id, int(match.group("milestone_num"))


def _parse_milestone_id(raw_milestone_id: str) -> int:
    """Validate milestone ID and return milestone numeric part."""
    match = MILESTONE_ID_PATTERN.fullmatch(raw_milestone_id)
    if match is None:
        raise WorkflowCommandError(
            f"Invalid milestone ID {raw_milestone_id!r}; expected format M<milestone>.",
            exit_code=4,
        )
    return int(match.group("milestone_num"))


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


def _find_milestone(dev_map: dict[str, Any], milestone_id: str) -> dict[str, Any] | None:
    """Find milestone node by ID."""
    milestones = dev_map.get("milestones", [])
    for milestone in milestones:
        if milestone.get("id") == milestone_id:
            return milestone
    return None


def _resolve_github_milestone_title(milestone_node: dict[str, Any], milestone_id: str) -> str:
    """Resolve mapped GitHub milestone title from DEV_MAP milestone node."""
    title = str(milestone_node.get("title", "")).strip()
    if not title:
        raise WorkflowCommandError(
            f"Milestone {milestone_id} has empty title in DEV_MAP; cannot map to GitHub milestone title.",
            exit_code=4,
        )
    return title


def _find_feature(dev_map: dict[str, Any], feature_id: str) -> dict[str, Any] | None:
    """Find feature node and its parent milestone by feature ID."""
    milestones = dev_map.get("milestones", [])
    for milestone in milestones:
        for feature in milestone.get("features", []):
            if feature.get("id") == feature_id:
                return {"feature": feature, "milestone": milestone}
    return None


def _build_feature_node(feature_id: str, title: str, track: str) -> dict[str, Any]:
    """Build canonical feature node shape for DEV_MAP."""
    return {
        "id": feature_id,
        "title": title.strip(),
        "status": "Planned",
        "track": track.strip(),
        "gh_issue_number": None,
        "gh_issue_url": None,
        "issues": [],
        "branch_name": None,
        "branch_url": None,
    }


def _require_feature_exists(context: WorkflowContext, feature_id: str) -> None:
    """Require feature node existence in DEV_MAP."""
    dev_map = _load_json(context.dev_map_path)
    if _find_feature(dev_map, feature_id) is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)


def _find_h2_section_bounds(text: str, heading: str) -> tuple[int, int] | None:
    """Locate a level-2 markdown section by exact heading text."""
    lines = text.splitlines()
    starts: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        match = SECTION_H2_PATTERN.match(line)
        if match is not None:
            starts.append((match.group(1).strip(), index))
    for index, (title, start_line) in enumerate(starts):
        if title != heading:
            continue
        end_line = len(lines)
        if index + 1 < len(starts):
            end_line = starts[index + 1][1]
        return start_line, end_line
    return None


def _build_feature_plan_scaffold(feature_id: str) -> str:
    """Build default feature plan markdown scaffold."""
    return (
        f"## {feature_id}\n\n"
        "### Dependencies\n"
        "- TODO\n\n"
        "### Decomposition\n"
        "1. TODO\n\n"
        "### Issue/Task Decomposition Assessment\n"
        "- TODO\n"
    )


def _extract_feature_plan_section(feature_plans_path: Path, feature_id: str) -> str:
    """Extract one feature section from FEATURE_PLANS by ID."""
    text = feature_plans_path.read_text(encoding="utf-8")
    bounds = _find_h2_section_bounds(text, feature_id)
    if bounds is None:
        raise WorkflowCommandError(
            f"Feature plan section ## {feature_id} not found in {feature_plans_path}.",
            exit_code=4,
        )
    lines = text.splitlines()
    start_line, end_line = bounds
    return "\n".join(lines[start_line:end_line]) + "\n"


def _lint_plan_section(section_text: str, strict: bool) -> dict[str, list[str]]:
    """Lint required plan headings and content under one feature section."""
    lines = section_text.splitlines()
    heading_indexes: dict[str, int] = {}
    for index, line in enumerate(lines):
        match = SECTION_H3_PATTERN.match(line)
        if match is not None:
            heading_indexes[match.group(1).strip()] = index

    missing_headings = [heading for heading in REQUIRED_PLAN_HEADINGS if heading not in heading_indexes]
    if missing_headings:
        joined = ", ".join(missing_headings)
        raise WorkflowCommandError(f"Plan section is missing required heading(s): {joined}.", exit_code=4)

    messages: list[str] = []
    for heading in REQUIRED_PLAN_HEADINGS:
        start_index = heading_indexes[heading] + 1
        next_indexes = [value for key, value in heading_indexes.items() if value > heading_indexes[heading]]
        end_index = min(next_indexes) if next_indexes else len(lines)
        content_lines = _filter_section_content(lines[start_index:end_index])
        if not content_lines:
            raise WorkflowCommandError(f"Heading {heading!r} must contain non-empty content.", exit_code=4)
        if strict and any("TODO" in line.upper() or "TBD" in line.upper() for line in content_lines):
            raise WorkflowCommandError(
                f"Heading {heading!r} contains TODO/TBD placeholder content under --strict lint.",
                exit_code=4,
            )
        messages.append(f"{heading}:ok")

    return {"messages": messages}


def _filter_section_content(lines: list[str]) -> list[str]:
    """Filter heading section lines to meaningful content lines."""
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("<!--"):
            continue
        result.append(stripped)
    return result


def _collect_feature_tasks(feature_node: dict[str, Any], only_pending: bool) -> list[dict[str, str]]:
    """Collect feature tasks in local issue/task order."""
    collected: list[dict[str, str]] = []
    for issue in feature_node.get("issues", []):
        issue_id = str(issue.get("id", ""))
        for task in issue.get("tasks", []):
            status = str(task.get("status", ""))
            if only_pending and status == "Done":
                continue
            collected.append(
                {
                    "id": str(task.get("id", "")),
                    "issue_id": issue_id,
                    "status": status,
                    "title": str(task.get("title", "")),
                }
            )
    return collected


def _parse_pipeline_execution_order(pipeline_path: Path) -> list[str]:
    """Parse task IDs from pipeline execution sequence section."""
    lines = pipeline_path.read_text(encoding="utf-8").splitlines()
    start_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip().startswith("### Execution sequence"):
            start_index = index
            break
    if start_index is None:
        return []

    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if lines[index].startswith("### "):
            end_index = index
            break

    ordered_ids: list[str] = []
    seen: set[str] = set()
    for line in lines[start_index:end_index]:
        for token in re.findall(r"\*\*([^*]+)\*\*", line):
            for part in token.split("/"):
                candidate = part.strip()
                if TASK_ID_PATTERN.fullmatch(candidate) is None:
                    continue
                if candidate in seen:
                    continue
                ordered_ids.append(candidate)
                seen.add(candidate)
    return ordered_ids


def _apply_pipeline_order(tasks: list[dict[str, str]], pipeline_order: list[str]) -> list[dict[str, str]]:
    """Sort tasks by pipeline sequence, then by original issue/task order."""
    order_index = {task_id: index for index, task_id in enumerate(pipeline_order)}
    decorated: list[tuple[int, int, int, dict[str, str]]] = []
    fallback_start = len(order_index) + 1
    for original_index, task in enumerate(tasks):
        task_id = task.get("id", "")
        if task_id in order_index:
            decorated.append((0, order_index[task_id], original_index, task))
        else:
            decorated.append((1, fallback_start + original_index, original_index, task))
    decorated.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in decorated]
