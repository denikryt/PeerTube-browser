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
from .git_adapter import plan_canonical_feature_branch
from .github_adapter import (
    ensure_github_milestone_exists,
    gh_issue_create,
    gh_issue_edit,
    gh_issue_edit_body,
    gh_issue_view_body,
    resolve_github_repository,
)
from .issue_checklist import append_missing_issue_checklist_rows
from .output import emit_json
from .sync_delta import load_sync_delta, resolve_sync_delta_references
from .tracker_store import load_pipeline_payload, load_task_list_payload, write_pipeline_payload, write_task_list_payload
from .tracker_json_contracts import (
    build_pipeline_contract_payload,
    build_task_list_contract_payload,
    validate_pipeline_contract_payload,
    validate_task_list_contract_payload,
)
from .tracking_writers import apply_pipeline_delta, apply_task_list_delta


FEATURE_ID_PATTERN = re.compile(r"^F(?P<feature_num>\d+)-M(?P<milestone_num>\d+)$")
ISSUE_ID_PATTERN = re.compile(r"^I(?P<issue_num>\d+)-F(?P<feature_num>\d+)-M(?P<milestone_num>\d+)$")
MILESTONE_ID_PATTERN = re.compile(r"^M(?P<milestone_num>\d+)$")
TASK_ID_PATTERN = re.compile(r"^[0-9]+[a-z]?$")
SECTION_H2_PATTERN = re.compile(r"^##\s+([^#].*?)\s*$")
SECTION_H3_PATTERN = re.compile(r"^###\s+([^#].*?)\s*$")
SECTION_H4_PATTERN = re.compile(r"^####\s+([^#].*?)\s*$")
ISSUE_EXECUTION_ORDER_HEADING = "### Issue Execution Order"
ISSUE_ORDER_ROW_PATTERN = re.compile(r"^\d+\.\s+`(?P<issue_id>I\d+-F\d+-M\d+)`\s+-\s+(?P<issue_title>.+\S)\s*$")
ISSUE_PLAN_BLOCK_HEADING_PATTERN = re.compile(
    r"^###\s+(?:Follow-up issue:\s*)?`?(?P<issue_id>I\d+-F\d+-M\d+)`?(?:\s*(?:-|—|:)\s*.+)?\s*$"
)
CANONICAL_ISSUE_PLAN_BLOCK_HEADING_PATTERN = re.compile(r"^###\s+(?P<issue_id>I\d+-F\d+-M\d+)\s+-\s+(?P<issue_title>.+\S)\s*$")
REQUIRED_PLAN_HEADINGS = (
    "Dependencies",
    "Decomposition",
    "Issue/Task Decomposition Assessment",
)
REQUIRED_ISSUE_PLAN_SUBHEADINGS = (
    "Dependencies",
    "Decomposition",
    "Issue/Task Decomposition Assessment",
)
ISSUE_PLANNING_ACTIVE_STATUSES = {"Pending", "Planned", "Tasked"}
ISSUE_TERMINAL_STATUSES = {"Done", "Rejected"}
ISSUE_ALLOWED_PLANNING_STATUSES = ISSUE_PLANNING_ACTIVE_STATUSES | ISSUE_TERMINAL_STATUSES


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

    plan_issue_parser = feature_subparsers.add_parser(
        "plan-issue",
        help="Create or update one canonical issue-plan block in FEATURE_PLANS.",
    )
    plan_issue_parser.add_argument("--id", required=True, help="Issue ID.")
    plan_issue_parser.add_argument("--feature-id", help="Optional owner feature assertion.")
    plan_issue_parser.add_argument("--write", action="store_true", help="Persist plan block update to file.")
    plan_issue_parser.add_argument("--strict", action="store_true", help="Enable strict scoped lint checks.")
    plan_issue_parser.set_defaults(handler=_handle_feature_plan_issue)

    materialize_parser = feature_subparsers.add_parser(
        "materialize",
        help="Materialize local feature issues to GitHub and apply canonical branch policy.",
    )
    materialize_parser.add_argument("--id", required=True, help="Feature ID.")
    materialize_parser.add_argument(
        "--mode",
        required=True,
        choices=["bootstrap", "issues-create", "issues-sync"],
        help="Materialize mode contract.",
    )
    materialize_parser.add_argument(
        "--issue-id",
        action="append",
        default=[],
        help="Optional repeatable child issue selector (queue order is preserved).",
    )
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


def register_plan_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register canonical decomposition commands: `plan tasks for ...`."""
    plan_parser = subparsers.add_parser(
        "plan",
        help="Plan and decompose workflow entities.",
    )
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", required=True)
    tasks_parser = plan_subparsers.add_parser(
        "tasks",
        help="Task decomposition operations.",
    )
    tasks_subparsers = tasks_parser.add_subparsers(dest="plan_tasks_command", required=True)
    for_parser = tasks_subparsers.add_parser(
        "for",
        help="Select decomposition target type.",
    )
    for_subparsers = for_parser.add_subparsers(dest="plan_tasks_target", required=True)

    feature_parser = for_subparsers.add_parser(
        "feature",
        help="Plan tasks for one feature decomposition delta.",
    )
    feature_parser.add_argument("--id", required=True, help="Feature ID.")
    feature_parser.add_argument(
        "--delta-file",
        required=True,
        help="Path to JSON delta describing issue/task and tracker updates.",
    )
    feature_parser.add_argument("--write", action="store_true", help="Persist tracker updates.")
    feature_parser.add_argument(
        "--allocate-task-ids",
        action="store_true",
        help="Allocate numeric IDs from DEV_MAP task_count for token IDs ($token).",
    )
    feature_parser.add_argument(
        "--update-pipeline",
        action="store_true",
        help="Apply pipeline section updates from the delta payload.",
    )
    feature_parser.set_defaults(handler=_handle_plan_tasks_for_feature)

    issue_parser = for_subparsers.add_parser(
        "issue",
        help="Plan tasks for one issue decomposition delta.",
    )
    issue_parser.add_argument("--id", required=True, help="Issue ID.")
    issue_parser.add_argument(
        "--delta-file",
        required=True,
        help="Path to JSON delta describing issue/task and tracker updates.",
    )
    issue_parser.add_argument("--write", action="store_true", help="Persist tracker updates.")
    issue_parser.add_argument(
        "--allocate-task-ids",
        action="store_true",
        help="Allocate numeric IDs from DEV_MAP task_count for token IDs ($token).",
    )
    issue_parser.add_argument(
        "--update-pipeline",
        action="store_true",
        help="Apply pipeline section updates from the delta payload.",
    )
    issue_parser.set_defaults(handler=_handle_plan_tasks_for_issue)


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
            github_repo = resolve_github_repository(context.root_dir)
            ensure_github_milestone_exists(
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
    dev_map = _load_json(context.dev_map_path)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)
    lint_result = _lint_plan_section(
        section_text,
        strict=bool(args.strict),
        feature_id=feature_id,
        feature_node=feature_ref["feature"],
        require_issue_order_for_active=True,
    )
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


def _handle_feature_plan_issue(args: Namespace, context: WorkflowContext) -> int:
    """Handle issue-plan command with deterministic output contract fields."""
    issue_id, _, _ = _parse_issue_id(args.id)
    dev_map = _load_json(context.dev_map_path)
    issue_resolution = _resolve_issue_owner_feature(dev_map=dev_map, issue_id=issue_id)
    feature_id = issue_resolution["feature_id"]
    feature_assertion = str(getattr(args, "feature_id", "")).strip()
    if feature_assertion:
        normalized_feature_assertion, _ = _parse_feature_id(feature_assertion)
        if normalized_feature_assertion != feature_id:
            raise WorkflowCommandError(
                f"plan-issue feature assertion mismatch: issue {issue_id} belongs to {feature_id}, got {normalized_feature_assertion}.",
                exit_code=4,
            )

    emit_json(
        {
            "action": "would-update",
            "command": "feature.plan-issue",
            "feature_id": feature_id,
            "issue_id": issue_id,
            "issue_order_checked": False,
            "issue_order_mutated": False,
            "plan_block_updated": False,
            "strict": bool(args.strict),
            "write": bool(args.write),
        }
    )
    return 0


def _handle_plan_tasks_for_feature(args: Namespace, context: WorkflowContext) -> int:
    """Handle `plan tasks for feature` command by forwarding to decomposition engine."""
    feature_id, _ = _parse_feature_id(args.id)
    setattr(args, "id", feature_id)
    setattr(args, "issue_id_filter", None)
    setattr(args, "command_label", "plan tasks for feature")
    setattr(args, "command_output", "plan.tasks.for.feature")
    return _handle_feature_sync(args, context)


def _handle_plan_tasks_for_issue(args: Namespace, context: WorkflowContext) -> int:
    """Handle `plan tasks for issue` command by resolving owner feature and filtering delta."""
    issue_id, feature_local_num, feature_milestone_num = _parse_issue_id(args.id)
    setattr(args, "id", f"F{feature_local_num}-M{feature_milestone_num}")
    setattr(args, "issue_id_filter", issue_id)
    setattr(args, "command_label", "plan tasks for issue")
    setattr(args, "command_output", "plan.tasks.for.issue")
    return _handle_feature_sync(args, context)


def _handle_feature_sync(args: Namespace, context: WorkflowContext) -> int:
    """Apply manual decomposition delta to local trackers via canonical plan-tasks commands."""
    command_label = str(getattr(args, "command_label", "plan tasks for feature")).strip() or "plan tasks for feature"
    command_output = str(getattr(args, "command_output", "plan.tasks.for.feature")).strip() or "plan.tasks.for.feature"
    feature_id, feature_milestone_num = _parse_feature_id(args.id)
    feature_local_num = _parse_feature_local_num(feature_id)
    dev_map = _load_json(context.dev_map_path)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)

    feature_node = feature_ref["feature"]

    issue_id_filter = _resolve_plan_tasks_issue_filter(
        raw_issue_id=getattr(args, "issue_id_filter", None),
        feature_id=feature_id,
        feature_milestone_num=feature_milestone_num,
        feature_local_num=feature_local_num,
    )
    delta = load_sync_delta(Path(args.delta_file))
    existing_task_locations = _collect_task_locations(dev_map)
    resolved_delta, allocation = resolve_sync_delta_references(
        delta=delta,
        dev_map=dev_map,
        existing_task_locations=existing_task_locations,
        allocate_task_ids=bool(args.allocate_task_ids),
    )
    issue_payloads = _filter_issue_payloads_for_plan_tasks(
        issue_payloads=resolved_delta.get("issues", []),
        issue_id_filter=issue_id_filter,
    )
    _enforce_plan_tasks_issue_status_gate(
        feature_node=feature_node,
        issue_payloads=issue_payloads,
        issue_id_filter=issue_id_filter,
        command_label=command_label,
    )
    issue_counts = _apply_issue_delta(
        feature_node=feature_node,
        feature_id=feature_id,
        feature_milestone_num=feature_milestone_num,
        feature_local_num=feature_local_num,
        statuses=set(dev_map.get("statuses", [])),
        issue_payloads=issue_payloads,
        existing_task_locations=existing_task_locations,
    )
    issue_title_by_id = {
        str(issue.get("id", "")).strip(): str(issue.get("title", "")).strip()
        for issue in feature_node.get("issues", [])
        if isinstance(issue, dict) and str(issue.get("id", "")).strip()
    }
    issue_execution_order_sync = _sync_issue_execution_order_for_new_issues(
        feature_plans_path=context.feature_plans_path,
        feature_id=feature_id,
        created_issue_ids=issue_counts["created_issue_ids"],
        issue_title_by_id=issue_title_by_id,
        write=bool(args.write),
    )
    issue_planning_status_reconciliation = _reconcile_feature_issue_planning_statuses(
        feature_plans_path=context.feature_plans_path,
        feature_id=feature_id,
        feature_node=feature_node,
        write=bool(args.write),
    )

    expected_marker = f"[M{feature_milestone_num}][F{feature_local_num}]"
    task_list_contract_payload = build_task_list_contract_payload(
        resolved_delta.get("task_list_entries", []),
        expected_marker=expected_marker,
    )
    validate_task_list_contract_payload(
        payload=task_list_contract_payload,
        location="plan.tasks.for.task_list_contract",
    )
    pipeline_contract_payload = build_pipeline_contract_payload(resolved_delta.get("pipeline", {}))
    validate_pipeline_contract_payload(
        payload=pipeline_contract_payload,
        location="plan.tasks.for.pipeline_contract",
    )

    task_list_payload = load_task_list_payload(context)
    updated_task_list_payload, task_list_count = apply_task_list_delta(
        task_list_payload=task_list_payload,
        entries=resolved_delta.get("task_list_entries", []),
        expected_marker=expected_marker,
    )

    pipeline_payload = load_pipeline_payload(context)
    updated_pipeline_payload, pipeline_counts = apply_pipeline_delta(
        pipeline_payload=pipeline_payload,
        delta_payload=resolved_delta.get("pipeline", {}),
        update_pipeline=bool(args.update_pipeline),
    )

    task_count_before = int(dev_map.get("task_count", 0))
    if bool(args.write):
        if allocation["task_count_after"] != task_count_before:
            dev_map["task_count"] = allocation["task_count_after"]
        _touch_updated_at(dev_map)
        _write_json(context.dev_map_path, dev_map)
        write_task_list_payload(context, updated_task_list_payload)
        write_pipeline_payload(context, updated_pipeline_payload)

    emit_json(
        {
            "action": "planned-tasks" if bool(args.write) else "would-plan-tasks",
            "allocate_task_ids": bool(args.allocate_task_ids),
            "allocated_task_ids": allocation["allocated_ids"],
            "command": command_output,
            "delta_file": str(Path(args.delta_file)),
            "dev_map_issues_upserted": issue_counts["issues_upserted"],
            "dev_map_tasks_upserted": issue_counts["tasks_upserted"],
            "feature_id": feature_id,
            "issue_id_filter": issue_id_filter,
            "issue_execution_order_sync": issue_execution_order_sync,
            "issue_planning_status_reconciliation": issue_planning_status_reconciliation,
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
    materialize_mode = str(args.mode).strip()
    mode_action = _resolve_materialize_mode_action(materialize_mode)
    feature_local_num = _parse_feature_local_num(feature_id)
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

    all_issue_nodes = feature_node.get("issues", [])
    if not isinstance(all_issue_nodes, list):
        raise WorkflowCommandError(
            f"Feature {feature_id} has invalid issue list in DEV_MAP.",
            exit_code=4,
        )
    issue_id_queue = _resolve_materialize_issue_queue(args.issue_id)
    issue_id_filter = issue_id_queue[0] if len(issue_id_queue) == 1 else None
    issue_nodes: list[dict[str, Any]] = []
    selected_issue_ids: list[str] = []
    if materialize_mode == "bootstrap":
        if issue_id_queue:
            raise WorkflowCommandError(
                "--issue-id is not allowed with --mode bootstrap.",
                exit_code=4,
            )
    else:
        if not all_issue_nodes:
            raise WorkflowCommandError(
                f"Feature {feature_id} has no local issue nodes to materialize.",
                exit_code=4,
            )
        issue_nodes = all_issue_nodes
        if issue_id_queue:
            issue_nodes_by_id = {
                _normalize_id(str(issue_node.get("id", ""))): issue_node
                for issue_node in issue_nodes
            }
            queued_issue_nodes: list[dict[str, Any]] = []
            for queued_issue_id in issue_id_queue:
                _assert_issue_belongs_to_feature(
                    issue_id=queued_issue_id,
                    feature_id=feature_id,
                    feature_milestone_num=feature_milestone_num,
                    feature_local_num=feature_local_num,
                )
                matched_issue_node = issue_nodes_by_id.get(queued_issue_id)
                if matched_issue_node is None:
                    raise WorkflowCommandError(
                        f"Issue {queued_issue_id} was not found in feature {feature_id}.",
                        exit_code=4,
                    )
                queued_issue_nodes.append(matched_issue_node)
            issue_nodes = queued_issue_nodes
        selected_issue_ids = [
            _normalize_id(str(issue_node.get("id", "")))
            for issue_node in issue_nodes
            if _normalize_id(str(issue_node.get("id", "")))
        ]
        _enforce_materialize_issue_status_gate(issue_nodes)

    branch_name = f"feature/{feature_id}"
    repo_url = _resolve_repository_url(context.root_dir, feature_node)
    branch_url = _build_branch_url(repo_url, branch_name)
    branch_action = plan_canonical_feature_branch(context.root_dir, branch_name)

    materialized_issues: list[dict[str, Any]] = []
    feature_issue_checklist_sync: dict[str, Any] = {
        "attempted": False,
        "updated": False,
        "added_issue_ids": [],
    }
    github_repo_name_with_owner: str | None = None
    if materialize_mode != "bootstrap":
        if bool(args.write) and bool(args.github):
            github_repo = resolve_github_repository(context.root_dir)
            github_repo_name_with_owner = github_repo["name_with_owner"]
            ensure_github_milestone_exists(
                repo_name_with_owner=github_repo_name_with_owner,
                milestone_title=milestone_title,
                milestone_id=milestone_id,
            )
            for issue_node in issue_nodes:
                issue_id = str(issue_node.get("id", "")).strip()
                issue_number = _coerce_issue_number(
                    issue_node.get("gh_issue_number"),
                    issue_node.get("gh_issue_url"),
                )
                issue_url = str(issue_node.get("gh_issue_url", "")).strip() or None
                issue_is_mapped = issue_number is not None and issue_url is not None
                if materialize_mode == "issues-create" and issue_is_mapped:
                    materialized_issues.append(
                        {
                            "action": "skipped",
                            "issue_id": issue_id,
                            "gh_issue_number": issue_number,
                            "gh_issue_url": issue_url,
                            "mode_action": mode_action,
                            "reason": "already-materialized-create-only",
                        }
                    )
                    continue
                materialized = _materialize_feature_issue_node(
                    issue_node=issue_node,
                    milestone_title=milestone_title,
                    repo_name_with_owner=github_repo_name_with_owner,
                    repo_url=_normalize_repository_url(str(github_repo.get("url", ""))),
                )
                materialized["mode_action"] = mode_action
                materialized_issues.append(materialized)
        else:
            for issue_node in issue_nodes:
                issue_id = str(issue_node.get("id", ""))
                issue_number = _coerce_issue_number(
                    issue_node.get("gh_issue_number"),
                    issue_node.get("gh_issue_url"),
                )
                issue_url = str(issue_node.get("gh_issue_url", "")).strip() or None
                issue_is_mapped = issue_number is not None and issue_url is not None
                if materialize_mode == "issues-create" and issue_is_mapped:
                    action = "would-skip"
                else:
                    action = "would-update" if issue_number else "would-create"
                materialized_issues.append(
                    {
                        "action": action,
                        "issue_id": issue_id,
                        "gh_issue_number": issue_number,
                        "gh_issue_url": issue_url,
                        "mode_action": mode_action,
                    }
                )

    if bool(args.write) and bool(args.github) and github_repo_name_with_owner is not None and issue_nodes:
        feature_issue_checklist_sync = _sync_feature_issue_checklist_after_materialize(
            feature_node=feature_node,
            issue_nodes=issue_nodes,
            repo_name_with_owner=github_repo_name_with_owner,
        )

    if bool(args.write):
        feature_node["branch_name"] = branch_name
        feature_node["branch_url"] = branch_url
        _touch_updated_at(dev_map)
        _write_json(context.dev_map_path, dev_map)

    active_branch_message = f"Canonical feature branch: {branch_name}"
    emit_json(
        {
            "active_feature_branch": branch_name,
            "active_feature_branch_message": active_branch_message,
            "branch_action": branch_action,
            "branch_url": branch_url,
            "command": "feature.materialize",
            "feature_id": feature_id,
            "feature_issue_checklist_sync": feature_issue_checklist_sync,
            "feature_status": feature_status,
            "github_enabled": bool(args.github),
            "issue_id_filter": issue_id_filter,
            "issue_id_queue": issue_id_queue,
            "selected_issue_ids": selected_issue_ids,
            "mode": materialize_mode,
            "mode_action": mode_action,
            "issues_materialized": materialized_issues,
            "github_milestone_title": milestone_title,
            "milestone_id": milestone_id,
            "write": bool(args.write),
        }
    )
    return 0


def _sync_feature_issue_checklist_after_materialize(
    feature_node: dict[str, Any],
    issue_nodes: list[dict[str, Any]],
    repo_name_with_owner: str,
) -> dict[str, Any]:
    """Append missing child-issue checklist rows in mapped feature-level GitHub issue."""
    feature_issue_number = _coerce_issue_number(
        feature_node.get("gh_issue_number"),
        feature_node.get("gh_issue_url"),
    )
    feature_issue_url = str(feature_node.get("gh_issue_url", "")).strip()
    if feature_issue_number is None or not feature_issue_url:
        return {
            "attempted": False,
            "updated": False,
            "added_issue_ids": [],
            "feature_issue_number": None,
            "reason": "feature-issue-not-mapped",
        }

    current_body = gh_issue_view_body(repo_name_with_owner, feature_issue_number)
    updated_body, added_issue_ids = append_missing_issue_checklist_rows(current_body, issue_nodes)
    if not added_issue_ids:
        return {
            "attempted": True,
            "updated": False,
            "added_issue_ids": [],
            "feature_issue_number": feature_issue_number,
        }

    gh_issue_edit_body(repo_name_with_owner, feature_issue_number, updated_body)
    return {
        "attempted": True,
        "updated": True,
        "added_issue_ids": added_issue_ids,
        "feature_issue_number": feature_issue_number,
    }


def _handle_feature_execution_plan(args: Namespace, context: WorkflowContext) -> int:
    """Build ordered task execution plan for one feature subtree."""
    feature_id, _ = _parse_feature_id(args.id)
    dev_map = _load_json(context.dev_map_path)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)
    feature_node = feature_ref["feature"]
    feature_status = str(feature_node.get("status", ""))

    ordered_tasks = _collect_feature_tasks(feature_node, only_pending=bool(args.only_pending))
    if bool(args.from_pipeline):
        pipeline_order = _parse_pipeline_execution_order(load_pipeline_payload(context))
        ordered_tasks = _apply_pipeline_order(ordered_tasks, pipeline_order)
    section_text = _extract_feature_plan_section(context.feature_plans_path, feature_id)
    issue_order_state = _resolve_issue_execution_order_state(
        section_text=section_text,
        feature_id=feature_id,
        feature_node=feature_node,
        require_issue_order_for_active=False,
    )

    emit_json(
        {
            "command": "feature.execution-plan",
            "feature_id": feature_id,
            "feature_status": feature_status,
            "from_pipeline": bool(args.from_pipeline),
            "issue_execution_order": issue_order_state["rows"],
            "next_issue_from_plan_order": issue_order_state["next_issue"],
            "only_pending": bool(args.only_pending),
            "task_count": len(ordered_tasks),
            "tasks": ordered_tasks,
        }
    )
    return 0


def _parse_feature_local_num(feature_id: str) -> int:
    """Extract the local feature number from an already validated feature ID."""
    match = FEATURE_ID_PATTERN.fullmatch(feature_id)
    if match is None:
        raise WorkflowCommandError(f"Cannot parse feature local number from {feature_id}.", exit_code=4)
    return int(match.group("feature_num"))


def _resolve_materialize_issue_queue(raw_issue_ids: Any) -> list[str]:
    """Normalize optional materialize issue-id queue in user-provided order."""
    if raw_issue_ids is None:
        return []
    if not isinstance(raw_issue_ids, list):
        raw_issue_ids = [raw_issue_ids]
    issue_id_queue: list[str] = []
    seen_issue_ids: set[str] = set()
    for raw_issue_id in raw_issue_ids:
        issue_id = _normalize_id(str(raw_issue_id))
        if ISSUE_ID_PATTERN.fullmatch(issue_id) is None:
            raise WorkflowCommandError(
                f"Invalid --issue-id value {raw_issue_id!r}; expected I<local>-F<feature_local>-M<milestone>.",
                exit_code=4,
            )
        if issue_id in seen_issue_ids:
            raise WorkflowCommandError(
                f"Duplicate --issue-id value {issue_id}; provide each issue once in queue order.",
                exit_code=4,
            )
        seen_issue_ids.add(issue_id)
        issue_id_queue.append(issue_id)
    return issue_id_queue


def _resolve_materialize_mode_action(materialize_mode: str) -> str:
    """Return explicit mode-action label for materialize command output."""
    if materialize_mode == "bootstrap":
        return "branch-bootstrap-only"
    if materialize_mode == "issues-create":
        return "issue-materialization-create-mode"
    if materialize_mode == "issues-sync":
        return "issue-materialization-sync-mode"
    raise WorkflowCommandError(f"Unsupported materialize mode: {materialize_mode!r}.", exit_code=4)


def _enforce_materialize_issue_status_gate(issue_nodes: list[dict[str, Any]]) -> None:
    """Require Tasked status for issues selected for materialize create/sync modes."""
    non_tasked_statuses: list[str] = []
    for issue_node in issue_nodes:
        issue_id = str(issue_node.get("id", "")).strip() or "<unknown-issue>"
        issue_status = str(issue_node.get("status", "")).strip() or "Pending"
        if issue_status != "Tasked":
            non_tasked_statuses.append(f"{issue_id}(status={issue_status!r})")
    if non_tasked_statuses:
        raise WorkflowCommandError(
            "feature materialize requires status 'Tasked' for selected issue nodes; "
            "run plan tasks for issue/feature first for: "
            + ", ".join(non_tasked_statuses)
            + ".",
            exit_code=4,
        )


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


def _resolve_plan_tasks_issue_filter(
    raw_issue_id: Any,
    *,
    feature_id: str,
    feature_milestone_num: int,
    feature_local_num: int,
) -> str | None:
    """Normalize and validate optional issue filter against selected feature."""
    if raw_issue_id is None:
        return None
    issue_id, issue_feature_num, issue_milestone_num = _parse_issue_id(str(raw_issue_id))
    if issue_feature_num != feature_local_num or issue_milestone_num != feature_milestone_num:
        raise WorkflowCommandError(
            f"Issue filter {issue_id} does not belong to feature {feature_id}.",
            exit_code=4,
        )
    return issue_id


def _filter_issue_payloads_for_plan_tasks(
    issue_payloads: list[dict[str, Any]],
    issue_id_filter: str | None,
) -> list[dict[str, Any]]:
    """Restrict delta issue payloads to one issue when issue-scoped decomposition is requested."""
    if issue_id_filter is None:
        return issue_payloads
    filtered_payloads: list[dict[str, Any]] = []
    for issue_index, issue_payload in enumerate(issue_payloads):
        payload_issue_id = _required_string_field(issue_payload, "id", f"issues[{issue_index}]")
        if payload_issue_id != issue_id_filter:
            raise WorkflowCommandError(
                "plan tasks for issue delta contains non-target issue "
                f"{payload_issue_id}; expected only {issue_id_filter}.",
                exit_code=4,
            )
        filtered_payloads.append(issue_payload)
    return filtered_payloads


def _enforce_plan_tasks_issue_status_gate(
    *,
    feature_node: dict[str, Any],
    issue_payloads: list[dict[str, Any]],
    issue_id_filter: str | None,
    command_label: str,
) -> None:
    """Reject decomposition updates for pending/missing issue nodes."""
    issues = feature_node.get("issues", [])
    if not isinstance(issues, list):
        raise WorkflowCommandError("Feature issue list is invalid in DEV_MAP.", exit_code=4)
    issue_status_by_id = {
        str(issue.get("id", "")).strip(): str(issue.get("status", "")).strip() or "Pending"
        for issue in issues
        if isinstance(issue, dict) and str(issue.get("id", "")).strip()
    }
    target_issue_ids: list[str] = []
    for issue_index, issue_payload in enumerate(issue_payloads):
        payload_issue_id = _required_string_field(issue_payload, "id", f"issues[{issue_index}]")
        if payload_issue_id not in target_issue_ids:
            target_issue_ids.append(payload_issue_id)
    if issue_id_filter is not None and issue_id_filter not in target_issue_ids:
        target_issue_ids.append(issue_id_filter)

    for issue_id in target_issue_ids:
        issue_status = issue_status_by_id.get(issue_id)
        if issue_status is None:
            raise WorkflowCommandError(
                f"{command_label} requires existing issue {issue_id}; run plan issue {issue_id} first.",
                exit_code=4,
            )
        if issue_status == "Pending":
            raise WorkflowCommandError(
                f"{command_label} cannot run for issue {issue_id} with status 'Pending'; run plan issue {issue_id} first.",
                exit_code=4,
            )


def _apply_issue_delta(
    feature_node: dict[str, Any],
    feature_id: str,
    feature_milestone_num: int,
    feature_local_num: int,
    statuses: set[str],
    issue_payloads: list[dict[str, Any]],
    existing_task_locations: dict[str, str],
) -> dict[str, Any]:
    """Upsert issue/task nodes from decomposition payload into feature subtree."""
    issues = feature_node.setdefault("issues", [])
    issues_by_id = {str(issue.get("id", "")): issue for issue in issues}
    issue_upsert_count = 0
    task_upsert_count = 0
    created_issue_ids: list[str] = []
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
                "status": "Pending",
                "gh_issue_number": None,
                "gh_issue_url": None,
                "tasks": [],
            }
            issues.append(issue_node)
            issues_by_id[issue_id] = issue_node
            issue_created = True
            created_issue_ids.append(issue_id)
        issue_upsert_count += 1 if issue_created else 0

        if "title" in issue_payload:
            issue_node["title"] = _required_string_field(issue_payload, "title", f"issues[{issue_index}]")
        if "status" in issue_payload:
            status_value = _required_string_field(issue_payload, "status", f"issues[{issue_index}]")
            _validate_issue_planning_status_transition(
                issue_id=issue_id,
                status_before=str(issue_node.get("status", "")).strip() or None,
                status_after=status_value,
                location=f"issues[{issue_index}].status",
            )
            _validate_issue_planning_status_value(status_value, f"issues[{issue_index}].status")
            _validate_status_value(status_value, statuses | ISSUE_ALLOWED_PLANNING_STATUSES, f"issues[{issue_index}].status")
            issue_node["status"] = status_value

        task_payloads = issue_payload.get("tasks", [])
        if not isinstance(task_payloads, list):
            raise WorkflowCommandError(f"issues[{issue_index}].tasks must be a list.", exit_code=4)
        tasks = issue_node.setdefault("tasks", [])
        tasks_by_id = {str(task.get("id", "")): task for task in tasks}
        issue_task_upsert_count = 0
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
            issue_task_upsert_count += 1
        if issue_task_upsert_count > 0 and str(issue_node.get("status", "")).strip() not in ISSUE_TERMINAL_STATUSES:
            issue_node["status"] = "Tasked"
    return {
        "created_issue_ids": created_issue_ids,
        "issues_upserted": issue_upsert_count,
        "tasks_upserted": task_upsert_count,
    }


def _validate_issue_planning_status_value(status: str, location: str) -> None:
    """Validate issue planning status against canonical Pending/Planned contract."""
    if status in ISSUE_ALLOWED_PLANNING_STATUSES:
        return
    allowed = ", ".join(sorted(ISSUE_ALLOWED_PLANNING_STATUSES))
    raise WorkflowCommandError(
        f"Invalid planning status at {location}: {status!r}. Allowed planning statuses: {allowed}.",
        exit_code=4,
    )


def _validate_issue_planning_status_transition(
    issue_id: str,
    status_before: str | None,
    status_after: str,
    location: str,
) -> None:
    """Reject decomposition-driven transitions that mutate terminal issue statuses."""
    if status_before not in ISSUE_TERMINAL_STATUSES:
        return
    if status_after == status_before:
        return
    raise WorkflowCommandError(
        "Invalid planning-status transition at "
        f"{location} for {issue_id}: {status_before!r} -> {status_after!r}. "
        "Terminal issue statuses ('Done', 'Rejected') cannot be changed by decomposition updates.",
        exit_code=4,
    )


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
        created_url = gh_issue_create(
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
        gh_issue_edit(
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
        created_url = gh_issue_create(
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
        gh_issue_edit(
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


def _parse_issue_id(raw_issue_id: str) -> tuple[str, int, int]:
    """Validate issue ID and return normalized ID with feature/milestone numbers."""
    issue_id = _normalize_id(raw_issue_id)
    match = ISSUE_ID_PATTERN.fullmatch(issue_id)
    if match is None:
        raise WorkflowCommandError(
            f"Invalid issue ID {raw_issue_id!r}; expected format I<local>-F<feature_local>-M<milestone>.",
            exit_code=4,
        )
    return issue_id, int(match.group("feature_num")), int(match.group("milestone_num"))


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


def _resolve_issue_owner_feature(dev_map: dict[str, Any], issue_id: str) -> dict[str, Any]:
    """Resolve issue node and owning feature from DEV_MAP with uniqueness checks."""
    matches: list[dict[str, Any]] = []
    for milestone in dev_map.get("milestones", []):
        for feature in milestone.get("features", []):
            feature_id = str(feature.get("id", "")).strip()
            issues = feature.get("issues", [])
            if not isinstance(issues, list):
                continue
            for issue in issues:
                candidate_issue_id = str(issue.get("id", "")).strip()
                if candidate_issue_id != issue_id:
                    continue
                matches.append(
                    {
                        "feature": feature,
                        "feature_id": feature_id,
                        "issue": issue,
                        "milestone": milestone,
                    }
                )
    if not matches:
        raise WorkflowCommandError(f"Issue {issue_id} not found in DEV_MAP.", exit_code=4)
    if len(matches) > 1:
        owner_ids = ", ".join(sorted({str(match["feature_id"]) for match in matches}))
        raise WorkflowCommandError(
            f"Issue {issue_id} has multiple owner matches in DEV_MAP: {owner_ids}.",
            exit_code=4,
        )
    return matches[0]


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


def _lint_plan_section(
    section_text: str,
    strict: bool,
    *,
    feature_id: str | None = None,
    feature_node: dict[str, Any] | None = None,
    require_issue_order_for_active: bool = False,
) -> dict[str, list[str]]:
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

    if feature_id is not None and feature_node is not None:
        _lint_issue_plan_blocks(
            section_text=section_text,
            feature_id=feature_id,
            feature_node=feature_node,
        )
        messages.append("Issue Plan Blocks:ok")
        issue_order_state = _resolve_issue_execution_order_state(
            section_text=section_text,
            feature_id=feature_id,
            feature_node=feature_node,
            require_issue_order_for_active=require_issue_order_for_active,
        )
        issue_planning_mismatches = _collect_issue_planning_status_mismatches(
            feature_node=feature_node,
            issue_plan_block_ids=_extract_issue_plan_block_ids(section_text),
        )
        if issue_planning_mismatches:
            mismatch_tokens = [
                (
                    f"{item['issue_id']}(status={item['status_before']!r}, "
                    f"expected={item['status_expected']!r}, has_plan_block={item['has_plan_block']})"
                )
                for item in issue_planning_mismatches
            ]
            raise WorkflowCommandError(
                "Issue planning status mismatch: " + "; ".join(mismatch_tokens) + ".",
                exit_code=4,
            )
        messages.append("Issue Planning Status:ok")
        if issue_order_state["rows"]:
            messages.append("Issue Execution Order:ok")
        elif issue_order_state["active_issue_count"] == 0:
            messages.append("Issue Execution Order:skipped(no-active-issues)")

    return {"messages": messages}


def _resolve_issue_execution_order_state(
    section_text: str,
    feature_id: str,
    feature_node: dict[str, Any],
    *,
    require_issue_order_for_active: bool,
) -> dict[str, Any]:
    """Parse and validate issue execution order rows against active DEV_MAP issues."""
    issue_nodes = feature_node.get("issues", [])
    issue_by_id: dict[str, dict[str, Any]] = {}
    active_issue_ids: set[str] = set()
    for issue in issue_nodes:
        if not isinstance(issue, dict):
            continue
        issue_id = str(issue.get("id", "")).strip()
        if not issue_id:
            continue
        issue_by_id[issue_id] = issue
        issue_status = str(issue.get("status", "")).strip()
        if issue_status not in {"Done", "Rejected"}:
            active_issue_ids.add(issue_id)

    order_block_found, parsed_rows = _parse_issue_execution_order_rows(section_text)
    if require_issue_order_for_active and active_issue_ids and not order_block_found:
        raise WorkflowCommandError(
            f"Feature {feature_id} plan is missing {ISSUE_EXECUTION_ORDER_HEADING} with ordered active issues.",
            exit_code=4,
        )
    if not order_block_found:
        return {
            "active_issue_count": len(active_issue_ids),
            "next_issue": None,
            "rows": [],
        }

    feature_local_num = _parse_feature_local_num(feature_id)
    _, feature_milestone_num = _parse_feature_id(feature_id)
    order_issue_ids: list[str] = []
    seen_issue_ids: set[str] = set()
    for row in parsed_rows:
        issue_id = row["id"]
        _assert_issue_belongs_to_feature(
            issue_id=issue_id,
            feature_id=feature_id,
            feature_milestone_num=feature_milestone_num,
            feature_local_num=feature_local_num,
        )
        if issue_id in seen_issue_ids:
            raise WorkflowCommandError(
                f"Issue Execution Order contains duplicate issue ID {issue_id}.",
                exit_code=4,
            )
        seen_issue_ids.add(issue_id)
        order_issue_ids.append(issue_id)
        issue_node = issue_by_id.get(issue_id)
        if issue_node is None:
            raise WorkflowCommandError(
                f"Issue Execution Order references unknown issue {issue_id} for feature {feature_id}.",
                exit_code=4,
            )

    stale_issue_ids = sorted(issue_id for issue_id in order_issue_ids if issue_id not in active_issue_ids)
    if stale_issue_ids:
        raise WorkflowCommandError(
            "Issue Execution Order contains stale issue IDs (not active): "
            + ", ".join(stale_issue_ids)
            + ".",
            exit_code=4,
        )

    missing_issue_ids = sorted(active_issue_ids - set(order_issue_ids))
    if missing_issue_ids:
        raise WorkflowCommandError(
            "Issue Execution Order is missing active issues from DEV_MAP: "
            + ", ".join(missing_issue_ids)
            + ".",
            exit_code=4,
        )

    normalized_rows: list[dict[str, str]] = []
    for issue_id in order_issue_ids:
        issue_title = str(issue_by_id[issue_id].get("title", "")).strip()
        issue_status = str(issue_by_id[issue_id].get("status", "")).strip()
        normalized_rows.append(
            {
                "id": issue_id,
                "title": issue_title,
                "status": issue_status,
            }
        )

    next_issue = normalized_rows[0] if normalized_rows else None
    return {
        "active_issue_count": len(active_issue_ids),
        "next_issue": next_issue,
        "rows": normalized_rows,
    }


def _parse_issue_execution_order_rows(section_text: str) -> tuple[bool, list[dict[str, str]]]:
    """Parse `Issue Execution Order` rows from one feature plan section."""
    lines = section_text.splitlines()
    heading_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == ISSUE_EXECUTION_ORDER_HEADING:
            heading_index = index
            break
    if heading_index is None:
        return False, []

    rows: list[dict[str, str]] = []
    for raw_line in lines[heading_index + 1 :]:
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("<!--"):
            continue
        if stripped.startswith("### ") or stripped.startswith("## "):
            break
        match = ISSUE_ORDER_ROW_PATTERN.fullmatch(stripped)
        if match is None:
            raise WorkflowCommandError(
                f"Invalid Issue Execution Order row format: {stripped!r}.",
                exit_code=4,
            )
        issue_id = match.group("issue_id").strip()
        issue_title = match.group("issue_title").strip()
        rows.append(
            {
                "id": issue_id,
                "title": issue_title,
            }
        )
    if not rows:
        raise WorkflowCommandError(
            f"{ISSUE_EXECUTION_ORDER_HEADING} must contain at least one ordered issue row.",
            exit_code=4,
        )
    return True, rows


def _sync_issue_execution_order_for_new_issues(
    feature_plans_path: Path,
    feature_id: str,
    created_issue_ids: list[str],
    issue_title_by_id: dict[str, str],
    write: bool,
) -> dict[str, Any]:
    """Append newly created issue IDs to feature plan `Issue Execution Order` block."""
    if not created_issue_ids:
        return {
            "added_issue_ids": [],
            "attempted": False,
            "block_created": False,
            "updated": False,
        }

    text = feature_plans_path.read_text(encoding="utf-8")
    bounds = _find_h2_section_bounds(text, feature_id)
    if bounds is None:
        raise WorkflowCommandError(
            f"Feature plan section ## {feature_id} not found in {feature_plans_path}.",
            exit_code=4,
        )
    lines = text.splitlines()
    start_line, end_line = bounds

    heading_index: int | None = None
    for index in range(start_line + 1, end_line):
        if lines[index].strip() == ISSUE_EXECUTION_ORDER_HEADING:
            heading_index = index
            break

    if heading_index is None:
        if not write:
            return {
                "added_issue_ids": list(created_issue_ids),
                "attempted": True,
                "block_created": True,
                "updated": True,
            }
        insert_at = start_line + 1
        new_block = ["", ISSUE_EXECUTION_ORDER_HEADING]
        for index, issue_id in enumerate(created_issue_ids, start=1):
            issue_title = issue_title_by_id.get(issue_id, "").strip() or issue_id
            new_block.append(_format_issue_execution_order_row(index, issue_id, issue_title))
        new_block.append("")
        lines[insert_at:insert_at] = new_block
        feature_plans_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {
            "added_issue_ids": list(created_issue_ids),
            "attempted": True,
            "block_created": True,
            "updated": True,
        }

    rows_start = heading_index + 1
    rows_end = rows_start
    while rows_end < end_line:
        stripped = lines[rows_end].strip()
        if stripped.startswith("### ") or stripped.startswith("## "):
            break
        rows_end += 1

    existing_issue_ids: list[str] = []
    existing_issue_titles: dict[str, str] = {}
    for raw_line in lines[rows_start:rows_end]:
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("<!--"):
            continue
        match = ISSUE_ORDER_ROW_PATTERN.fullmatch(stripped)
        if match is None:
            raise WorkflowCommandError(
                f"Invalid Issue Execution Order row format while syncing new issues: {stripped!r}.",
                exit_code=4,
            )
        issue_id = match.group("issue_id").strip()
        issue_title = match.group("issue_title").strip()
        existing_issue_ids.append(issue_id)
        existing_issue_titles[issue_id] = issue_title

    added_issue_ids = [issue_id for issue_id in created_issue_ids if issue_id not in existing_issue_ids]
    if not added_issue_ids:
        return {
            "added_issue_ids": [],
            "attempted": True,
            "block_created": False,
            "updated": False,
        }
    if not write:
        return {
            "added_issue_ids": added_issue_ids,
            "attempted": True,
            "block_created": False,
            "updated": True,
        }

    ordered_issue_ids = existing_issue_ids + added_issue_ids
    replacement_rows: list[str] = []
    for index, issue_id in enumerate(ordered_issue_ids, start=1):
        issue_title = issue_title_by_id.get(issue_id, "").strip() or existing_issue_titles.get(issue_id, "").strip() or issue_id
        replacement_rows.append(_format_issue_execution_order_row(index, issue_id, issue_title))
    lines[rows_start:rows_end] = replacement_rows
    feature_plans_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "added_issue_ids": added_issue_ids,
        "attempted": True,
        "block_created": False,
        "updated": True,
    }


def _reconcile_feature_issue_planning_statuses(
    feature_plans_path: Path,
    feature_id: str,
    feature_node: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    """Reconcile active issue statuses from issue-plan block coverage in FEATURE_PLANS."""
    section_text = _extract_feature_plan_section(feature_plans_path, feature_id)
    issue_plan_block_ids = _extract_issue_plan_block_ids(section_text)
    reconciled_issue_ids: list[str] = []
    active_issue_count = 0

    issues = feature_node.get("issues", [])
    if not isinstance(issues, list):
        raise WorkflowCommandError(f"Feature {feature_id} has invalid issue list in DEV_MAP.", exit_code=4)
    active_issue_count = _count_active_issues(feature_node)
    mismatches = _collect_issue_planning_status_mismatches(
        feature_node=feature_node,
        issue_plan_block_ids=issue_plan_block_ids,
    )
    if write:
        issues_by_id = {
            str(issue.get("id", "")).strip(): issue
            for issue in issues
            if isinstance(issue, dict) and str(issue.get("id", "")).strip()
        }
        for mismatch in mismatches:
            issue_id = mismatch["issue_id"]
            issue = issues_by_id.get(issue_id)
            if issue is None:
                continue
            issue["status"] = mismatch["status_expected"]
            reconciled_issue_ids.append(issue_id)

    return {
        "active_issue_count": active_issue_count,
        "issue_plan_block_ids": sorted(issue_plan_block_ids),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "reconciled_issue_ids": reconciled_issue_ids,
        "write_applied": write,
    }


def _extract_issue_plan_block_ids(section_text: str) -> set[str]:
    """Collect issue IDs that have an explicit issue-plan block in one feature section."""
    issue_ids: set[str] = set()
    for raw_line in section_text.splitlines():
        stripped = raw_line.strip()
        if stripped == ISSUE_EXECUTION_ORDER_HEADING:
            continue
        match = ISSUE_PLAN_BLOCK_HEADING_PATTERN.fullmatch(stripped)
        if match is None:
            continue
        issue_ids.add(match.group("issue_id").strip())
    return issue_ids


def _lint_issue_plan_blocks(
    *,
    section_text: str,
    feature_id: str,
    feature_node: dict[str, Any],
) -> None:
    """Validate canonical per-issue plan block headings/sections within one feature plan section."""
    lines = section_text.splitlines()
    issue_ids_in_feature = {
        str(issue.get("id", "")).strip()
        for issue in feature_node.get("issues", [])
        if isinstance(issue, dict) and str(issue.get("id", "")).strip()
    }
    _, feature_milestone_num = _parse_feature_id(feature_id)
    feature_local_num = _parse_feature_local_num(feature_id)

    issue_heading_indexes: list[tuple[int, str]] = []
    seen_issue_ids: set[str] = set()
    for index, line in enumerate(lines):
        match = SECTION_H3_PATTERN.match(line)
        if match is None:
            continue
        heading = match.group(1).strip()
        if heading in REQUIRED_PLAN_HEADINGS:
            continue
        if line.strip() == ISSUE_EXECUTION_ORDER_HEADING:
            continue
        canonical_match = CANONICAL_ISSUE_PLAN_BLOCK_HEADING_PATTERN.fullmatch(line.strip())
        if canonical_match is None:
            raise WorkflowCommandError(
                f"Invalid issue plan heading {line.strip()!r}. Use canonical format: "
                "'### <issue_id> - <issue_title>'.",
                exit_code=4,
            )
        issue_id = canonical_match.group("issue_id").strip()
        _assert_issue_belongs_to_feature(
            issue_id=issue_id,
            feature_id=feature_id,
            feature_milestone_num=feature_milestone_num,
            feature_local_num=feature_local_num,
        )
        if issue_id not in issue_ids_in_feature:
            raise WorkflowCommandError(
                f"Issue plan block references unknown issue {issue_id} for feature {feature_id}.",
                exit_code=4,
            )
        if issue_id in seen_issue_ids:
            raise WorkflowCommandError(
                f"Duplicate issue plan block for issue {issue_id}.",
                exit_code=4,
            )
        seen_issue_ids.add(issue_id)
        issue_heading_indexes.append((index, issue_id))

    for heading_index, (start_index, issue_id) in enumerate(issue_heading_indexes):
        end_index = len(lines)
        if heading_index + 1 < len(issue_heading_indexes):
            end_index = issue_heading_indexes[heading_index + 1][0]
        for probe_index in range(start_index + 1, end_index):
            stripped = lines[probe_index].strip()
            if stripped.startswith("## ") or stripped.startswith("### "):
                end_index = probe_index
                break
        _lint_one_issue_plan_block(lines=lines, start_index=start_index, end_index=end_index, issue_id=issue_id)


def _lint_one_issue_plan_block(lines: list[str], start_index: int, end_index: int, issue_id: str) -> None:
    """Validate required subheading hierarchy/content inside one canonical issue-plan block."""
    subheading_positions: list[tuple[str, int]] = []
    seen_subheadings: set[str] = set()
    for index in range(start_index + 1, end_index):
        stripped = lines[index].strip()
        if not stripped:
            continue
        if stripped.startswith("<!--"):
            continue
        if stripped.startswith("#") and not stripped.startswith("#### "):
            raise WorkflowCommandError(
                f"Issue plan block {issue_id} contains invalid heading hierarchy: {stripped!r}.",
                exit_code=4,
            )
        match = SECTION_H4_PATTERN.match(lines[index])
        if match is None:
            continue
        heading = match.group(1).strip()
        if heading not in REQUIRED_ISSUE_PLAN_SUBHEADINGS:
            raise WorkflowCommandError(
                f"Issue plan block {issue_id} has unsupported section heading {heading!r}.",
                exit_code=4,
            )
        if heading in seen_subheadings:
            raise WorkflowCommandError(
                f"Issue plan block {issue_id} contains duplicate section heading {heading!r}.",
                exit_code=4,
            )
        seen_subheadings.add(heading)
        subheading_positions.append((heading, index))

    for required_heading in REQUIRED_ISSUE_PLAN_SUBHEADINGS:
        if required_heading not in seen_subheadings:
            raise WorkflowCommandError(
                f"Issue plan block {issue_id} is missing required section {required_heading!r}.",
                exit_code=4,
            )

    for position_index, (heading, heading_line_index) in enumerate(subheading_positions):
        content_start = heading_line_index + 1
        content_end = end_index
        if position_index + 1 < len(subheading_positions):
            content_end = subheading_positions[position_index + 1][1]
        content_lines = _filter_section_content(lines[content_start:content_end])
        if not content_lines:
            raise WorkflowCommandError(
                f"Issue plan block {issue_id} section {heading!r} must contain non-empty content.",
                exit_code=4,
            )


def _collect_issue_planning_status_mismatches(
    *,
    feature_node: dict[str, Any],
    issue_plan_block_ids: set[str],
) -> list[dict[str, Any]]:
    """Return active issue-status mismatches against plan-block coverage."""
    issues = feature_node.get("issues", [])
    if not isinstance(issues, list):
        return []
    mismatches: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        issue_id = str(issue.get("id", "")).strip()
        if not issue_id:
            continue
        status_before = str(issue.get("status", "")).strip()
        if status_before in ISSUE_TERMINAL_STATUSES:
            continue
        status_expected = _expected_issue_planning_status(issue=issue, issue_plan_block_ids=issue_plan_block_ids)
        if status_before == status_expected:
            continue
        mismatches.append(
            {
                "has_plan_block": issue_id in issue_plan_block_ids,
                "issue_id": issue_id,
                "status_before": status_before,
                "status_expected": status_expected,
            }
        )
    mismatches.sort(key=lambda item: item["issue_id"])
    return mismatches


def _expected_issue_planning_status(issue: dict[str, Any], issue_plan_block_ids: set[str]) -> str:
    """Return expected issue planning status from plan-block coverage and decomposition presence."""
    issue_id = str(issue.get("id", "")).strip()
    if issue_id not in issue_plan_block_ids:
        return "Pending"
    tasks = issue.get("tasks", [])
    has_tasks = isinstance(tasks, list) and any(
        isinstance(task, dict) and str(task.get("id", "")).strip()
        for task in tasks
    )
    if has_tasks:
        return "Tasked"
    return "Planned"


def _count_active_issues(feature_node: dict[str, Any]) -> int:
    """Count feature issues that are not terminal (`Done`/`Rejected`)."""
    issues = feature_node.get("issues", [])
    if not isinstance(issues, list):
        return 0
    count = 0
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        issue_id = str(issue.get("id", "")).strip()
        if not issue_id:
            continue
        if str(issue.get("status", "")).strip() in ISSUE_TERMINAL_STATUSES:
            continue
        count += 1
    return count


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


def _format_issue_execution_order_row(position: int, issue_id: str, issue_title: str) -> str:
    """Build canonical markdown row for one issue execution order item."""
    normalized_title = issue_title.strip() or issue_id
    return f"{position}. `{issue_id}` - {normalized_title}"


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


def _parse_pipeline_execution_order(pipeline_payload: dict[str, Any]) -> list[str]:
    """Parse task IDs from pipeline execution sequence payload."""
    execution_sequence = pipeline_payload.get("execution_sequence", [])
    if not isinstance(execution_sequence, list):
        return []
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for item in execution_sequence:
        if not isinstance(item, dict):
            continue
        for token in item.get("tasks", []):
            candidate = str(token).strip()
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
