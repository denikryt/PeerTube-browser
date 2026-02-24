"""Register and execute confirm command routing for workflow CLI."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from typing import Any

from .context import WorkflowContext
from .errors import WorkflowCommandError
from .output import emit_json


TASK_ID_PATTERN = re.compile(r"^[0-9]+[a-z]?$")
ISSUE_ID_PATTERN = re.compile(r"^I[0-9]+-F[0-9]+-M[0-9]+$")
FEATURE_ID_PATTERN = re.compile(r"^F[0-9]+-M[0-9]+$")
STANDALONE_ISSUE_ID_PATTERN = re.compile(r"^SI[0-9]+-M[0-9]+$")
TASK_LIST_HEADING_PATTERN = re.compile(r"^###\s+(?P<task_id>[0-9]+[a-z]?)\)\s+")
PIPELINE_TASK_BOLD_PATTERN = re.compile(r"\*\*(?P<task_id>[0-9]+[a-z]?)\*\*")
PIPELINE_BLOCK_TITLE_PATTERN = re.compile(r"^- \*\*.+\*\*$")
PIPELINE_BLOCK_TASKS_PATTERN = re.compile(r"^\s*-\s+Tasks:\s+\*\*(?P<chain>.+?)\*\*\s*$")


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
        help="Close mapped GitHub issue in the same run where applicable.",
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
    if args.confirm_target == "task":
        return _handle_confirm_task_done(args, context)
    if args.confirm_target == "issue":
        return _handle_confirm_issue_done(args, context)
    if args.confirm_target == "feature":
        return _handle_confirm_feature_done(args, context)
    if args.confirm_target == "standalone-issue":
        return _handle_confirm_standalone_issue_done(args, context)
    raise WorkflowCommandError(f"Unsupported confirm target: {args.confirm_target}", exit_code=4)


def _handle_confirm_task_done(args: Namespace, context: WorkflowContext) -> int:
    """Confirm one task completion and clean pending-only trackers."""
    task_id = _normalize_identifier(args.id)
    if TASK_ID_PATTERN.fullmatch(task_id) is None:
        raise WorkflowCommandError(
            f"Invalid task ID {args.id!r}; expected numeric task id format.",
            exit_code=4,
        )

    dev_map = _load_json(context.dev_map_path)
    task_ref = _find_task(dev_map, task_id)
    if task_ref is None:
        raise WorkflowCommandError(f"Task {task_id} not found in DEV_MAP.", exit_code=4)

    task_node = task_ref["task"]
    status_before = str(task_node.get("status", ""))
    if bool(args.write):
        task_node["status"] = "Done"

    cleanup_preview = _compute_tracker_cleanup_preview(context, {task_id})
    if bool(args.write):
        cleanup_result = _apply_tracker_cleanup(
            context=context,
            dev_map=dev_map,
            task_ids_to_remove={task_id},
        )
    else:
        cleanup_result = cleanup_preview

    emit_json(
        {
            "cleanup": cleanup_result,
            "close_github": bool(args.close_github),
            "command": "confirm.task",
            "github_closed": False,
            "parent_id": task_ref["parent_id"],
            "parent_type": task_ref["parent_type"],
            "status_after": "Done" if bool(args.write) else status_before,
            "status_before": status_before,
            "task_id": task_id,
            "write": bool(args.write),
        }
    )
    return 0


def _handle_confirm_issue_done(args: Namespace, context: WorkflowContext) -> int:
    """Confirm issue completion with optional child-task cascade."""
    issue_id = _normalize_identifier(args.id)
    if ISSUE_ID_PATTERN.fullmatch(issue_id) is None:
        raise WorkflowCommandError(
            f"Invalid issue ID {args.id!r}; expected I<local>-F<feature_local>-M<milestone>.",
            exit_code=4,
        )

    dev_map = _load_json(context.dev_map_path)
    issue_ref = _find_issue(dev_map, issue_id)
    if issue_ref is None:
        raise WorkflowCommandError(f"Issue {issue_id} not found in DEV_MAP.", exit_code=4)

    issue_node = issue_ref["issue"]
    child_tasks = issue_node.get("tasks", [])
    child_task_ids = [str(task.get("id", "")).strip() for task in child_tasks if str(task.get("id", "")).strip()]
    pending_child_ids = [
        str(task.get("id", "")).strip()
        for task in child_tasks
        if str(task.get("id", "")).strip() and str(task.get("status", "")) != "Done"
    ]
    needs_extra_confirmation = bool(pending_child_ids)
    if needs_extra_confirmation and not bool(args.force):
        if not _ask_pending_tasks_confirmation(issue_id, pending_child_ids):
            raise WorkflowCommandError(
                f"Confirmation cancelled for {issue_id}; pending child tasks were not accepted for cascade.",
                exit_code=4,
            )

    github_issue_number = issue_node.get("gh_issue_number")
    github_issue_url = str(issue_node.get("gh_issue_url", "")).strip()
    if bool(args.close_github) and (github_issue_number is None or not github_issue_url):
        raise WorkflowCommandError(
            f"Issue {issue_id} has no mapped GitHub issue metadata (gh_issue_number/gh_issue_url).",
            exit_code=4,
        )

    if bool(args.write):
        for task in child_tasks:
            task["status"] = "Done"
        issue_node["status"] = "Done"

    cleanup_preview = _compute_tracker_cleanup_preview(context, set(child_task_ids))
    if bool(args.write):
        cleanup_result = _apply_tracker_cleanup(
            context=context,
            dev_map=dev_map,
            task_ids_to_remove=set(child_task_ids),
        )
    else:
        cleanup_result = cleanup_preview

    github_closed = False
    if bool(args.write) and bool(args.close_github):
        _close_github_issue(int(github_issue_number))
        github_closed = True

    emit_json(
        {
            "child_tasks_marked_done": len(pending_child_ids) if bool(args.write) else 0,
            "cleanup": cleanup_result,
            "close_github": bool(args.close_github),
            "command": "confirm.issue",
            "extra_confirmation_required": needs_extra_confirmation,
            "feature_id": str(issue_ref["feature"].get("id", "")),
            "github_closed": github_closed,
            "issue_id": issue_id,
            "issue_status_after": "Done" if bool(args.write) else str(issue_node.get("status", "")),
            "pending_child_tasks": pending_child_ids,
            "write": bool(args.write),
        }
    )
    return 0


def _handle_confirm_feature_done(args: Namespace, context: WorkflowContext) -> int:
    """Confirm full feature subtree completion and close mapped GitHub issues."""
    feature_id = _normalize_identifier(args.id)
    if FEATURE_ID_PATTERN.fullmatch(feature_id) is None:
        raise WorkflowCommandError(
            f"Invalid feature ID {args.id!r}; expected F<local>-M<milestone>.",
            exit_code=4,
        )

    dev_map = _load_json(context.dev_map_path)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)

    feature_node = feature_ref["feature"]
    issue_nodes = feature_node.get("issues", [])
    all_task_ids: list[str] = []
    pending_task_ids: list[str] = []
    for issue_node in issue_nodes:
        for task in issue_node.get("tasks", []):
            task_id = str(task.get("id", "")).strip()
            if not task_id:
                continue
            all_task_ids.append(task_id)
            if str(task.get("status", "")) != "Done":
                pending_task_ids.append(task_id)

    if bool(args.close_github):
        _require_issue_github_mapping(
            issue_number=feature_node.get("gh_issue_number"),
            issue_url=feature_node.get("gh_issue_url"),
            label=f"Feature {feature_id}",
        )
        for issue_node in issue_nodes:
            issue_id = str(issue_node.get("id", "")).strip()
            _require_issue_github_mapping(
                issue_number=issue_node.get("gh_issue_number"),
                issue_url=issue_node.get("gh_issue_url"),
                label=f"Issue {issue_id}",
            )

    if bool(args.write):
        for issue_node in issue_nodes:
            issue_node["status"] = "Done"
            for task in issue_node.get("tasks", []):
                task["status"] = "Done"
        feature_node["status"] = "Done"

    cleanup_preview = _compute_tracker_cleanup_preview(context, set(all_task_ids))
    if bool(args.write):
        cleanup_result = _apply_tracker_cleanup(
            context=context,
            dev_map=dev_map,
            task_ids_to_remove=set(all_task_ids),
        )
    else:
        cleanup_result = cleanup_preview

    github_closed: list[int] = []
    if bool(args.write) and bool(args.close_github):
        for issue_node in issue_nodes:
            issue_number = int(issue_node.get("gh_issue_number"))
            _close_github_issue(issue_number)
            github_closed.append(issue_number)
        feature_issue_number = int(feature_node.get("gh_issue_number"))
        _close_github_issue(feature_issue_number)
        github_closed.append(feature_issue_number)

    emit_json(
        {
            "cleanup": cleanup_result,
            "close_github": bool(args.close_github),
            "command": "confirm.feature",
            "feature_id": feature_id,
            "feature_status_after": "Done" if bool(args.write) else str(feature_node.get("status", "")),
            "github_closed_issue_numbers": github_closed,
            "issue_count": len(issue_nodes),
            "pending_task_count": len(pending_task_ids),
            "task_count": len(all_task_ids),
            "write": bool(args.write),
        }
    )
    return 0


def _handle_confirm_standalone_issue_done(args: Namespace, context: WorkflowContext) -> int:
    """Confirm standalone issue completion after verifying all child tasks are already done."""
    standalone_issue_id = _normalize_identifier(args.id)
    if STANDALONE_ISSUE_ID_PATTERN.fullmatch(standalone_issue_id) is None:
        raise WorkflowCommandError(
            f"Invalid standalone issue ID {args.id!r}; expected SI<local>-M<milestone>.",
            exit_code=4,
        )

    dev_map = _load_json(context.dev_map_path)
    standalone_ref = _find_standalone_issue(dev_map, standalone_issue_id)
    if standalone_ref is None:
        raise WorkflowCommandError(f"Standalone issue {standalone_issue_id} not found in DEV_MAP.", exit_code=4)

    standalone_issue_node = standalone_ref["standalone_issue"]
    child_task_ids: list[str] = []
    pending_task_ids: list[str] = []
    for task in standalone_issue_node.get("tasks", []):
        task_id = str(task.get("id", "")).strip()
        if not task_id:
            continue
        child_task_ids.append(task_id)
        if str(task.get("status", "")) != "Done":
            pending_task_ids.append(task_id)
    if pending_task_ids:
        pending_csv = ", ".join(pending_task_ids)
        raise WorkflowCommandError(
            f"Standalone issue {standalone_issue_id} has pending child tasks ({pending_csv}); "
            "confirm tasks first before standalone-issue confirmation.",
            exit_code=4,
        )

    if bool(args.close_github):
        _require_issue_github_mapping(
            issue_number=standalone_issue_node.get("gh_issue_number"),
            issue_url=standalone_issue_node.get("gh_issue_url"),
            label=f"Standalone issue {standalone_issue_id}",
        )

    if bool(args.write):
        standalone_issue_node["status"] = "Done"

    cleanup_preview = _compute_tracker_cleanup_preview(context, set(child_task_ids))
    if bool(args.write):
        cleanup_result = _apply_tracker_cleanup(
            context=context,
            dev_map=dev_map,
            task_ids_to_remove=set(child_task_ids),
        )
    else:
        cleanup_result = cleanup_preview

    github_closed = False
    if bool(args.write) and bool(args.close_github):
        _close_github_issue(int(standalone_issue_node.get("gh_issue_number")))
        github_closed = True

    emit_json(
        {
            "cleanup": cleanup_result,
            "close_github": bool(args.close_github),
            "command": "confirm.standalone-issue",
            "github_closed": github_closed,
            "standalone_issue_id": standalone_issue_id,
            "status_after": "Done" if bool(args.write) else str(standalone_issue_node.get("status", "")),
            "task_count": len(child_task_ids),
            "write": bool(args.write),
        }
    )
    return 0


def _compute_tracker_cleanup_preview(context: WorkflowContext, task_ids_to_remove: set[str]) -> dict[str, Any]:
    """Compute cleanup counts for TASK_LIST and PIPELINE without writing changes."""
    task_list_text = context.task_list_path.read_text(encoding="utf-8")
    _, removed_task_entries = _remove_task_entries_from_task_list(task_list_text, task_ids_to_remove)
    pipeline_text = context.pipeline_path.read_text(encoding="utf-8")
    _, pipeline_cleanup = _cleanup_pipeline_for_completed_tasks(pipeline_text, task_ids_to_remove)
    return {
        "pipeline": pipeline_cleanup,
        "task_list_entries_removed": len(removed_task_entries),
    }


def _apply_tracker_cleanup(
    context: WorkflowContext,
    dev_map: dict[str, Any],
    task_ids_to_remove: set[str],
) -> dict[str, Any]:
    """Apply DEV_MAP/TASK_LIST/PIPELINE completion cleanup in one write run."""
    task_list_text = context.task_list_path.read_text(encoding="utf-8")
    updated_task_list, removed_task_entries = _remove_task_entries_from_task_list(task_list_text, task_ids_to_remove)
    pipeline_text = context.pipeline_path.read_text(encoding="utf-8")
    updated_pipeline, pipeline_cleanup = _cleanup_pipeline_for_completed_tasks(pipeline_text, task_ids_to_remove)
    _touch_updated_at(dev_map)
    _write_json(context.dev_map_path, dev_map)
    context.task_list_path.write_text(updated_task_list, encoding="utf-8")
    context.pipeline_path.write_text(updated_pipeline, encoding="utf-8")
    return {
        "pipeline": pipeline_cleanup,
        "task_list_entries_removed": len(removed_task_entries),
    }


def _remove_task_entries_from_task_list(task_list_text: str, task_ids_to_remove: set[str]) -> tuple[str, list[str]]:
    """Remove completed task sections from TASK_LIST by heading task IDs."""
    if not task_ids_to_remove:
        return task_list_text, []
    lines = task_list_text.splitlines()
    headings: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = TASK_LIST_HEADING_PATTERN.match(line)
        if match is not None:
            headings.append((index, match.group("task_id")))
    if not headings:
        return task_list_text, []

    removed_ids: list[str] = []
    kept_lines: list[str] = lines[: headings[0][0]]
    for heading_index, (start_line, task_id) in enumerate(headings):
        end_line = headings[heading_index + 1][0] if heading_index + 1 < len(headings) else len(lines)
        section_lines = lines[start_line:end_line]
        if task_id in task_ids_to_remove:
            removed_ids.append(task_id)
            continue
        kept_lines.extend(section_lines)

    updated = "\n".join(kept_lines)
    if task_list_text.endswith("\n"):
        updated = f"{updated}\n"
    return updated, removed_ids


def _cleanup_pipeline_for_completed_tasks(
    pipeline_text: str,
    task_ids_to_remove: set[str],
) -> tuple[str, dict[str, int]]:
    """Remove completed task references from pipeline sequence, blocks, and overlaps."""
    if not task_ids_to_remove:
        return (
            pipeline_text,
            {
                "blocks_removed": 0,
                "execution_rows_removed": 0,
                "overlap_rows_removed": 0,
            },
        )

    lines = pipeline_text.splitlines()
    sequence_bounds = _find_section_bounds(lines, "### Execution sequence")
    blocks_bounds = _find_section_bounds(lines, "### Functional blocks")
    overlaps_bounds = _find_section_bounds(lines, "### Cross-task overlaps and dependencies")
    if sequence_bounds is None or blocks_bounds is None or overlaps_bounds is None:
        raise WorkflowCommandError("Pipeline file is missing required sections for completion cleanup.", exit_code=4)

    sequence_start, sequence_end = sequence_bounds
    blocks_start, blocks_end = blocks_bounds
    overlaps_start, overlaps_end = overlaps_bounds
    sequence_section = lines[sequence_start + 1 : sequence_end]
    blocks_section = lines[blocks_start + 1 : blocks_end]
    overlaps_section = lines[overlaps_start + 1 : overlaps_end]

    cleaned_sequence, execution_rows_removed = _cleanup_sequence_section(sequence_section, task_ids_to_remove)
    cleaned_blocks, blocks_removed = _cleanup_functional_blocks_section(blocks_section, task_ids_to_remove)
    cleaned_overlaps, overlap_rows_removed = _cleanup_overlaps_section(overlaps_section, task_ids_to_remove)

    rebuilt_lines: list[str] = []
    rebuilt_lines.extend(lines[: sequence_start + 1])
    rebuilt_lines.extend(cleaned_sequence)
    rebuilt_lines.append(lines[blocks_start])
    rebuilt_lines.extend(cleaned_blocks)
    rebuilt_lines.append(lines[overlaps_start])
    rebuilt_lines.extend(cleaned_overlaps)
    rebuilt_lines.extend(lines[overlaps_end:])

    updated = "\n".join(rebuilt_lines)
    if pipeline_text.endswith("\n"):
        updated = f"{updated}\n"
    return (
        updated,
        {
            "blocks_removed": blocks_removed,
            "execution_rows_removed": execution_rows_removed,
            "overlap_rows_removed": overlap_rows_removed,
        },
    )


def _cleanup_sequence_section(lines: list[str], task_ids_to_remove: set[str]) -> tuple[list[str], int]:
    """Remove completed task IDs from execution-sequence lines and renumber remaining rows."""
    cleaned: list[str] = []
    removed_rows = 0
    next_number = 1
    for line in lines:
        numbered_match = re.match(r"^\s*(?P<number>\d+)\.\s+(?P<body>.+)$", line)
        if numbered_match is None:
            cleaned.append(line)
            continue
        body = numbered_match.group("body")
        task_ids = PIPELINE_TASK_BOLD_PATTERN.findall(body)
        if not task_ids:
            cleaned.append(line)
            continue
        remaining_task_ids = [task_id for task_id in task_ids if task_id not in task_ids_to_remove]
        if not remaining_task_ids:
            removed_rows += 1
            continue
        suffix = ""
        for match in PIPELINE_TASK_BOLD_PATTERN.finditer(body):
            suffix = body[match.end() :]
        rebuilt = f"{next_number}. " + " then ".join(f"**{task_id}**" for task_id in remaining_task_ids)
        suffix = suffix.rstrip()
        if suffix:
            rebuilt = f"{rebuilt} {suffix}"
        cleaned.append(rebuilt)
        next_number += 1
    return cleaned, removed_rows


def _cleanup_functional_blocks_section(lines: list[str], task_ids_to_remove: set[str]) -> tuple[list[str], int]:
    """Remove completed task IDs from functional blocks and drop empty blocks."""
    cleaned: list[str] = []
    removed_blocks = 0
    index = 0
    while index < len(lines):
        if not PIPELINE_BLOCK_TITLE_PATTERN.match(lines[index]):
            cleaned.append(lines[index])
            index += 1
            continue
        next_index = index + 1
        while next_index < len(lines) and not PIPELINE_BLOCK_TITLE_PATTERN.match(lines[next_index]):
            next_index += 1
        block_lines = list(lines[index:next_index])
        tasks_line_index = _find_block_tasks_line_index(block_lines)
        if tasks_line_index is not None:
            task_chain_match = PIPELINE_BLOCK_TASKS_PATTERN.match(block_lines[tasks_line_index])
            if task_chain_match is not None:
                task_tokens = [
                    token.strip()
                    for token in task_chain_match.group("chain").split("->")
                    if token.strip()
                ]
                filtered_tokens = [
                    token
                    for token in task_tokens
                    if TASK_ID_PATTERN.fullmatch(token) is not None and token not in task_ids_to_remove
                ]
                if task_tokens and not filtered_tokens:
                    removed_blocks += 1
                    index = next_index
                    continue
                if filtered_tokens and len(filtered_tokens) != len(task_tokens):
                    block_lines[tasks_line_index] = f"  - Tasks: **{' -> '.join(filtered_tokens)}**"
        cleaned.extend(block_lines)
        index = next_index
    return cleaned, removed_blocks


def _cleanup_overlaps_section(lines: list[str], task_ids_to_remove: set[str]) -> tuple[list[str], int]:
    """Remove overlap rows that reference completed task IDs."""
    cleaned: list[str] = []
    removed_rows = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- **"):
            line_task_ids = {
                token
                for token in re.findall(r"\b[0-9]+[a-z]?\b", stripped)
                if TASK_ID_PATTERN.fullmatch(token) is not None
            }
            if line_task_ids.intersection(task_ids_to_remove):
                removed_rows += 1
                continue
        cleaned.append(line)
    return cleaned, removed_rows


def _find_block_tasks_line_index(block_lines: list[str]) -> int | None:
    """Return index of the tasks line inside one functional block, if present."""
    for index, line in enumerate(block_lines):
        if PIPELINE_BLOCK_TASKS_PATTERN.match(line) is not None:
            return index
    return None


def _find_section_bounds(lines: list[str], heading_prefix: str) -> tuple[int, int] | None:
    """Locate one markdown level-3 section as [start, end) line bounds."""
    start_index: int | None = None
    for index, line in enumerate(lines):
        if line.startswith(heading_prefix):
            start_index = index
            break
    if start_index is None:
        return None
    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if lines[index].startswith("### "):
            end_index = index
            break
    return start_index, end_index


def _require_issue_github_mapping(issue_number: Any, issue_url: Any, label: str) -> None:
    """Validate presence of GitHub issue metadata required for close operation."""
    issue_url_text = str(issue_url or "").strip()
    if issue_number is None or not issue_url_text:
        raise WorkflowCommandError(
            f"{label} has no mapped GitHub issue metadata (gh_issue_number/gh_issue_url).",
            exit_code=4,
        )


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


def _normalize_identifier(raw_identifier: str) -> str:
    """Normalize identifier text to canonical uppercase representation."""
    return str(raw_identifier).strip().upper()


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


def _find_task(dev_map: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    """Find task node and parent metadata for both feature and standalone chains."""
    for milestone in dev_map.get("milestones", []):
        for feature in milestone.get("features", []):
            for issue in feature.get("issues", []):
                for task in issue.get("tasks", []):
                    if str(task.get("id", "")).strip().upper() == task_id:
                        return {
                            "feature": feature,
                            "issue": issue,
                            "milestone": milestone,
                            "parent_id": str(issue.get("id", "")),
                            "parent_type": "issue",
                            "task": task,
                        }
        for standalone_issue in milestone.get("standalone_issues", []):
            for task in standalone_issue.get("tasks", []):
                if str(task.get("id", "")).strip().upper() == task_id:
                    return {
                        "milestone": milestone,
                        "parent_id": str(standalone_issue.get("id", "")),
                        "parent_type": "standalone-issue",
                        "standalone_issue": standalone_issue,
                        "task": task,
                    }
    return None


def _find_issue(dev_map: dict[str, Any], issue_id: str) -> dict[str, Any] | None:
    """Find issue node and parent metadata by issue ID."""
    for milestone in dev_map.get("milestones", []):
        for feature in milestone.get("features", []):
            for issue in feature.get("issues", []):
                if str(issue.get("id", "")).strip().upper() == issue_id:
                    return {
                        "feature": feature,
                        "issue": issue,
                        "milestone": milestone,
                    }
    return None


def _find_feature(dev_map: dict[str, Any], feature_id: str) -> dict[str, Any] | None:
    """Find feature node and parent milestone by feature ID."""
    for milestone in dev_map.get("milestones", []):
        for feature in milestone.get("features", []):
            if str(feature.get("id", "")).strip().upper() == feature_id:
                return {
                    "feature": feature,
                    "milestone": milestone,
                }
    return None


def _find_standalone_issue(dev_map: dict[str, Any], standalone_issue_id: str) -> dict[str, Any] | None:
    """Find standalone issue node and parent milestone by standalone issue ID."""
    for milestone in dev_map.get("milestones", []):
        for standalone_issue in milestone.get("standalone_issues", []):
            if str(standalone_issue.get("id", "")).strip().upper() == standalone_issue_id:
                return {
                    "milestone": milestone,
                    "standalone_issue": standalone_issue,
                }
    return None
