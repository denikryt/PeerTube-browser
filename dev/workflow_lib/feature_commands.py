"""Register and execute feature workflow commands."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from typing import Any

from .context import WorkflowContext
from .errors import WorkflowCommandError
from .git_adapter import plan_canonical_feature_branch
from .github_adapter import (
    ensure_github_milestone_exists,
    gh_issue_add_sub_issue,
    gh_issue_create,
    gh_issue_edit,
    gh_issue_list_sub_issue_numbers,
    resolve_github_repository,
)
from .markdown_parser import parse_feature_issue_template
from .output import emit_json
from .sync_delta import load_sync_delta, resolve_sync_delta_references
from .tracker_store import (
    load_issue_dependency_index_payload,
    load_issue_overlaps_payload,
    load_task_list_payload,
    write_issue_dependency_index_payload,
    write_issue_overlaps_payload,
    write_task_list_payload,
)
from .tracker_json_contracts import (
    build_issue_dependency_index_contract_payload,
    build_issue_overlaps_contract_payload,
    build_task_list_contract_payload,
    validate_issue_dependency_index_contract_payload,
    validate_issue_overlaps_contract_payload,
    validate_task_list_contract_payload,
)
from .tracking_writers import apply_task_list_delta


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
    "Expected Behaviour",
    "Dependencies",
    "Decomposition",
    "Issue/Task Decomposition Assessment",
)
REQUIRED_ISSUE_PLAN_SUBHEADINGS = (
    "Expected Behaviour",
    "Dependencies",
    "Decomposition",
    "Issue/Task Decomposition Assessment",
)
ISSUE_PLANNING_ACTIVE_STATUSES = {"Pending", "Planned", "Tasked"}
ISSUE_TERMINAL_STATUSES = {"Done", "Rejected"}
ISSUE_ALLOWED_PLANNING_STATUSES = ISSUE_PLANNING_ACTIVE_STATUSES | ISSUE_TERMINAL_STATUSES
DEPENDENCY_LINE_PATTERN = re.compile(
    r"^-\s+(?P<kind>file|module|function|class):\s+(?P<target>[^|]+?)(?:\s+\|\s+reason:\s+(?P<reason>.+))?$"
)
DEPENDENCY_LOOKUP_TOKEN_PATTERN = re.compile(r"`([^`]+)`")


def register_feature_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register feature-scoped planning and execution-plan commands."""
    feature_parser = subparsers.add_parser(
        "feature",
        help="Feature-scoped planning and execution-plan commands.",
    )
    feature_subparsers = feature_parser.add_subparsers(
        dest="feature_command",
        required=True,
    )

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
    execution_plan_parser.set_defaults(only_pending=True)
    execution_plan_parser.set_defaults(handler=_handle_feature_execution_plan)


def register_create_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register canonical action-first create commands."""
    create_parser = subparsers.add_parser(
        "create",
        help="Canonical action-first create commands.",
    )
    create_subparsers = create_parser.add_subparsers(dest="create_target", required=True)

    create_feature_parser = create_subparsers.add_parser(
        "feature",
        help="Register one feature locally without GitHub materialization.",
    )
    create_feature_parser.add_argument("--id", required=True, help="Feature ID (for example, F1-M1).")
    create_feature_parser.add_argument("--milestone", help="Milestone ID (for example, M1).")
    create_feature_parser.add_argument("--title", help="Feature title when creating a new node.")
    create_feature_parser.add_argument(
        "--description",
        help="Optional concise feature description persisted on the local feature node.",
    )
    create_feature_parser.add_argument(
        "--input",
        help="Optional markdown draft file used instead of --title/--description.",
    )
    create_feature_parser.add_argument("--track", default="System/Test", help="Track label for feature node.")
    create_feature_parser.add_argument("--write", action="store_true", help="Write local tracker updates.")
    create_feature_parser.set_defaults(handler=_handle_create_feature_action)

    create_issue_parser = create_subparsers.add_parser(
        "issue",
        help="Register one issue locally without GitHub materialization.",
    )
    create_issue_parser.add_argument("--id", required=True, help="Issue ID (for example, I1-F1-M1).")
    create_issue_parser.add_argument("--title", help="Issue title when creating a new node.")
    create_issue_parser.add_argument(
        "--description",
        help="Optional concise issue description persisted on the local issue node.",
    )
    create_issue_parser.add_argument(
        "--input",
        help="Optional markdown draft file used instead of --title/--description.",
    )
    create_issue_parser.add_argument("--write", action="store_true", help="Write local tracker updates.")
    create_issue_parser.set_defaults(handler=_handle_create_issue_action)


def register_materialize_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register canonical action-first materialize commands."""
    materialize_parser = subparsers.add_parser(
        "materialize",
        help="Canonical action-first GitHub materialization commands.",
    )
    materialize_subparsers = materialize_parser.add_subparsers(dest="materialize_target", required=True)

    materialize_feature_parser = materialize_subparsers.add_parser(
        "feature",
        help="Create or sync one feature-level GitHub issue and branch linkage.",
        description=(
            "Materialize one feature-level GitHub issue.\n"
            "  create: create the feature issue if it is not mapped yet; mapped feature issues are skipped.\n"
            "  sync: update an already mapped feature issue; unmapped feature issues are rejected."
        ),
    )
    materialize_feature_parser.add_argument("--id", required=True, help="Feature ID to materialize.")
    materialize_feature_parser.add_argument(
        "--mode",
        required=True,
        choices=["create", "sync"],
        help=(
            "Select feature-level materialize behavior.\n"
            "create: create GitHub issue only when the feature issue is not mapped yet.\n"
            "sync: update the already mapped feature issue."
        ),
    )
    materialize_feature_parser.add_argument("--write", action="store_true", help="Persist branch linkage and mappings.")
    materialize_feature_parser.add_argument(
        "--github",
        dest="github",
        action="store_true",
        default=True,
        help="Enable GitHub create or update calls. Default: enabled.",
    )
    materialize_feature_parser.add_argument(
        "--no-github",
        dest="github",
        action="store_false",
        help="Disable GitHub create or update calls and keep the run local/dry for remote feature issue changes.",
    )
    materialize_feature_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include full materialize diagnostics. Default output is compact.",
    )
    materialize_feature_parser.set_defaults(handler=_handle_materialize_feature_action)

    materialize_issue_parser = materialize_subparsers.add_parser(
        "issue",
        help="Create or sync one issue or one feature-owned issue set on GitHub.",
        description=(
            "Materialize one issue or one feature-owned issue set.\n"
            "  create: create GitHub issues only for unmapped target issues.\n"
            "  sync: update mapped issues and create any missing mappings for the selected scope."
        ),
    )
    issue_target_group = materialize_issue_parser.add_mutually_exclusive_group(required=True)
    issue_target_group.add_argument("--id", help="Single issue ID to materialize (for example, I1-F1-M1).")
    issue_target_group.add_argument("--feature-id", help="Feature ID owning the issue set to materialize.")
    materialize_issue_parser.add_argument(
        "--issue-id",
        action="append",
        default=[],
        help="Optional repeatable issue selector when using --feature-id. Queue order is preserved.",
    )
    materialize_issue_parser.add_argument(
        "--mode",
        required=True,
        choices=["create", "sync"],
        help=(
            "Select issue-level materialize behavior.\n"
            "create: create GitHub issues only for unmapped selected issues.\n"
            "sync: update mapped issues and create any missing selected issue mappings."
        ),
    )
    materialize_issue_parser.add_argument("--write", action="store_true", help="Persist issue mappings and branch linkage.")
    materialize_issue_parser.add_argument(
        "--github",
        dest="github",
        action="store_true",
        default=True,
        help="Enable GitHub create or update calls. Default: enabled.",
    )
    materialize_issue_parser.add_argument(
        "--no-github",
        dest="github",
        action="store_false",
        help="Disable GitHub create or update calls and keep the run local/dry for remote issue changes.",
    )
    materialize_issue_parser.add_argument(
        "--pause-seconds",
        type=float,
        default=1.0,
        help="Pause between consecutive GitHub requests in write plus github mode. Default: 1.0.",
    )
    materialize_issue_parser.add_argument(
        "--max-retries",
        type=int,
        default=4,
        help="Maximum retry attempts for transient GitHub request failures. Default: 4.",
    )
    materialize_issue_parser.add_argument(
        "--request-timeout",
        type=float,
        default=20.0,
        help="Per-request GitHub CLI timeout in seconds for write plus github mode. Default: 20.0.",
    )
    materialize_issue_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Emit full materialize diagnostics, including per-issue details. Default output is compact.",
    )
    materialize_issue_parser.set_defaults(handler=_handle_materialize_issue_action)


def register_plan_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register canonical decomposition commands: `plan tasks for ...`."""
    plan_parser = subparsers.add_parser(
        "plan",
        help="Plan and decompose workflow entities.",
    )
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", required=True)

    index_dependencies_parser = plan_subparsers.add_parser(
        "index-dependencies",
        help="Build or clean the issue dependency index from FEATURE_PLANS.",
    )
    _register_scope_selector_args(index_dependencies_parser, allow_all=True)
    index_dependencies_parser.add_argument(
        "--remove-index",
        action="store_true",
        help="Remove indexed rows for the selected scope instead of rebuilding them.",
    )
    index_dependencies_parser.add_argument("--write", action="store_true", help="Persist dependency index changes.")
    index_dependencies_parser.set_defaults(handler=_handle_plan_index_dependencies)

    show_related_parser = plan_subparsers.add_parser(
        "show-related",
        help="Show issue candidates that share indexed dependency surfaces.",
    )
    _register_scope_selector_args(show_related_parser, allow_all=False)
    show_related_parser.set_defaults(handler=_handle_plan_show_related)

    get_plan_block_parser = plan_subparsers.add_parser(
        "get-plan-block",
        help="Return Dependencies-only plan blocks for one issue or feature scope.",
    )
    _register_scope_selector_args(get_plan_block_parser, allow_all=False)
    get_plan_block_parser.set_defaults(handler=_handle_plan_get_plan_block)

    show_overlaps_parser = plan_subparsers.add_parser(
        "show-overlaps",
        help="Show dedicated issue-overlap records for one scope or all scopes.",
    )
    _register_scope_selector_args(show_overlaps_parser, allow_all=True)
    show_overlaps_parser.set_defaults(handler=_handle_plan_show_overlaps)

    build_overlaps_parser = plan_subparsers.add_parser(
        "build-overlaps",
        help="Build draft issue-overlap delta payload for one feature or issue scope.",
    )
    _register_scope_selector_args(build_overlaps_parser, allow_all=False)
    build_overlaps_parser.add_argument("--delta-file", required=True, help="Path to write draft overlap payload.")
    build_overlaps_parser.set_defaults(handler=_handle_plan_build_overlaps)

    apply_overlaps_parser = plan_subparsers.add_parser(
        "apply-overlaps",
        help="Validate and persist issue-overlap payload from a delta file.",
    )
    apply_overlaps_parser.add_argument("--delta-file", required=True, help="Path to overlap payload JSON file.")
    apply_overlaps_parser.add_argument("--write", action="store_true", help="Persist overlap changes.")
    apply_overlaps_parser.set_defaults(handler=_handle_plan_apply_overlaps)

    migrate_overlaps_parser = plan_subparsers.add_parser(
        "migrate-overlaps",
        help="Clear legacy pipeline overlap rows after moving overlap ownership to ISSUE_OVERLAPS.",
    )
    migrate_overlaps_parser.add_argument("--write", action="store_true", help="Persist pipeline cleanup.")
    migrate_overlaps_parser.set_defaults(handler=_handle_plan_migrate_overlaps)

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
    issue_parser.set_defaults(handler=_handle_plan_tasks_for_issue)

    issues_parser = for_subparsers.add_parser(
        "issues",
        help="Plan tasks for multiple issues in one decomposition delta run.",
    )
    issues_parser.add_argument(
        "--issue-id",
        action="append",
        required=True,
        help="Repeatable issue selector; queue order is preserved.",
    )
    issues_parser.add_argument(
        "--delta-file",
        required=True,
        help="Path to JSON delta describing issue/task and tracker updates.",
    )
    issues_parser.add_argument("--write", action="store_true", help="Persist tracker updates.")
    issues_parser.add_argument(
        "--allocate-task-ids",
        action="store_true",
        help="Allocate numeric IDs from DEV_MAP task_count for token IDs ($token).",
    )
    issues_parser.set_defaults(handler=_handle_plan_tasks_for_issues)


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
    resolved_input = _resolve_markdown_command_input(args, command_label="feature create")
    requested_feature_title = resolved_input["title"]
    requested_feature_description = resolved_input["description"]
    if feature_ref is not None:
        existing_milestone = feature_ref["milestone"]["id"]
        if existing_milestone != milestone_id:
            raise WorkflowCommandError(
                f"Feature {feature_id} already exists under {existing_milestone}, not {milestone_id}.",
                exit_code=4,
            )
        feature_node = feature_ref["feature"]
        if bool(args.write):
            if requested_feature_description:
                feature_node["description"] = requested_feature_description
                wrote_changes = True
            elif not str(feature_node.get("description", "")).strip():
                feature_node["description"] = _build_default_feature_description(feature_node)
                wrote_changes = True
            _normalize_feature_node_layout(feature_node)
    else:
        feature_node = _build_feature_node(
            feature_id=feature_id,
            title=(requested_feature_title or f"Feature {feature_id}"),
            description=requested_feature_description,
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
                "gh_issue_url": _optional_text(feature_node.get("gh_issue_url")),
                "milestone_title": milestone_title,
            }

    if bool(args.write) and wrote_changes:
        _touch_updated_at(dev_map)
        _write_json(context.dev_map_path, dev_map)

    emit_json(
        {
            "action": "already-exists" if feature_exists else ("created" if bool(args.write) else "would-create"),
            "command": str(getattr(args, "command_output", "feature.create")).strip() or "feature.create",
            "feature_id": feature_id,
            "description": str(feature_node.get("description", "")).strip() or None,
            "gh_issue_number": feature_node.get("gh_issue_number"),
            "gh_issue_url": feature_node.get("gh_issue_url"),
            "github_enabled": bool(args.github),
            "github_issue": github_issue,
            "input_warnings": resolved_input["warnings"],
            "milestone_title": milestone_title,
            "milestone_id": milestone_id,
            "write_applied": bool(args.write) and wrote_changes,
            "write": bool(args.write),
        }
    )
    return 0


def _handle_create_issue(args: Namespace, context: WorkflowContext) -> int:
    """Create one issue node under its owning feature and optionally sync GitHub metadata."""
    issue_id, feature_local_num, feature_milestone_num = _parse_issue_id(args.id)
    feature_id = f"F{feature_local_num}-M{feature_milestone_num}"
    milestone_id = f"M{feature_milestone_num}"

    dev_map = _load_json(context.dev_map_path)
    milestone_node = _find_milestone(dev_map, milestone_id)
    if milestone_node is None:
        raise WorkflowCommandError(f"Milestone {milestone_id} not found in DEV_MAP.", exit_code=4)
    milestone_title = _resolve_github_milestone_title(milestone_node, milestone_id)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(
            f"Feature {feature_id} not found in DEV_MAP; create the parent feature before creating issue {issue_id}.",
            exit_code=4,
        )

    feature_node = feature_ref["feature"]
    issues = feature_node.setdefault("issues", [])
    if not isinstance(issues, list):
        raise WorkflowCommandError(f"Feature {feature_id} has invalid issue list in DEV_MAP.", exit_code=4)

    resolved_input = _resolve_markdown_command_input(args, command_label="feature create-issue")
    requested_issue_title = resolved_input["title"]
    requested_issue_description = resolved_input["description"]

    issue_node = None
    for candidate in issues:
        if isinstance(candidate, dict) and str(candidate.get("id", "")).strip() == issue_id:
            issue_node = candidate
            break
    issue_exists = issue_node is not None
    wrote_changes = False

    if issue_node is None:
        issue_node = _build_issue_node(
            issue_id=issue_id,
            title=requested_issue_title or f"Issue {issue_id}",
            description=requested_issue_description,
        )
        if bool(args.write):
            issues.append(issue_node)
            _normalize_feature_issue_nodes_layout(feature_node)
            wrote_changes = True
    elif bool(args.write):
        if requested_issue_title:
            issue_node["title"] = requested_issue_title
            wrote_changes = True
        if requested_issue_description:
            issue_node["description"] = requested_issue_description
            wrote_changes = True
        elif not str(issue_node.get("description", "")).strip():
            issue_node["description"] = _build_default_issue_description(issue_node)
            wrote_changes = True
        _normalize_issue_node_layout(issue_node)

    github_issue: dict[str, Any] | None = None
    if bool(args.github):
        if bool(args.write):
            github_repo = resolve_github_repository(context.root_dir)
            ensure_github_milestone_exists(
                repo_name_with_owner=github_repo["name_with_owner"],
                milestone_title=milestone_title,
                milestone_id=milestone_id,
            )
            github_issue = _materialize_feature_issue_node(
                issue_node=issue_node,
                milestone_title=milestone_title,
                repo_name_with_owner=github_repo["name_with_owner"],
                repo_url=_normalize_repository_url(str(github_repo.get("url", ""))),
                max_retries=4,
                retry_pause_seconds=1.0,
                request_timeout=20.0,
            )
            wrote_changes = True
        else:
            existing_issue_number = _coerce_issue_number(
                issue_node.get("gh_issue_number"),
                issue_node.get("gh_issue_url"),
            )
            github_issue = {
                "action": "would-update" if existing_issue_number is not None else "would-create",
                "gh_issue_number": existing_issue_number,
                "gh_issue_url": _optional_text(issue_node.get("gh_issue_url")),
                "milestone_title": milestone_title,
            }

    if bool(args.write) and wrote_changes:
        _touch_updated_at(dev_map)
        _write_json(context.dev_map_path, dev_map)

    emit_json(
        {
            "action": "already-exists" if issue_exists else ("created" if bool(args.write) else "would-create"),
            "command": str(getattr(args, "command_output", "feature.create-issue")).strip() or "feature.create-issue",
            "feature_id": feature_id,
            "issue_id": issue_id,
            "description": str(issue_node.get("description", "")).strip() or None,
            "gh_issue_number": issue_node.get("gh_issue_number"),
            "gh_issue_url": issue_node.get("gh_issue_url"),
            "github_enabled": bool(args.github),
            "github_issue": github_issue,
            "input_warnings": resolved_input["warnings"],
            "milestone_title": milestone_title,
            "milestone_id": milestone_id,
            "write_applied": bool(args.write) and wrote_changes,
            "write": bool(args.write),
        }
    )
    return 0


def _handle_create_feature_action(args: Namespace, context: WorkflowContext) -> int:
    """Execute canonical action-first `create feature` as local registration only."""
    setattr(args, "github", False)
    setattr(args, "command_output", "create.feature")
    return _handle_feature_create(args, context)


def _handle_create_issue_action(args: Namespace, context: WorkflowContext) -> int:
    """Execute canonical action-first `create issue` as local registration only."""
    setattr(args, "github", False)
    setattr(args, "command_output", "create.issue")
    return _handle_create_issue(args, context)


def _handle_feature_plan_init(args: Namespace, context: WorkflowContext) -> int:
    """Initialize a feature plan section scaffold in FEATURE_PLANS."""
    feature_id, _ = _parse_feature_id(args.id)
    dev_map = _load_json(context.dev_map_path)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)
    feature_node = feature_ref["feature"]
    feature_title = str(feature_node.get("title", "")).strip() or feature_id
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
        scaffold = _build_feature_plan_scaffold(feature_id=feature_id, feature_title=feature_title)
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
        require_issue_order_for_active=False,
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
    issue_node = issue_resolution["issue"]
    raw_feature_assertion = getattr(args, "feature_id", None)
    feature_assertion = str(raw_feature_assertion).strip() if raw_feature_assertion is not None else ""
    if feature_assertion:
        normalized_feature_assertion, _ = _parse_feature_id(feature_assertion)
        if normalized_feature_assertion != feature_id:
            raise WorkflowCommandError(
                f"plan-issue feature assertion mismatch: issue {issue_id} belongs to {feature_id}, got {normalized_feature_assertion}.",
                exit_code=4,
            )

    feature_plans_text = context.feature_plans_path.read_text(encoding="utf-8")
    section_bounds = _find_h2_section_bounds(feature_plans_text, feature_id)
    if section_bounds is None:
        raise WorkflowCommandError(
            f"Feature plan section ## {feature_id} not found in {context.feature_plans_path}.",
            exit_code=4,
        )
    section_start, section_end = section_bounds
    feature_plans_lines = feature_plans_text.splitlines()
    section_lines = feature_plans_lines[section_start:section_end]
    _lint_existing_issue_plan_block_if_present(section_lines=section_lines, issue_id=issue_id)
    updated_section_lines, block_action = _upsert_issue_plan_block_in_section(
        section_lines=section_lines,
        issue_id=issue_id,
        issue_title=str(issue_node.get("title", "")).strip() or issue_id,
        issue_node=issue_node,
    )
    plan_block_updated = block_action in {"created", "updated"}
    _lint_plan_issue_block_scoped(
        section_lines=updated_section_lines,
        issue_id=issue_id,
        strict=bool(args.strict),
    )
    if bool(args.write) and plan_block_updated:
        feature_plans_lines[section_start:section_end] = updated_section_lines
        context.feature_plans_path.write_text("\n".join(feature_plans_lines) + "\n", encoding="utf-8")
    action = block_action if bool(args.write) else _render_plan_issue_dry_run_action(block_action)

    emit_json(
        {
            "action": action,
            "command": "feature.plan-issue",
            "feature_id": feature_id,
            "issue_id": issue_id,
            "issue_order_checked": True,
            "issue_order_mutated": False,
            "plan_block_updated": plan_block_updated,
            "strict": bool(args.strict),
            "write": bool(args.write),
        }
    )
    return 0


def _handle_plan_index_dependencies(args: Namespace, context: WorkflowContext) -> int:
    """Build or clean scoped dependency-index payload from FEATURE_PLANS issue blocks."""
    selector = _resolve_scope_selector(args=args, allow_all=True)
    if selector["scope_type"] == "all":
        raise WorkflowCommandError(
            "index-dependencies currently supports --feature-id or --issue-id only.",
            exit_code=4,
        )

    dev_map = _load_json(context.dev_map_path)
    current_payload = load_issue_dependency_index_payload(context)
    by_issue = dict(current_payload.get("by_issue", {}))
    by_surface = dict(current_payload.get("by_surface", {}))
    target_issue_ids: set[str] = set()
    target_feature_ids: set[str] = set()

    if selector["scope_type"] == "feature":
        feature_ref = _find_feature(dev_map, selector["scope_id"])
        if feature_ref is None:
            raise WorkflowCommandError(f"Feature {selector['scope_id']} not found in DEV_MAP.", exit_code=4)
        target_feature_ids.add(selector["scope_id"])
        for issue_node in _collect_feature_issue_nodes(feature_ref["feature"]):
            target_issue_ids.add(str(issue_node.get("id", "")).strip())
    else:
        issue_ref = _resolve_issue_owner_feature(dev_map, selector["scope_id"])
        target_issue_ids.add(selector["scope_id"])
        target_feature_ids.add(issue_ref["feature_id"])

    removed_issue_ids = sorted(target_issue_ids & set(by_issue.keys()))
    surfaces_added = 0
    surfaces_updated = 0
    surfaces_removed = 0
    for issue_id in removed_issue_ids:
        by_issue.pop(issue_id, None)
    for surface_key in list(by_surface.keys()):
        entry = by_surface[surface_key]
        issue_ids = [issue_id for issue_id in entry if issue_id not in target_issue_ids]
        if issue_ids:
            by_surface[surface_key] = sorted(issue_ids)
        else:
            by_surface.pop(surface_key, None)
            surfaces_removed += 1

    issues_reindexed = 0
    if not bool(args.remove_index):
        scoped_payload = _build_dependency_index_for_scope(
            context=context,
            dev_map=dev_map,
            scope_type=selector["scope_type"],
            scope_id=selector["scope_id"],
        )
        scoped_by_issue = scoped_payload.get("by_issue", {})
        scoped_by_surface = scoped_payload.get("by_surface", {})
        issues_reindexed = len(scoped_by_issue)
        for issue_id, entry in scoped_by_issue.items():
            by_issue[issue_id] = entry
        for surface_key, entry in scoped_by_surface.items():
            if surface_key in by_surface:
                surfaces_updated += 1
                by_surface[surface_key] = sorted(set(by_surface[surface_key]) | set(entry))
            else:
                surfaces_added += 1
                by_surface[surface_key] = sorted(entry)

    updated_payload = build_issue_dependency_index_contract_payload(
        {
            "scope_type": selector["scope_type"],
            "scope_id": selector["scope_id"],
            "by_issue": dict(sorted(by_issue.items())),
            "by_surface": dict(sorted(by_surface.items())),
        }
    )
    validate_issue_dependency_index_contract_payload(updated_payload, "plan.index-dependencies")
    changed = updated_payload != current_payload
    if bool(args.write) and changed:
        write_issue_dependency_index_payload(context, updated_payload)

    emit_json(
        {
            "action": "removed" if bool(args.remove_index) else ("updated" if changed else "unchanged"),
            "changed": changed,
            "command": "plan.index-dependencies",
            "issues_reindexed": issues_reindexed,
            "issues_removed": len(removed_issue_ids),
            "scope_id": selector["scope_id"],
            "scope_type": selector["scope_type"],
            "surfaces_added": surfaces_added,
            "surfaces_pruned": surfaces_removed,
            "surfaces_removed": surfaces_removed,
            "surfaces_updated": surfaces_updated,
            "write": bool(args.write),
        }
    )
    return 0


def _handle_plan_show_related(args: Namespace, context: WorkflowContext) -> int:
    """Show issue candidates that share one or more indexed dependency surfaces."""
    selector = _resolve_scope_selector(args=args, allow_all=False)
    current_payload = load_issue_dependency_index_payload(context)
    by_issue = current_payload.get("by_issue", {})
    by_surface = current_payload.get("by_surface", {})

    if selector["scope_type"] == "issue":
        issue_id = selector["scope_id"]
        issue_entry = by_issue.get(issue_id)
        if not isinstance(issue_entry, dict):
            raise WorkflowCommandError(
                f"Issue {issue_id} is missing from ISSUE_DEP_INDEX; run index-dependencies first.",
                exit_code=4,
            )
        related: dict[str, set[str]] = {}
        for surface_key in issue_entry.get("surface_keys", []):
            bucket = by_surface.get(surface_key, [])
            for candidate_issue_id in bucket:
                if candidate_issue_id == issue_id:
                    continue
                related.setdefault(candidate_issue_id, set()).add(surface_key)
        emit_json(
            {
                "command": "plan.show-related",
                "issue_id": issue_id,
                "related_issues": [
                    {
                        "issue_id": candidate_issue_id,
                        "matched_surfaces": sorted(surfaces, key=_normalize_dependency_surface),
                    }
                    for candidate_issue_id, surfaces in sorted(related.items())
                ],
            }
        )
        return 0

    dev_map = _load_json(context.dev_map_path)
    feature_ref = _find_feature(dev_map, selector["scope_id"])
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {selector['scope_id']} not found in DEV_MAP.", exit_code=4)
    issue_ids = [str(issue.get("id", "")).strip() for issue in _collect_feature_issue_nodes(feature_ref["feature"])]
    pair_matches: list[dict[str, Any]] = []
    for index, left_issue_id in enumerate(issue_ids):
        left_entry = by_issue.get(left_issue_id)
        if not isinstance(left_entry, dict):
            continue
        left_surfaces = set(left_entry.get("surface_keys", []))
        for right_issue_id in issue_ids[index + 1 :]:
            right_entry = by_issue.get(right_issue_id)
            if not isinstance(right_entry, dict):
                continue
            matched_surfaces = sorted(left_surfaces & set(right_entry.get("surface_keys", [])), key=_normalize_dependency_surface)
            if not matched_surfaces:
                continue
            pair_matches.append(
                {
                    "issues": [left_issue_id, right_issue_id],
                    "matched_surfaces": matched_surfaces,
                }
            )
    emit_json(
        {
            "command": "plan.show-related",
            "feature_id": selector["scope_id"],
            "related_pairs": pair_matches,
        }
    )
    return 0


def _handle_plan_get_plan_block(args: Namespace, context: WorkflowContext) -> int:
    """Return Dependencies-only plan block content for one issue or feature scope."""
    selector = _resolve_scope_selector(args=args, allow_all=False)
    dev_map = _load_json(context.dev_map_path)
    if selector["scope_type"] == "issue":
        issue_ref = _resolve_issue_owner_feature(dev_map, selector["scope_id"])
        section_lines = _extract_feature_section_lines(context.feature_plans_path, issue_ref["feature_id"])
        dependency_lines = _extract_issue_dependencies_block_lines(section_lines, selector["scope_id"])
        emit_json(
            {
                "command": "plan.get-plan-block",
                "feature_id": issue_ref["feature_id"],
                "issue_id": selector["scope_id"],
                "dependencies": "\n".join(dependency_lines),
            }
        )
        return 0

    feature_ref = _find_feature(dev_map, selector["scope_id"])
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {selector['scope_id']} not found in DEV_MAP.", exit_code=4)
    section_lines = _extract_feature_section_lines(context.feature_plans_path, selector["scope_id"])
    blocks: list[dict[str, str]] = []
    for issue_node in _collect_feature_issue_nodes(feature_ref["feature"]):
        issue_id = str(issue_node.get("id", "")).strip()
        dependency_lines = _extract_issue_dependencies_block_lines(section_lines, issue_id)
        blocks.append({"issue_id": issue_id, "dependencies": "\n".join(dependency_lines)})
    emit_json(
        {
            "command": "plan.get-plan-block",
            "feature_id": selector["scope_id"],
            "blocks": blocks,
        }
    )
    return 0


def _handle_plan_show_overlaps(args: Namespace, context: WorkflowContext) -> int:
    """Return dedicated issue-overlap rows for one scope or all scopes."""
    selector = _resolve_scope_selector(args=args, allow_all=True)
    payload = load_issue_overlaps_payload(context)
    overlaps = payload.get("overlaps", [])
    if selector["scope_type"] == "all":
        filtered = overlaps
    elif selector["scope_type"] == "issue":
        filtered = [item for item in overlaps if selector["scope_id"] in item.get("issues", [])]
    else:
        dev_map = _load_json(context.dev_map_path)
        feature_ref = _find_feature(dev_map, selector["scope_id"])
        if feature_ref is None:
            raise WorkflowCommandError(f"Feature {selector['scope_id']} not found in DEV_MAP.", exit_code=4)
        feature_issue_ids = {
            str(issue.get("id", "")).strip()
            for issue in _collect_feature_issue_nodes(feature_ref["feature"])
        }
        filtered = [
            item
            for item in overlaps
            if any(issue_id in feature_issue_ids for issue_id in item.get("issues", []))
        ]
    emit_json(
        {
            "command": "plan.show-overlaps",
            "overlaps": filtered,
            "scope_id": selector["scope_id"],
            "scope_type": selector["scope_type"],
        }
    )
    return 0


def _handle_plan_build_overlaps(args: Namespace, context: WorkflowContext) -> int:
    """Build draft overlap delta payload from dependency-index candidates."""
    selector = _resolve_scope_selector(args=args, allow_all=False)
    current_index = load_issue_dependency_index_payload(context)
    current_overlaps = load_issue_overlaps_payload(context).get("overlaps", [])
    if selector["scope_type"] == "issue":
        related_payload = _build_related_issue_draft(current_index, selector["scope_id"])
    else:
        dev_map = _load_json(context.dev_map_path)
        feature_ref = _find_feature(dev_map, selector["scope_id"])
        if feature_ref is None:
            raise WorkflowCommandError(f"Feature {selector['scope_id']} not found in DEV_MAP.", exit_code=4)
        related_payload = _build_feature_related_pairs_draft(current_index, feature_ref["feature"])
    draft_payload = {
        "scope_type": selector["scope_type"],
        "scope_id": selector["scope_id"],
        "candidates": related_payload,
        "existing_overlaps": current_overlaps,
        "overlaps": [],
    }
    Path(args.delta_file).write_text(f"{json.dumps(draft_payload, indent=2, ensure_ascii=False)}\n", encoding="utf-8")
    emit_json(
        {
            "candidate_count": len(related_payload),
            "command": "plan.build-overlaps",
            "delta_file": str(Path(args.delta_file)),
            "scope_id": selector["scope_id"],
            "scope_type": selector["scope_type"],
        }
    )
    return 0


def _handle_plan_apply_overlaps(args: Namespace, context: WorkflowContext) -> int:
    """Validate and optionally persist overlap payload from a delta file."""
    payload = _load_json(Path(args.delta_file))
    dev_map = _load_json(context.dev_map_path)
    issue_execution_order = _build_global_issue_execution_order(
        dev_map=dev_map,
        overlaps=payload.get("overlaps", []),
    )
    overlaps_payload = build_issue_overlaps_contract_payload(
        payload.get("overlaps", []),
        issue_execution_order,
    )
    validate_issue_overlaps_contract_payload(overlaps_payload, "plan.apply-overlaps")
    if bool(args.write):
        write_issue_overlaps_payload(context, overlaps_payload)
    emit_json(
        {
            "command": "plan.apply-overlaps",
            "overlap_count": len(overlaps_payload.get("overlaps", [])),
            "write": bool(args.write),
        }
    )
    return 0


def _handle_plan_migrate_overlaps(args: Namespace, context: WorkflowContext) -> int:
    """Reject retired migration command once pipeline runtime has been removed."""
    raise WorkflowCommandError(
        "plan migrate-overlaps is retired because TASK_EXECUTION_PIPELINE is no longer a runtime artifact.",
        exit_code=4,
    )


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
    setattr(args, "issue_id_queue", [issue_id])
    setattr(args, "command_label", "plan tasks for issue")
    setattr(args, "command_output", "plan.tasks.for.issue")
    return _handle_feature_sync(args, context)


def _handle_plan_tasks_for_issues(args: Namespace, context: WorkflowContext) -> int:
    """Handle `plan tasks for issues` command by resolving one owning feature and queue filter."""
    issue_id_queue = _resolve_plan_tasks_issue_batch_queue(args.issue_id)
    first_issue_id, feature_local_num, feature_milestone_num = _parse_issue_id(issue_id_queue[0])
    feature_id = f"F{feature_local_num}-M{feature_milestone_num}"
    _assert_issue_queue_belongs_to_feature(
        issue_id_queue=issue_id_queue,
        feature_id=feature_id,
        feature_milestone_num=feature_milestone_num,
        feature_local_num=feature_local_num,
        command_label="plan tasks for issues",
    )
    setattr(args, "id", feature_id)
    setattr(args, "issue_id_filter", first_issue_id if len(issue_id_queue) == 1 else None)
    setattr(args, "issue_id_queue", issue_id_queue)
    setattr(args, "command_label", "plan tasks for issues")
    setattr(args, "command_output", "plan.tasks.for.issues")
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
    issue_id_queue = _resolve_plan_tasks_issue_queue(
        raw_issue_ids=getattr(args, "issue_id_queue", None),
        feature_id=feature_id,
        feature_milestone_num=feature_milestone_num,
        feature_local_num=feature_local_num,
    )
    if issue_id_filter is not None and issue_id_filter not in issue_id_queue:
        issue_id_queue.append(issue_id_filter)
    if issue_id_filter is None and len(issue_id_queue) == 1:
        issue_id_filter = issue_id_queue[0]
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
        issue_id_queue=issue_id_queue,
        command_label=command_label,
    )
    _enforce_plan_tasks_issue_status_gate(
        feature_node=feature_node,
        issue_payloads=issue_payloads,
        issue_id_filter=issue_id_filter,
        issue_id_queue=issue_id_queue,
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
    issue_description_backfill = _backfill_missing_issue_descriptions_for_feature(feature_node)
    issue_title_by_id = {
        str(issue.get("id", "")).strip(): str(issue.get("title", "")).strip()
        for issue in feature_node.get("issues", [])
        if isinstance(issue, dict) and str(issue.get("id", "")).strip()
    }
    scoped_issue_ids = {
        str(issue_payload.get("id", "")).strip()
        for issue_payload in issue_payloads
        if isinstance(issue_payload, dict) and str(issue_payload.get("id", "")).strip()
    }
    issue_overlaps_payload = load_issue_overlaps_payload(context)
    scoped_issue_overlaps = [
        overlap
        for overlap in issue_overlaps_payload.get("overlaps", [])
        if any(issue_id in scoped_issue_ids for issue_id in overlap.get("issues", []))
    ]
    issue_execution_order_sync = {
        "added_issue_ids": [],
        "attempted": False,
        "block_created": False,
        "updated": False,
    }
    issue_planning_status_reconciliation = _reconcile_feature_issue_planning_statuses(
        feature_plans_path=context.feature_plans_path,
        feature_id=feature_id,
        feature_node=feature_node,
        write=bool(args.write),
    )
    _normalize_feature_node_layout(feature_node)
    _normalize_feature_issue_nodes_layout(feature_node)

    expected_marker = f"[M{feature_milestone_num}][F{feature_local_num}]"
    task_list_contract_payload = build_task_list_contract_payload(
        resolved_delta.get("task_list_entries", []),
        expected_marker=expected_marker,
    )
    validate_task_list_contract_payload(
        payload=task_list_contract_payload,
        location="plan.tasks.for.task_list_contract",
    )

    task_list_payload = load_task_list_payload(context)
    updated_task_list_payload, task_list_count = apply_task_list_delta(
        task_list_payload=task_list_payload,
        entries=resolved_delta.get("task_list_entries", []),
        expected_marker=expected_marker,
    )

    task_count_before = int(dev_map.get("task_count", 0))
    if bool(args.write):
        if allocation["task_count_after"] != task_count_before:
            dev_map["task_count"] = allocation["task_count_after"]
        _touch_updated_at(dev_map)
        _write_json(context.dev_map_path, dev_map)
        write_task_list_payload(context, updated_task_list_payload)

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
            "issue_id_queue": issue_id_queue,
            "issue_overlap_context_count": len(scoped_issue_overlaps),
            "issue_execution_order_sync": issue_execution_order_sync,
            "issue_description_backfill": issue_description_backfill,
            "issue_planning_status_reconciliation": issue_planning_status_reconciliation,
            "task_count_after": allocation["task_count_after"] if bool(args.write) else task_count_before,
            "task_count_before": task_count_before,
            "task_list_entries_added": task_list_count,
            "write": bool(args.write),
        }
    )
    return 0


def _handle_feature_materialize(args: Namespace, context: WorkflowContext) -> int:
    """Materialize local feature issue nodes to GitHub with canonical branch policy."""
    feature_id, feature_milestone_num = _parse_feature_id(args.id)
    materialize_mode = str(args.mode).strip()
    mode_action = _resolve_materialize_mode_action(materialize_mode)
    materialize_request_policy = _resolve_materialize_request_policy(args)
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
    if not str(feature_node.get("description", "")).strip():
        feature_node["description"] = _build_default_feature_description(feature_node)
    _normalize_feature_node_layout(feature_node)
    issue_description_backfill = _backfill_missing_issue_descriptions_for_feature(feature_node)
    _normalize_feature_issue_nodes_layout(feature_node)

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
        _enforce_materialize_issue_status_gate(issue_nodes, materialize_mode=materialize_mode)

    branch_name = f"feature/{feature_id}"
    repo_url = _resolve_repository_url(context.root_dir, feature_node)
    branch_url = _build_branch_url(repo_url, branch_name)
    branch_action = plan_canonical_feature_branch(context.root_dir, branch_name)

    materialized_issues: list[dict[str, Any]] = []
    missing_issue_mappings: list[dict[str, Any]] = []
    sub_issues_sync: dict[str, Any] = {
        "attempted": False,
        "added": [],
        "skipped": [],
        "errors": [],
        "existing_sub_issue_numbers": [],
        "target_sub_issue_numbers": [],
        "parent_issue_number": None,
        "reason": "materialize-mode-bootstrap",
    }
    feature_issue_checklist_sync: dict[str, Any] = {
        "attempted": False,
        "updated": False,
        "added_issue_ids": [],
        "reason": "description-driven-body-no-checklist-sync",
    }
    feature_issue_body_sync: dict[str, Any] = {
        "attempted": False,
        "updated": False,
        "reason": "feature-issue-sync-runs-in-issues-sync-write-github-mode",
    }
    github_repo_name_with_owner: str | None = None
    github_repo_url: str | None = None
    if materialize_mode != "bootstrap":
        if bool(args.write) and bool(args.github):
            github_repo = resolve_github_repository(context.root_dir)
            github_repo_name_with_owner = github_repo["name_with_owner"]
            github_repo_url = _normalize_repository_url(str(github_repo.get("url", "")))
            ensure_github_milestone_exists(
                repo_name_with_owner=github_repo_name_with_owner,
                milestone_title=milestone_title,
                milestone_id=milestone_id,
                max_retries=materialize_request_policy["max_retries"],
                retry_pause_seconds=materialize_request_policy["pause_seconds"],
                timeout_seconds=materialize_request_policy["request_timeout"],
            )
            for issue_index, issue_node in enumerate(issue_nodes):
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
                    repo_url=github_repo_url,
                    max_retries=materialize_request_policy["max_retries"],
                    retry_pause_seconds=materialize_request_policy["pause_seconds"],
                    request_timeout=materialize_request_policy["request_timeout"],
                )
                materialized["mode_action"] = mode_action
                materialized_issues.append(materialized)
                if (
                    materialize_request_policy["pause_seconds"] > 0
                    and issue_index < len(issue_nodes) - 1
                ):
                    time.sleep(materialize_request_policy["pause_seconds"])
            if materialize_mode in {"issues-create", "issues-sync"}:
                missing_issue_mappings = _collect_missing_issue_mappings(all_issue_nodes)
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
            if materialize_mode in {"issues-create", "issues-sync"}:
                missing_issue_mappings = _collect_missing_issue_mappings(all_issue_nodes)

    if materialize_mode != "bootstrap":
        if (
            materialize_mode == "issues-sync"
            and bool(args.write)
            and bool(args.github)
            and github_repo_name_with_owner is not None
        ):
            feature_issue_body_sync = _sync_feature_issue_body_for_materialize(
                feature_node=feature_node,
                repo_name_with_owner=github_repo_name_with_owner,
                milestone_title=milestone_title,
                repo_url=github_repo_url,
                max_retries=materialize_request_policy["max_retries"],
                retry_pause_seconds=materialize_request_policy["pause_seconds"],
                request_timeout=materialize_request_policy["request_timeout"],
            )
        else:
            feature_issue_body_sync = {
                "attempted": False,
                "updated": False,
                "reason": "feature-issue-sync-requires-issues-sync-write-github",
            }
        if bool(args.write) and bool(args.github) and github_repo_name_with_owner is not None:
            sub_issues_sync = _reconcile_feature_sub_issues(
                feature_node=feature_node,
                issue_nodes=all_issue_nodes,
                repo_name_with_owner=github_repo_name_with_owner,
                max_retries=materialize_request_policy["max_retries"],
                retry_pause_seconds=materialize_request_policy["pause_seconds"],
                request_timeout=materialize_request_policy["request_timeout"],
            )
        else:
            sub_issues_sync = {
                "attempted": False,
                "added": [],
                "skipped": [],
                "errors": [],
                "existing_sub_issue_numbers": [],
                "target_sub_issue_numbers": [],
                "parent_issue_number": _coerce_issue_number(
                    feature_node.get("gh_issue_number"),
                    feature_node.get("gh_issue_url"),
                ),
                "reason": "sub-issue-sync-requires-write-and-github",
            }

    if bool(args.write):
        feature_node["branch_name"] = branch_name
        feature_node["branch_url"] = branch_url
        _touch_updated_at(dev_map)
        _write_json(context.dev_map_path, dev_map)

    active_branch_message = f"Canonical feature branch: {branch_name}"
    full_payload = {
        "active_feature_branch": branch_name,
        "active_feature_branch_message": active_branch_message,
        "branch_action": branch_action,
        "branch_url": branch_url,
        "command": str(getattr(args, "command_output", "feature.materialize")).strip() or "feature.materialize",
        "feature_id": feature_id,
        "feature_issue_checklist_sync": feature_issue_checklist_sync,
        "feature_issue_body_sync": feature_issue_body_sync,
        "feature_status": feature_status,
        "github_enabled": bool(args.github),
        "issue_description_backfill": issue_description_backfill,
        "issue_id_filter": issue_id_filter,
        "issue_id_queue": issue_id_queue,
        "selected_issue_ids": selected_issue_ids,
        "mode": materialize_mode,
        "mode_action": mode_action,
        "issues_materialized": materialized_issues,
        "missing_issue_mappings": missing_issue_mappings,
        "request_policy": materialize_request_policy,
        "sub_issues_sync": sub_issues_sync,
        "github_milestone_title": milestone_title,
        "milestone_id": milestone_id,
        "write": bool(args.write),
    }
    emit_json(
        _build_feature_materialize_output_payload(
            full_payload=full_payload,
            verbose=bool(getattr(args, "verbose", False)),
        )
    )
    return 0


def _handle_materialize_feature_action(args: Namespace, context: WorkflowContext) -> int:
    """Execute canonical action-first `materialize feature` for feature-level issue sync."""
    feature_id, feature_milestone_num = _parse_feature_id(args.id)
    materialize_mode = str(args.mode).strip()
    if materialize_mode not in {"create", "sync"}:
        raise WorkflowCommandError(
            f"Unsupported feature materialize mode {materialize_mode!r}; expected create or sync.",
            exit_code=4,
        )

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
    if not str(feature_node.get("description", "")).strip():
        feature_node["description"] = _build_default_feature_description(feature_node)
    _normalize_feature_node_layout(feature_node)

    existing_issue_number = _coerce_issue_number(
        feature_node.get("gh_issue_number"),
        feature_node.get("gh_issue_url"),
    )
    existing_issue_url = _optional_text(feature_node.get("gh_issue_url"))
    if materialize_mode == "sync" and existing_issue_number is None:
        raise WorkflowCommandError(
            f"materialize feature --mode sync requires existing feature issue mapping for {feature_id}.",
            exit_code=4,
        )

    branch_name = f"feature/{feature_id}"
    repo_url = _resolve_repository_url(context.root_dir, feature_node)
    branch_url = _build_branch_url(repo_url, branch_name)
    branch_action = plan_canonical_feature_branch(context.root_dir, branch_name)

    github_issue: dict[str, Any]
    if bool(args.write) and bool(args.github):
        github_repo = resolve_github_repository(context.root_dir)
        github_repo_url = _normalize_repository_url(str(github_repo.get("url", "")))
        ensure_github_milestone_exists(
            repo_name_with_owner=github_repo["name_with_owner"],
            milestone_title=milestone_title,
            milestone_id=milestone_id,
        )
        if materialize_mode == "create" and existing_issue_number is not None:
            github_issue = {
                "action": "skipped",
                "gh_issue_number": existing_issue_number,
                "gh_issue_url": existing_issue_url,
                "reason": "already-materialized-create-only",
                "milestone_title": milestone_title,
            }
        else:
            github_issue = _materialize_feature_registration_issue(
                feature_node=feature_node,
                milestone_title=milestone_title,
                repo_name_with_owner=github_repo["name_with_owner"],
                repo_url=github_repo_url,
            )
    else:
        if materialize_mode == "create" and existing_issue_number is not None:
            action = "would-skip"
            reason = "already-materialized-create-only"
        elif materialize_mode == "create":
            action = "would-create"
            reason = ""
        else:
            action = "would-update"
            reason = ""
        github_issue = {
            "action": action,
            "gh_issue_number": existing_issue_number,
            "gh_issue_url": existing_issue_url,
            "milestone_title": milestone_title,
        }
        if reason:
            github_issue["reason"] = reason

    if bool(args.write):
        feature_node["branch_name"] = branch_name
        feature_node["branch_url"] = branch_url
        _touch_updated_at(dev_map)
        _write_json(context.dev_map_path, dev_map)

    payload = {
        "command": "materialize.feature",
        "feature_id": feature_id,
        "mode": materialize_mode,
        "write": bool(args.write),
        "github_enabled": bool(args.github),
        "active_feature_branch": branch_name,
        "branch_action": branch_action,
        "branch_url": branch_url,
        "gh_issue_number": feature_node.get("gh_issue_number"),
        "gh_issue_url": feature_node.get("gh_issue_url"),
        "github_issue": github_issue,
        "output_profile": "compact",
    }
    if bool(getattr(args, "verbose", False)):
        payload["feature_description"] = str(feature_node.get("description", "")).strip() or None
        payload["milestone_id"] = milestone_id
        payload["milestone_title"] = milestone_title
    emit_json(payload)
    return 0


def _handle_materialize_issue_action(args: Namespace, context: WorkflowContext) -> int:
    """Execute canonical action-first `materialize issue` via the shared issue sync engine."""
    materialize_mode = str(args.mode).strip()
    if materialize_mode == "create":
        mapped_mode = "issues-create"
    elif materialize_mode == "sync":
        mapped_mode = "issues-sync"
    else:
        raise WorkflowCommandError(
            f"Unsupported issue materialize mode {materialize_mode!r}; expected create or sync.",
            exit_code=4,
        )

    raw_issue_id = _optional_text(getattr(args, "id", None))
    raw_feature_id = _optional_text(getattr(args, "feature_id", None))
    selected_issue_ids = list(getattr(args, "issue_id", []) or [])
    if raw_issue_id is not None:
        if selected_issue_ids:
            raise WorkflowCommandError(
                "materialize issue does not allow --issue-id when a single --id target is provided.",
                exit_code=4,
            )
        issue_id, feature_local_num, feature_milestone_num = _parse_issue_id(raw_issue_id)
        setattr(args, "id", f"F{feature_local_num}-M{feature_milestone_num}")
        setattr(args, "issue_id", [issue_id])
    else:
        if raw_feature_id is None:
            raise WorkflowCommandError(
                "materialize issue requires either --id <issue_id> or --feature-id <feature_id>.",
                exit_code=4,
            )
        feature_id, _ = _parse_feature_id(raw_feature_id)
        setattr(args, "id", feature_id)
    setattr(args, "mode", mapped_mode)
    setattr(args, "command_output", "materialize.issue")
    return _handle_feature_materialize(args, context)


def _handle_feature_execution_plan(args: Namespace, context: WorkflowContext) -> int:
    """Build ordered task execution plan for one feature subtree."""
    feature_id, _ = _parse_feature_id(args.id)
    dev_map = _load_json(context.dev_map_path)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)
    feature_node = feature_ref["feature"]
    feature_status = str(feature_node.get("status", ""))

    issue_order_state = _resolve_issue_execution_order_from_overlaps(
        context=context,
        dev_map=dev_map,
        feature_id=feature_id,
        feature_node=feature_node,
    )
    ordered_tasks = _collect_feature_tasks(feature_node, only_pending=bool(args.only_pending))
    ordered_tasks = _apply_issue_execution_order(ordered_tasks, issue_order_state["rows"])

    emit_json(
        {
            "command": "feature.execution-plan",
            "feature_id": feature_id,
            "feature_status": feature_status,
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


def _resolve_materialize_request_policy(args: Namespace) -> dict[str, Any]:
    """Normalize and validate materialize request retry/throttle policy options."""
    pause_seconds = float(getattr(args, "pause_seconds", 1.0))
    if pause_seconds < 0:
        raise WorkflowCommandError(
            f"Invalid --pause-seconds {pause_seconds}; expected a value >= 0.",
            exit_code=4,
        )
    max_retries = int(getattr(args, "max_retries", 4))
    if max_retries < 0:
        raise WorkflowCommandError(
            f"Invalid --max-retries {max_retries}; expected a value >= 0.",
            exit_code=4,
        )
    request_timeout = float(getattr(args, "request_timeout", 20.0))
    if request_timeout <= 0:
        raise WorkflowCommandError(
            f"Invalid --request-timeout {request_timeout}; expected a value > 0.",
            exit_code=4,
        )
    return {
        "pause_seconds": pause_seconds,
        "max_retries": max_retries,
        "request_timeout": request_timeout,
    }


def _resolve_materialize_mode_action(materialize_mode: str) -> str:
    """Return explicit mode-action label for materialize command output."""
    if materialize_mode == "bootstrap":
        return "branch-bootstrap-only"
    if materialize_mode == "issues-create":
        return "issue-materialization-create-mode"
    if materialize_mode == "issues-sync":
        return "issue-materialization-sync-mode"
    raise WorkflowCommandError(f"Unsupported materialize mode: {materialize_mode!r}.", exit_code=4)


def _summarize_materialized_issue_actions(materialized_issues: list[dict[str, Any]]) -> dict[str, int]:
    """Return deterministic action counters for materialize issue results."""
    summary = {
        "total": len(materialized_issues),
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "would_create": 0,
        "would_update": 0,
        "would_skip": 0,
    }
    action_to_key = {
        "created": "created",
        "updated": "updated",
        "skipped": "skipped",
        "would-create": "would_create",
        "would-update": "would_update",
        "would-skip": "would_skip",
    }
    for item in materialized_issues:
        action = str(item.get("action", "")).strip()
        key = action_to_key.get(action)
        if key is not None:
            summary[key] += 1
    return summary


def _build_compact_sub_issues_sync(sub_issues_sync: dict[str, Any]) -> dict[str, Any]:
    """Compress verbose sub-issues reconciliation payload to stable actionable summary."""
    added = sub_issues_sync.get("added", [])
    skipped = sub_issues_sync.get("skipped", [])
    errors = sub_issues_sync.get("errors", [])
    added_issue_ids: list[str] = []
    if isinstance(added, list):
        for item in added:
            if not isinstance(item, dict):
                continue
            issue_id = str(item.get("issue_id", "")).strip()
            if issue_id:
                added_issue_ids.append(issue_id)
    compact: dict[str, Any] = {
        "attempted": bool(sub_issues_sync.get("attempted", False)),
        "added_issue_ids": added_issue_ids,
        "added_count": len(added_issue_ids),
        "skipped_count": len(skipped) if isinstance(skipped, list) else 0,
        "errors_count": len(errors) if isinstance(errors, list) else 0,
    }
    reason = str(sub_issues_sync.get("reason", "")).strip()
    if reason:
        compact["reason"] = reason
    if isinstance(errors, list) and errors:
        compact["errors"] = errors
    return compact


def _build_compact_materialized_issues(materialized_issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return shortened per-issue materialize list for default command output."""
    compact_items: list[dict[str, Any]] = []
    for item in materialized_issues:
        issue_id = str(item.get("issue_id", "")).strip()
        action = str(item.get("action", "")).strip()
        compact_item: dict[str, Any] = {
            "issue_id": issue_id,
            "action": action,
        }
        issue_number = _coerce_issue_number(item.get("gh_issue_number"), item.get("gh_issue_url"))
        if issue_number is not None:
            compact_item["gh_issue_number"] = issue_number
        reason = str(item.get("reason", "")).strip()
        if reason:
            compact_item["reason"] = reason
        compact_items.append(compact_item)
    return compact_items


def _build_compact_feature_issue_sync(feature_issue_body_sync: dict[str, Any]) -> dict[str, Any]:
    """Return small feature-issue-body sync status payload."""
    compact: dict[str, Any] = {
        "attempted": bool(feature_issue_body_sync.get("attempted", False)),
        "updated": bool(feature_issue_body_sync.get("updated", False)),
    }
    reason = str(feature_issue_body_sync.get("reason", "")).strip()
    if reason:
        compact["reason"] = reason
    return compact


def _build_feature_materialize_output_payload(
    *,
    full_payload: dict[str, Any],
    verbose: bool,
) -> dict[str, Any]:
    """Build materialize command output payload with compact-by-default diagnostics."""
    if verbose:
        verbose_payload = dict(full_payload)
        verbose_payload["output_profile"] = "verbose"
        return verbose_payload

    materialized_issues = full_payload.get("issues_materialized", [])
    if not isinstance(materialized_issues, list):
        materialized_issues = []
    selected_issue_ids = full_payload.get("selected_issue_ids", [])
    if not isinstance(selected_issue_ids, list):
        selected_issue_ids = []
    sub_issues_sync = full_payload.get("sub_issues_sync", {})
    if not isinstance(sub_issues_sync, dict):
        sub_issues_sync = {}
    feature_issue_body_sync = full_payload.get("feature_issue_body_sync", {})
    if not isinstance(feature_issue_body_sync, dict):
        feature_issue_body_sync = {}
    missing_issue_mappings = full_payload.get("missing_issue_mappings", [])
    if not isinstance(missing_issue_mappings, list):
        missing_issue_mappings = []

    compact_payload = {
        "command": full_payload.get("command"),
        "feature_id": full_payload.get("feature_id"),
        "mode": full_payload.get("mode"),
        "write": bool(full_payload.get("write", False)),
        "github_enabled": bool(full_payload.get("github_enabled", False)),
        "active_feature_branch": full_payload.get("active_feature_branch"),
        "branch_action": full_payload.get("branch_action"),
        "selected_issue_ids": selected_issue_ids,
        "issues_materialized": _build_compact_materialized_issues(materialized_issues),
        "issues_materialized_summary": _summarize_materialized_issue_actions(materialized_issues),
        "sub_issues_sync": _build_compact_sub_issues_sync(sub_issues_sync),
        "feature_issue_body_sync": _build_compact_feature_issue_sync(feature_issue_body_sync),
        "missing_issue_mappings_count": len(missing_issue_mappings),
        "output_profile": "compact",
        "output_hint": "Use --verbose to include full materialize diagnostics.",
    }
    if missing_issue_mappings:
        compact_payload["missing_issue_mapping_issue_ids"] = [
            str(item.get("issue_id", "")).strip()
            for item in missing_issue_mappings
            if isinstance(item, dict) and str(item.get("issue_id", "")).strip()
        ]
    return compact_payload


def _enforce_materialize_issue_status_gate(
    issue_nodes: list[dict[str, Any]],
    *,
    materialize_mode: str,
) -> None:
    """Require Tasked status only for issue nodes that still need GitHub creation."""
    non_tasked_unmapped: list[str] = []
    for issue_node in issue_nodes:
        issue_id = str(issue_node.get("id", "")).strip() or "<unknown-issue>"
        issue_status = str(issue_node.get("status", "")).strip() or "Pending"
        is_mapped = (
            _coerce_issue_number(issue_node.get("gh_issue_number"), issue_node.get("gh_issue_url")) is not None
            and bool(str(issue_node.get("gh_issue_url", "")).strip())
        )
        if is_mapped and materialize_mode == "issues-sync":
            continue
        if issue_status != "Tasked":
            non_tasked_unmapped.append(f"{issue_id}(status={issue_status!r})")
    if non_tasked_unmapped:
        raise WorkflowCommandError(
            "feature materialize requires status 'Tasked' for selected unmapped issue nodes; "
            "run plan tasks for issue/feature first for: "
            + ", ".join(non_tasked_unmapped)
            + ". Mapped issues can be synced in issues-sync mode without Tasked status.",
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


def _resolve_plan_tasks_issue_batch_queue(raw_issue_ids: Any) -> list[str]:
    """Normalize issue-id queue for `plan tasks for issues` and enforce no duplicates."""
    if not isinstance(raw_issue_ids, list) or not raw_issue_ids:
        raise WorkflowCommandError(
            "plan tasks for issues requires at least one --issue-id value.",
            exit_code=4,
        )
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


def _assert_issue_queue_belongs_to_feature(
    *,
    issue_id_queue: list[str],
    feature_id: str,
    feature_milestone_num: int,
    feature_local_num: int,
    command_label: str,
) -> None:
    """Validate that all queued issue IDs belong to the same selected feature chain."""
    for issue_id in issue_id_queue:
        try:
            _assert_issue_belongs_to_feature(
                issue_id=issue_id,
                feature_id=feature_id,
                feature_milestone_num=feature_milestone_num,
                feature_local_num=feature_local_num,
            )
        except WorkflowCommandError as error:
            raise WorkflowCommandError(
                f"{command_label} requires issue IDs from one feature chain; {error}",
                exit_code=4,
            ) from error


def _resolve_plan_tasks_issue_queue(
    raw_issue_ids: Any,
    *,
    feature_id: str,
    feature_milestone_num: int,
    feature_local_num: int,
) -> list[str]:
    """Normalize optional plan-tasks issue queue and validate ownership chain."""
    if raw_issue_ids is None:
        return []
    if not isinstance(raw_issue_ids, list):
        raw_issue_ids = [raw_issue_ids]
    issue_id_queue = _resolve_plan_tasks_issue_batch_queue(raw_issue_ids)
    _assert_issue_queue_belongs_to_feature(
        issue_id_queue=issue_id_queue,
        feature_id=feature_id,
        feature_milestone_num=feature_milestone_num,
        feature_local_num=feature_local_num,
        command_label="plan tasks for issues",
    )
    return issue_id_queue


def _filter_issue_payloads_for_plan_tasks(
    issue_payloads: list[dict[str, Any]],
    issue_id_filter: str | None,
    issue_id_queue: list[str],
    command_label: str,
) -> list[dict[str, Any]]:
    """Restrict delta issue payloads to selected issue ID(s) for issue-scoped decomposition."""
    if issue_id_filter is None and not issue_id_queue:
        return issue_payloads
    expected_issue_ids = issue_id_queue if issue_id_queue else [issue_id_filter] if issue_id_filter else []
    expected_issue_set = set(expected_issue_ids)
    filtered_payloads: list[dict[str, Any]] = []
    for issue_index, issue_payload in enumerate(issue_payloads):
        payload_issue_id = _required_string_field(issue_payload, "id", f"issues[{issue_index}]")
        if payload_issue_id not in expected_issue_set:
            expected_joined = ", ".join(expected_issue_ids)
            raise WorkflowCommandError(
                f"{command_label} delta contains non-target issue {payload_issue_id}; "
                f"expected only: {expected_joined}.",
                exit_code=4,
            )
        filtered_payloads.append(issue_payload)
    return filtered_payloads


def _enforce_plan_tasks_issue_status_gate(
    *,
    feature_node: dict[str, Any],
    issue_payloads: list[dict[str, Any]],
    issue_id_filter: str | None,
    issue_id_queue: list[str],
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
    for issue_id in issue_id_queue:
        if issue_id not in target_issue_ids:
            target_issue_ids.append(issue_id)

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
            issue_title = str(issue_payload.get("title", issue_id)).strip() or issue_id
            issue_node = {
                "id": issue_id,
                "title": issue_title,
                "description": _build_default_issue_description({"id": issue_id, "title": issue_title}),
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
        if "description" in issue_payload:
            issue_node["description"] = _required_string_field(
                issue_payload,
                "description",
                f"issues[{issue_index}]",
            )
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
        _normalize_issue_node_layout(issue_node)
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
    *,
    max_retries: int,
    retry_pause_seconds: float,
    request_timeout: float,
) -> dict[str, Any]:
    """Create or update one GitHub issue from a local DEV_MAP issue node with retries."""
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
            max_retries=max_retries,
            retry_pause_seconds=retry_pause_seconds,
            timeout_seconds=request_timeout,
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
            max_retries=max_retries,
            retry_pause_seconds=retry_pause_seconds,
            timeout_seconds=request_timeout,
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
    """Build concise GitHub body from one issue description."""
    issue_description = _resolve_issue_description(issue_node)
    return issue_description.strip() + "\n"


def _collect_missing_issue_mappings(issue_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect issue mapping gaps for deterministic materialize output."""
    missing: list[dict[str, Any]] = []
    for issue in issue_nodes:
        if not isinstance(issue, dict):
            continue
        issue_id = str(issue.get("id", "")).strip()
        missing_fields: list[str] = []
        if _coerce_issue_number(issue.get("gh_issue_number"), issue.get("gh_issue_url")) is None:
            missing_fields.append("gh_issue_number")
        if not str(issue.get("gh_issue_url", "")).strip():
            missing_fields.append("gh_issue_url")
        if not missing_fields:
            continue
        missing.append({"issue_id": issue_id, "missing_fields": missing_fields})
    return missing


def _reconcile_feature_sub_issues(
    *,
    feature_node: dict[str, Any],
    issue_nodes: list[dict[str, Any]],
    repo_name_with_owner: str,
    max_retries: int,
    retry_pause_seconds: float,
    request_timeout: float,
) -> dict[str, Any]:
    """Reconcile parent/child sub-issues with retry-aware GitHub API calls."""
    parent_issue_number = _coerce_issue_number(feature_node.get("gh_issue_number"), feature_node.get("gh_issue_url"))
    if parent_issue_number is None:
        return {
            "attempted": False,
            "added": [],
            "skipped": [],
            "errors": [],
            "existing_sub_issue_numbers": [],
            "target_sub_issue_numbers": [],
            "parent_issue_number": None,
            "reason": "feature-issue-not-mapped",
        }

    mapped_children: list[tuple[str, int]] = []
    for issue in issue_nodes:
        if not isinstance(issue, dict):
            continue
        issue_id = str(issue.get("id", "")).strip()
        issue_number = _coerce_issue_number(issue.get("gh_issue_number"), issue.get("gh_issue_url"))
        issue_url = str(issue.get("gh_issue_url", "")).strip()
        if issue_number is None or not issue_url:
            continue
        mapped_children.append((issue_id, issue_number))

    target_numbers = [number for _, number in mapped_children]
    errors: list[str] = []
    try:
        existing_numbers = gh_issue_list_sub_issue_numbers(
            repo_name_with_owner=repo_name_with_owner,
            parent_issue_number=parent_issue_number,
            max_retries=max_retries,
            retry_pause_seconds=retry_pause_seconds,
            timeout_seconds=request_timeout,
        )
    except WorkflowCommandError as error:
        return {
            "attempted": True,
            "added": [],
            "skipped": [],
            "errors": [str(error)],
            "existing_sub_issue_numbers": [],
            "target_sub_issue_numbers": target_numbers,
            "parent_issue_number": parent_issue_number,
        }

    existing_set = set(existing_numbers)
    added: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for child_index, (issue_id, child_number) in enumerate(mapped_children):
        if child_number == parent_issue_number:
            skipped.append(
                {
                    "issue_id": issue_id,
                    "gh_issue_number": child_number,
                    "reason": "parent-issue-cannot-be-sub-issue",
                }
            )
            continue
        if child_number in existing_set:
            skipped.append(
                {
                    "issue_id": issue_id,
                    "gh_issue_number": child_number,
                    "reason": "already-linked",
                }
            )
            continue
        try:
            gh_issue_add_sub_issue(
                repo_name_with_owner=repo_name_with_owner,
                parent_issue_number=parent_issue_number,
                sub_issue_number=child_number,
                max_retries=max_retries,
                retry_pause_seconds=retry_pause_seconds,
                timeout_seconds=request_timeout,
            )
        except WorkflowCommandError as error:
            errors.append(
                f"issue {issue_id} #{child_number}: {error}"
            )
            continue
        existing_set.add(child_number)
        added.append({"issue_id": issue_id, "gh_issue_number": child_number})
        if retry_pause_seconds > 0 and child_index < len(mapped_children) - 1:
            time.sleep(retry_pause_seconds)

    return {
        "attempted": True,
        "added": added,
        "skipped": skipped,
        "errors": errors,
        "existing_sub_issue_numbers": existing_numbers,
        "target_sub_issue_numbers": target_numbers,
        "parent_issue_number": parent_issue_number,
    }


def _sync_feature_issue_body_for_materialize(
    *,
    feature_node: dict[str, Any],
    repo_name_with_owner: str,
    milestone_title: str,
    repo_url: str | None,
    max_retries: int,
    retry_pause_seconds: float,
    request_timeout: float,
) -> dict[str, Any]:
    """Refresh mapped feature-level GitHub issue title/body during issues-sync."""
    feature_issue_number = _coerce_issue_number(feature_node.get("gh_issue_number"), feature_node.get("gh_issue_url"))
    if feature_issue_number is None:
        return {
            "attempted": False,
            "updated": False,
            "reason": "feature-issue-not-mapped",
            "gh_issue_number": None,
        }

    feature_title = str(feature_node.get("title", "")).strip() or str(feature_node.get("id", "")).strip()
    feature_body = _build_feature_registration_issue_body(feature_node)
    gh_issue_edit(
        repo_name_with_owner=repo_name_with_owner,
        issue_number=feature_issue_number,
        title=feature_title,
        body=feature_body,
        milestone_title=milestone_title,
        max_retries=max_retries,
        retry_pause_seconds=retry_pause_seconds,
        timeout_seconds=request_timeout,
    )
    feature_node["gh_issue_number"] = feature_issue_number
    if repo_url:
        feature_node["gh_issue_url"] = _build_issue_url(repo_url, feature_issue_number)
    return {
        "attempted": True,
        "updated": True,
        "reason": "feature-issue-body-updated",
        "gh_issue_number": feature_issue_number,
        "gh_issue_url": feature_node.get("gh_issue_url"),
    }


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
    """Build concise feature-level body from feature description only."""
    return _resolve_feature_description(feature_node).strip() + "\n"


def _resolve_feature_description(feature_node: dict[str, Any]) -> str:
    """Return feature description from node or deterministic fallback from title."""
    description = str(feature_node.get("description", "")).strip()
    if description:
        return description
    return _build_default_feature_description(feature_node)


def _build_default_feature_description(feature_node: dict[str, Any]) -> str:
    """Build concise default feature description with problem/change context."""
    feature_title = str(feature_node.get("title", "")).strip() or str(feature_node.get("id", "")).strip() or "feature scope"
    compact_title = " ".join(feature_title.split()).strip().rstrip(".")
    if not compact_title:
        return "This feature defines the required behavior and expected outcome."
    title_text = compact_title[0].lower() + compact_title[1:] if len(compact_title) > 1 else compact_title.lower()
    return (
        f"This feature addresses {title_text} by defining the required change "
        "and the expected user-visible outcome."
    )


def _backfill_missing_issue_descriptions_for_feature(feature_node: dict[str, Any]) -> dict[str, Any]:
    """Backfill missing issue descriptions inside one feature node."""
    issues = feature_node.get("issues", [])
    if not isinstance(issues, list):
        return {"count": 0, "issue_ids": []}
    backfilled_issue_ids: list[str] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        issue_id = str(issue.get("id", "")).strip()
        if str(issue.get("description", "")).strip():
            _normalize_issue_node_layout(issue)
            continue
        issue["description"] = _build_default_issue_description(issue)
        _normalize_issue_node_layout(issue)
        if issue_id:
            backfilled_issue_ids.append(issue_id)
    return {"count": len(backfilled_issue_ids), "issue_ids": backfilled_issue_ids}


def _resolve_issue_description(issue_node: dict[str, Any]) -> str:
    """Return issue description from node or deterministic fallback from title."""
    description = str(issue_node.get("description", "")).strip()
    if description:
        return description
    return _build_default_issue_description(issue_node)


def _build_default_issue_description(issue_node: dict[str, Any]) -> str:
    """Build concise default issue description with problem/change context."""
    issue_title = str(issue_node.get("title", "")).strip() or str(issue_node.get("id", "")).strip() or "Issue"
    compact_title = " ".join(issue_title.split()).strip().rstrip(".")
    if not compact_title:
        return "Resolve the issue."
    title_text = compact_title[0].lower() + compact_title[1:] if len(compact_title) > 1 else compact_title.lower()
    return (
        f"This issue addresses {title_text} by defining the required change and "
        "the problem it resolves."
    )


def _normalize_feature_node_layout(feature_node: dict[str, Any]) -> None:
    """Place feature description directly under title while preserving existing fields."""
    ordered_keys = (
        "id",
        "title",
        "description",
        "status",
        "track",
        "gh_issue_number",
        "gh_issue_url",
        "issues",
        "branch_name",
        "branch_url",
    )
    reordered: dict[str, Any] = {}
    for key in ordered_keys:
        if key in feature_node:
            reordered[key] = feature_node[key]
    for key, value in feature_node.items():
        if key in reordered:
            continue
        reordered[key] = value
    feature_node.clear()
    feature_node.update(reordered)


def _normalize_feature_issue_nodes_layout(feature_node: dict[str, Any]) -> None:
    """Normalize issue-node field order for one feature subtree."""
    issues = feature_node.get("issues", [])
    if not isinstance(issues, list):
        return
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        _normalize_issue_node_layout(issue)


def _normalize_issue_node_layout(issue_node: dict[str, Any]) -> None:
    """Place description directly under title while preserving all existing fields."""
    ordered_keys = (
        "id",
        "title",
        "description",
        "status",
        "gh_issue_number",
        "gh_issue_url",
        "tasks",
    )
    reordered: dict[str, Any] = {}
    for key in ordered_keys:
        if key in issue_node:
            reordered[key] = issue_node[key]
    for key, value in issue_node.items():
        if key in reordered:
            continue
        reordered[key] = value
    issue_node.clear()
    issue_node.update(reordered)


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


def _build_feature_node(feature_id: str, title: str, description: str, track: str) -> dict[str, Any]:
    """Build canonical feature node shape for DEV_MAP."""
    normalized_title = title.strip()
    description_value = description.strip() or _build_default_feature_description(
        {"id": feature_id, "title": normalized_title}
    )
    return {
        "id": feature_id,
        "title": normalized_title,
        "description": description_value,
        "status": "Planned",
        "track": track.strip(),
        "gh_issue_number": None,
        "gh_issue_url": None,
        "issues": [],
        "branch_name": None,
        "branch_url": None,
    }


def _build_issue_node(issue_id: str, title: str, description: str) -> dict[str, Any]:
    """Build canonical issue node shape for DEV_MAP."""
    normalized_title = title.strip()
    description_value = description.strip() or _build_default_issue_description(
        {"id": issue_id, "title": normalized_title}
    )
    return {
        "id": issue_id,
        "title": normalized_title,
        "description": description_value,
        "status": "Pending",
        "gh_issue_number": None,
        "gh_issue_url": None,
        "tasks": [],
    }


def _resolve_markdown_command_input(args: Namespace, *, command_label: str) -> dict[str, Any]:
    """Resolve title/description values from flags or markdown draft input."""
    raw_title = str(getattr(args, "title", "") or "").strip()
    raw_description = str(getattr(args, "description", "") or "").strip()
    raw_input = str(getattr(args, "input", "") or "").strip()
    if raw_input and (raw_title or raw_description):
        raise WorkflowCommandError(
            "Cannot combine --input with --title/--description. Use one input method only.",
            exit_code=4,
        )
    if not raw_input:
        return {
            "title": raw_title,
            "description": raw_description,
            "warnings": [],
        }
    parsed = parse_feature_issue_template(Path(raw_input))
    return {
        "title": str(parsed.get("title", "")).strip(),
        "description": str(parsed.get("description", "")).strip(),
        "warnings": list(parsed.get("warnings", [])),
        "input_path": raw_input,
        "command_label": command_label,
    }


def _optional_text(raw_value: Any) -> str | None:
    """Return one optional non-empty string value without turning None into text."""
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    return value or None


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


def _build_feature_plan_scaffold(feature_id: str, feature_title: str) -> str:
    """Build default feature plan markdown scaffold."""
    normalized_feature_title = feature_title.strip() or feature_id
    return (
        f"## {feature_id}\n\n"
        f"{normalized_feature_title}\n\n"
        "### Expected Behaviour\n"
        "- TODO\n\n"
        "### Dependencies\n"
        "- TODO\n\n"
        "### Decomposition\n"
        "1. TODO\n\n"
        "### Issue/Task Decomposition Assessment\n"
        "- TODO\n"
    )


def _render_plan_issue_dry_run_action(block_action: str) -> str:
    """Convert persisted plan-issue action to dry-run action token."""
    if block_action == "created":
        return "would-create"
    if block_action == "updated":
        return "would-update"
    return "unchanged"


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


def _register_scope_selector_args(
    parser: argparse.ArgumentParser,
    *,
    allow_all: bool,
) -> None:
    """Register common feature/issue/all selector flags for plan subcommands."""
    parser.add_argument("--feature-id", help="Feature ID selector.")
    parser.add_argument("--issue-id", help="Issue ID selector.")
    if allow_all:
        parser.add_argument("--all", action="store_true", help="Select all indexed scopes.")


def _resolve_scope_selector(
    *,
    args: Namespace,
    allow_all: bool,
) -> dict[str, Any]:
    """Normalize and validate feature/issue/all selector combination."""
    raw_feature_id = str(getattr(args, "feature_id", "") or "").strip()
    raw_issue_id = str(getattr(args, "issue_id", "") or "").strip()
    use_all = bool(getattr(args, "all", False)) if allow_all else False
    selected_count = int(bool(raw_feature_id)) + int(bool(raw_issue_id)) + int(use_all)
    if selected_count != 1:
        allowed = "--feature-id, --issue-id"
        if allow_all:
            allowed += ", --all"
        raise WorkflowCommandError(f"Select exactly one scope via {allowed}.", exit_code=4)
    if raw_feature_id:
        feature_id, _ = _parse_feature_id(raw_feature_id)
        return {"scope_type": "feature", "scope_id": feature_id}
    if raw_issue_id:
        issue_id, _, _ = _parse_issue_id(raw_issue_id)
        return {"scope_type": "issue", "scope_id": issue_id}
    return {"scope_type": "all", "scope_id": "all"}


def _extract_feature_section_lines(feature_plans_path: Path, feature_id: str) -> list[str]:
    """Return one feature section as split lines."""
    return _extract_feature_plan_section(feature_plans_path, feature_id).splitlines()


def _extract_issue_dependencies_block_lines(section_lines: list[str], issue_id: str) -> list[str]:
    """Extract raw issue Dependencies block lines for one issue plan block."""
    bounds = _find_issue_plan_block_bounds(section_lines, issue_id)
    if bounds is None:
        raise WorkflowCommandError(f"Issue plan block for {issue_id} not found in FEATURE_PLANS.", exit_code=4)
    start_index, end_index = bounds
    subheadings: dict[str, tuple[int, int]] = {}
    ordered_subheadings: list[tuple[str, int]] = []
    for index in range(start_index + 1, end_index):
        match = SECTION_H4_PATTERN.match(section_lines[index])
        if match is None:
            continue
        heading = match.group(1).strip()
        ordered_subheadings.append((heading, index))
    for index, (heading, line_index) in enumerate(ordered_subheadings):
        block_end = end_index
        if index + 1 < len(ordered_subheadings):
            block_end = ordered_subheadings[index + 1][1]
        subheadings[heading] = (line_index + 1, block_end)
    if "Dependencies" not in subheadings:
        raise WorkflowCommandError(f"Issue plan block {issue_id} is missing `#### Dependencies` section.", exit_code=4)
    dep_start, dep_end = subheadings["Dependencies"]
    dependency_lines = [line.rstrip() for line in section_lines[dep_start:dep_end] if line.strip()]
    if not dependency_lines:
        raise WorkflowCommandError(f"Issue plan block {issue_id} has empty `#### Dependencies` content.", exit_code=4)
    return dependency_lines


def _parse_dependency_line(raw_line: str, *, issue_id: str) -> dict[str, str]:
    """Parse one canonical dependency line from an issue Dependencies block."""
    stripped = raw_line.strip()
    match = DEPENDENCY_LINE_PATTERN.fullmatch(stripped)
    if match is None:
        raise WorkflowCommandError(
            f"Issue plan block {issue_id} has invalid dependency line {stripped!r}; "
            "use `- file: ...`, `- module: ...`, `- function: ...`, or `- class: ...`.",
            exit_code=4,
        )
    kind = match.group("kind").strip()
    target = match.group("target").strip()
    reason = str(match.group("reason") or "").strip()
    if not target:
        raise WorkflowCommandError(
            f"Issue plan block {issue_id} has dependency line without target: {stripped!r}.",
            exit_code=4,
        )
    return {
        "kind": kind,
        "target": target,
        "reason": reason,
        "surface": f"{kind}: {target}",
    }


def _normalize_dependency_surface(surface: str) -> str:
    """Normalize one dependency surface string for deterministic lookups."""
    return re.sub(r"\s+", " ", str(surface).strip().lower())


def _collect_issue_dependency_entries(
    *,
    issue_id: str,
    section_lines: list[str],
) -> list[dict[str, str]]:
    """Collect parsed dependency entries for one issue plan block."""
    entries: list[dict[str, str]] = []
    for raw_line in _extract_issue_dependencies_block_lines(section_lines, issue_id):
        entries.append(_parse_dependency_line(raw_line, issue_id=issue_id))
    return entries


def _build_related_issue_draft(index_payload: dict[str, Any], issue_id: str) -> list[dict[str, Any]]:
    """Build candidate related-issue records for one issue scope."""
    by_issue = index_payload.get("by_issue", {})
    by_surface = index_payload.get("by_surface", {})
    issue_entry = by_issue.get(issue_id)
    if not isinstance(issue_entry, dict):
        raise WorkflowCommandError(
            f"Issue {issue_id} is missing from ISSUE_DEP_INDEX; run index-dependencies first.",
            exit_code=4,
        )
    related: dict[str, set[str]] = {}
    for surface_key in issue_entry.get("surface_keys", []):
        bucket = by_surface.get(surface_key, [])
        for candidate_issue_id in bucket:
            if candidate_issue_id == issue_id:
                continue
            related.setdefault(candidate_issue_id, set()).add(surface_key)
    return [
        {
            "issues": [issue_id, candidate_issue_id],
            "matched_surfaces": sorted(surfaces, key=_normalize_dependency_surface),
        }
        for candidate_issue_id, surfaces in sorted(related.items())
    ]


def _build_feature_related_pairs_draft(index_payload: dict[str, Any], feature_node: dict[str, Any]) -> list[dict[str, Any]]:
    """Build candidate issue-pair records for one feature scope."""
    issue_ids = [str(issue.get("id", "")).strip() for issue in _collect_feature_issue_nodes(feature_node)]
    by_issue = index_payload.get("by_issue", {})
    pairs: list[dict[str, Any]] = []
    for index, left_issue_id in enumerate(issue_ids):
        left_entry = by_issue.get(left_issue_id)
        if not isinstance(left_entry, dict):
            continue
        left_surfaces = set(left_entry.get("surface_keys", []))
        for right_issue_id in issue_ids[index + 1 :]:
            right_entry = by_issue.get(right_issue_id)
            if not isinstance(right_entry, dict):
                continue
            matched_surfaces = sorted(left_surfaces & set(right_entry.get("surface_keys", [])), key=_normalize_dependency_surface)
            if not matched_surfaces:
                continue
            pairs.append({"issues": [left_issue_id, right_issue_id], "matched_surfaces": matched_surfaces})
    return pairs


def _collect_feature_issue_nodes(feature_node: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized issue node list for one feature node."""
    issues = feature_node.get("issues", [])
    if not isinstance(issues, list):
        raise WorkflowCommandError("Feature issue list is invalid in DEV_MAP.", exit_code=4)
    return [issue for issue in issues if isinstance(issue, dict) and str(issue.get("id", "")).strip()]


def _build_dependency_index_for_scope(
    *,
    context: WorkflowContext,
    dev_map: dict[str, Any],
    scope_type: str,
    scope_id: str,
) -> dict[str, Any]:
    """Build deterministic dependency index payload for one selected scope."""
    by_issue: dict[str, dict[str, Any]] = {}
    by_surface: dict[str, list[str]] = {}
    if scope_type == "feature":
        feature_ref = _find_feature(dev_map, scope_id)
        if feature_ref is None:
            raise WorkflowCommandError(f"Feature {scope_id} not found in DEV_MAP.", exit_code=4)
        feature_id = scope_id
        issue_nodes = _collect_feature_issue_nodes(feature_ref["feature"])
        section_lines = _extract_feature_section_lines(context.feature_plans_path, feature_id)
    elif scope_type == "issue":
        issue_ref = _resolve_issue_owner_feature(dev_map, scope_id)
        feature_id = issue_ref["feature_id"]
        issue_nodes = [issue_ref["issue"]]
        section_lines = _extract_feature_section_lines(context.feature_plans_path, feature_id)
    else:
        raise WorkflowCommandError(f"Unsupported dependency-index scope {scope_type!r}.", exit_code=4)

    for issue_node in issue_nodes:
        issue_id = str(issue_node.get("id", "")).strip()
        issue_status = str(issue_node.get("status", "")).strip() or "Pending"
        entries = _collect_issue_dependency_entries(issue_id=issue_id, section_lines=section_lines)
        surfaces = [entry["surface"] for entry in entries]
        surface_keys = sorted({_normalize_dependency_surface(surface) for surface in surfaces})
        by_issue[issue_id] = {
            "surface_keys": surface_keys,
        }
        for surface_key in surface_keys:
            bucket = by_surface.setdefault(surface_key, [])
            if issue_id not in bucket:
                bucket.append(issue_id)

    for surface_key, issue_ids in list(by_surface.items()):
        by_surface[surface_key] = sorted(issue_ids)

    return build_issue_dependency_index_contract_payload(
        {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "by_issue": dict(sorted(by_issue.items())),
            "by_surface": dict(sorted(by_surface.items())),
        }
    )


def _upsert_issue_plan_block_in_section(
    *,
    section_lines: list[str],
    issue_id: str,
    issue_title: str,
    issue_node: dict[str, Any],
) -> tuple[list[str], str]:
    """Create or update one canonical issue-plan block inside a feature section."""
    block_lines = _build_issue_plan_block_lines(issue_id=issue_id, issue_title=issue_title, issue_node=issue_node)
    updated_section_lines = list(section_lines)
    existing_bounds = _find_issue_plan_block_bounds(updated_section_lines, issue_id)
    if existing_bounds is not None:
        start_index, end_index = existing_bounds
        existing_block = updated_section_lines[start_index:end_index]
        if existing_block == block_lines:
            return updated_section_lines, "unchanged"
        updated_section_lines[start_index:end_index] = block_lines
        return updated_section_lines, "updated"

    insert_index = _resolve_issue_plan_block_insert_index(updated_section_lines)
    insert_lines = list(block_lines)
    if insert_index > 0 and updated_section_lines[insert_index - 1].strip():
        insert_lines = [""] + insert_lines
    updated_section_lines[insert_index:insert_index] = insert_lines
    return updated_section_lines, "created"


def _build_issue_plan_block_lines(*, issue_id: str, issue_title: str, issue_node: dict[str, Any]) -> list[str]:
    """Build canonical issue-plan markdown block lines for one issue node."""
    normalized_title = issue_title.strip() or issue_id
    issue_description = str(issue_node.get("description", "")).strip()
    tasks = issue_node.get("tasks", [])
    task_items = [task for task in tasks if isinstance(task, dict)] if isinstance(tasks, list) else []
    task_ids = [str(task.get("id", "")).strip() for task in task_items if str(task.get("id", "")).strip()]
    decomposition_steps: list[str] = []
    for index, task in enumerate(task_items, start=1):
        task_title = str(task.get("title", "")).strip()
        task_id = str(task.get("id", "")).strip()
        task_label = task_title or (f"task {task_id}" if task_id else "mapped task")
        decomposition_steps.append(f"{index}. Implement {task_label}.")
    if not decomposition_steps:
        decomposition_steps = ["1. Implement issue scope and produce executable task updates."]
    task_ids_line = ", ".join(task_ids) if task_ids else "none"
    return [
        f"### {issue_id} - {normalized_title}",
        "",
        "#### Expected Behaviour",
        issue_description or "- TODO",
        "",
        "#### Dependencies",
        f"- DEV_MAP issue node `{issue_id}` and mapped workflow tasks.",
        "",
        "#### Decomposition",
        *decomposition_steps,
        "",
        "#### Issue/Task Decomposition Assessment",
        f"- task_count = {len(task_items)}",
        f"- task_ids = {task_ids_line}",
        "",
    ]


def _find_issue_plan_block_bounds(section_lines: list[str], issue_id: str) -> tuple[int, int] | None:
    """Find canonical issue-plan block bounds by issue ID inside one feature section."""
    heading_indexes: list[tuple[int, str]] = []
    for index, line in enumerate(section_lines):
        canonical_match = CANONICAL_ISSUE_PLAN_BLOCK_HEADING_PATTERN.fullmatch(line.strip())
        if canonical_match is None:
            continue
        heading_indexes.append((index, canonical_match.group("issue_id").strip()))
    for heading_index, (start_index, candidate_issue_id) in enumerate(heading_indexes):
        if candidate_issue_id != issue_id:
            continue
        end_index = len(section_lines)
        if heading_index + 1 < len(heading_indexes):
            end_index = heading_indexes[heading_index + 1][0]
        for probe_index in range(start_index + 1, end_index):
            stripped = section_lines[probe_index].strip()
            if stripped.startswith("## ") or stripped.startswith("### "):
                end_index = probe_index
                break
        return start_index, end_index
    return None


def _resolve_issue_plan_block_insert_index(section_lines: list[str]) -> int:
    """Resolve insertion index for a new issue-plan block in one feature section."""
    last_block_end: int | None = None
    heading_indexes: list[int] = []
    for index, line in enumerate(section_lines):
        if CANONICAL_ISSUE_PLAN_BLOCK_HEADING_PATTERN.fullmatch(line.strip()) is not None:
            heading_indexes.append(index)
    for heading_index, start_index in enumerate(heading_indexes):
        end_index = len(section_lines)
        if heading_index + 1 < len(heading_indexes):
            end_index = heading_indexes[heading_index + 1]
        for probe_index in range(start_index + 1, end_index):
            stripped = section_lines[probe_index].strip()
            if stripped.startswith("## ") or stripped.startswith("### "):
                end_index = probe_index
                break
        last_block_end = end_index
    if last_block_end is not None:
        return last_block_end
    for index, line in enumerate(section_lines):
        if line.strip() == "### Issue/Task Decomposition Assessment":
            return index
    return len(section_lines)


def _lint_existing_issue_plan_block_if_present(section_lines: list[str], issue_id: str) -> None:
    """Validate existing target issue block before upsert when block already exists."""
    block_bounds = _find_issue_plan_block_bounds(section_lines, issue_id)
    if block_bounds is None:
        return
    start_index, end_index = block_bounds
    _lint_one_issue_plan_block(lines=section_lines, start_index=start_index, end_index=end_index, issue_id=issue_id)


def _lint_plan_issue_block_scoped(section_lines: list[str], issue_id: str, strict: bool) -> None:
    """Run scoped lint for one target issue-plan block inside one feature section."""
    block_bounds = _find_issue_plan_block_bounds(section_lines, issue_id)
    if block_bounds is None:
        raise WorkflowCommandError(
            f"Issue plan block for {issue_id} is missing after plan-issue upsert.",
            exit_code=4,
        )
    start_index, end_index = block_bounds
    _lint_one_issue_plan_block(lines=section_lines, start_index=start_index, end_index=end_index, issue_id=issue_id)
    if not strict:
        return
    content_lines = _filter_section_content(section_lines[start_index + 1 : end_index])
    if _contains_placeholder_plan_content(content_lines):
        raise WorkflowCommandError(
            f"Issue plan block {issue_id} contains placeholder content under --strict lint.",
            exit_code=4,
        )


def _enforce_plan_issue_order_row_presence(section_lines: list[str], issue_id: str, issue_status: str) -> None:
    """Require active issue to be present in read-only Issue Execution Order rows."""
    if issue_status in ISSUE_TERMINAL_STATUSES:
        return
    section_text = "\n".join(section_lines) + "\n"
    order_block_found, parsed_rows = _parse_issue_execution_order_rows(section_text)
    if not order_block_found:
        raise WorkflowCommandError(
            f"plan-issue requires {ISSUE_EXECUTION_ORDER_HEADING} with active row for {issue_id}.",
            exit_code=4,
        )
    row_issue_ids = {row["id"] for row in parsed_rows}
    if issue_id not in row_issue_ids:
        raise WorkflowCommandError(
            f"plan-issue requires active issue row `{issue_id}` in {ISSUE_EXECUTION_ORDER_HEADING}.",
            exit_code=4,
        )


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
        if strict and _contains_placeholder_plan_content(content_lines):
            raise WorkflowCommandError(
                f"Heading {heading!r} contains placeholder content under --strict lint.",
                exit_code=4,
            )
        messages.append(f"{heading}:ok")

    if feature_id is not None and feature_node is not None:
        _lint_issue_plan_blocks(
            section_text=section_text,
            feature_id=feature_id,
            feature_node=feature_node,
            strict=strict,
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
    strict: bool,
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
        _lint_one_issue_plan_block(
            lines=lines,
            start_index=start_index,
            end_index=end_index,
            issue_id=issue_id,
            strict=strict,
        )


def _lint_one_issue_plan_block(
    lines: list[str],
    start_index: int,
    end_index: int,
    issue_id: str,
    strict: bool = False,
) -> None:
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
        if strict and _contains_placeholder_plan_content(content_lines):
            raise WorkflowCommandError(
                f"Issue plan block {issue_id} section {heading!r} contains placeholder content under --strict lint.",
                exit_code=4,
            )
        if heading == "Dependencies":
            for raw_line in content_lines:
                _parse_dependency_line(raw_line, issue_id=issue_id)


def _contains_placeholder_plan_content(content_lines: list[str]) -> bool:
    """Return True when section content still contains placeholder authoring text."""
    placeholder_tokens = ("TODO", "TBD", "PLACEHOLDER")
    placeholder_phrases = (
        "describe expected behaviour",
        "describe runtime behaviour",
        "fill expected behaviour",
    )
    for line in content_lines:
        normalized = str(line).strip().lower()
        if not normalized:
            continue
        if any(token in normalized.upper() for token in placeholder_tokens):
            return True
        if any(phrase in normalized for phrase in placeholder_phrases):
            return True
    return False


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


def _resolve_issue_execution_order_from_overlaps(
    *,
    context: WorkflowContext,
    dev_map: dict[str, Any],
    feature_id: str,
    feature_node: dict[str, Any],
) -> dict[str, Any]:
    """Resolve feature issue order from the canonical ISSUE_OVERLAPS payload."""
    overlaps_payload = load_issue_overlaps_payload(context)
    ordered_issue_ids = _select_feature_issue_execution_order(
        ordered_issue_ids=overlaps_payload.get("issue_execution_order", {}).get("ordered_issue_ids", []),
        feature_node=feature_node,
    )
    issue_by_id = {
        str(issue.get("id", "")).strip(): issue
        for issue in _collect_feature_issue_nodes(feature_node)
    }
    rows = [
        {
            "id": issue_id,
            "title": str(issue_by_id[issue_id].get("title", "")).strip(),
            "status": str(issue_by_id[issue_id].get("status", "")).strip(),
        }
        for issue_id in ordered_issue_ids
        if issue_id in issue_by_id
    ]
    next_issue = rows[0] if rows else None
    return {
        "active_issue_count": len(rows),
        "next_issue": next_issue,
        "rows": rows,
    }


def _select_feature_issue_execution_order(*, ordered_issue_ids: list[str], feature_node: dict[str, Any]) -> list[str]:
    """Project global issue order onto one feature while keeping uncovered issues in DEV_MAP order."""
    active_issue_ids = [
        str(issue.get("id", "")).strip()
        for issue in _collect_feature_issue_nodes(feature_node)
        if str(issue.get("status", "")).strip() not in ISSUE_TERMINAL_STATUSES
    ]
    ordered_subset = [issue_id for issue_id in ordered_issue_ids if issue_id in active_issue_ids]
    remaining_issue_ids = [issue_id for issue_id in active_issue_ids if issue_id not in ordered_subset]
    return ordered_subset + remaining_issue_ids


def _build_global_issue_execution_order(*, dev_map: dict[str, Any], overlaps: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one deterministic global issue order from active DEV_MAP issues and dependency overlaps."""
    active_issue_ids = _collect_active_issue_ids_in_dev_map_order(dev_map)
    if not active_issue_ids:
        return {"ordered_issue_ids": []}

    adjacency: dict[str, set[str]] = {issue_id: set() for issue_id in active_issue_ids}
    indegree: dict[str, int] = {issue_id: 0 for issue_id in active_issue_ids}
    for item in overlaps:
        if not isinstance(item, dict) or str(item.get("type", "")).strip() != "dependency":
            continue
        order = str(item.get("order", "")).strip()
        if "->" not in order:
            continue
        left_issue_id, right_issue_id = [token.strip() for token in order.split("->", 1)]
        if left_issue_id not in adjacency or right_issue_id not in adjacency:
            continue
        if right_issue_id in adjacency[left_issue_id]:
            continue
        adjacency[left_issue_id].add(right_issue_id)
        indegree[right_issue_id] += 1

    ordered_issue_ids: list[str] = []
    queue = [issue_id for issue_id in active_issue_ids if indegree[issue_id] == 0]
    while queue:
        issue_id = queue.pop(0)
        ordered_issue_ids.append(issue_id)
        for dependent_issue_id in sorted(adjacency[issue_id], key=active_issue_ids.index):
            indegree[dependent_issue_id] -= 1
            if indegree[dependent_issue_id] == 0:
                queue.append(dependent_issue_id)
                queue.sort(key=active_issue_ids.index)

    if len(ordered_issue_ids) != len(active_issue_ids):
        raise WorkflowCommandError(
            "issue_execution_order cannot be derived because dependency overlaps contain a cycle.",
            exit_code=4,
        )
    return {"ordered_issue_ids": ordered_issue_ids}


def _collect_active_issue_ids_in_dev_map_order(dev_map: dict[str, Any]) -> list[str]:
    """Collect active issue IDs from DEV_MAP in canonical milestone/feature/issue order."""
    ordered_issue_ids: list[str] = []
    for milestone in dev_map.get("milestones", []):
        if not isinstance(milestone, dict):
            continue
        for feature in milestone.get("features", []):
            if not isinstance(feature, dict):
                continue
            for issue in feature.get("issues", []):
                if not isinstance(issue, dict):
                    continue
                issue_id = str(issue.get("id", "")).strip()
                if not issue_id:
                    continue
                if str(issue.get("status", "")).strip() in ISSUE_TERMINAL_STATUSES:
                    continue
                ordered_issue_ids.append(issue_id)
    return ordered_issue_ids


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


def _apply_issue_execution_order(
    tasks: list[dict[str, str]],
    ordered_issue_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Sort tasks by feature plan Issue Execution Order, then keep original task order inside each issue."""
    issue_order_index = {
        str(row.get("id", "")).strip(): index
        for index, row in enumerate(ordered_issue_rows)
        if str(row.get("id", "")).strip()
    }
    fallback_start = len(issue_order_index) + 1
    decorated: list[tuple[int, int, dict[str, str]]] = []
    for original_index, task in enumerate(tasks):
        issue_id = str(task.get("issue_id", "")).strip()
        decorated.append((issue_order_index.get(issue_id, fallback_start + original_index), original_index, task))
    decorated.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in decorated]
