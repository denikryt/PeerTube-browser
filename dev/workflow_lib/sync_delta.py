"""Provide sync-delta parsing and task-id allocation helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import WorkflowCommandError


TASK_TOKEN_PATTERN = re.compile(r"^\$[A-Za-z][A-Za-z0-9_-]*$")
TASK_REFERENCE_PATTERN = re.compile(r"^(?:[0-9]+[a-z]?|\$[A-Za-z][A-Za-z0-9_-]*)$")


def load_sync_delta(delta_path: Path) -> dict[str, Any]:
    """Load and validate the top-level shape of a decomposition delta file."""
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


def resolve_sync_delta_references(
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
        normalized = normalize_task_reference(raw_value, location)
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
        tasks = overlap.get("tasks")
        if not isinstance(tasks, list) or len(tasks) != 2:
            raise WorkflowCommandError(
                f"pipeline.overlaps_append[{overlap_index}].tasks must be a list with exactly 2 task references.",
                exit_code=4,
            )
        overlap["tasks"] = [
            collect_reference(
                task_ref,
                f"pipeline.overlaps_append[{overlap_index}].tasks[{task_index}]",
            )
            for task_index, task_ref in enumerate(tasks)
        ]

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

    replace_task_reference_tokens(resolved, token_to_id)
    return (
        resolved,
        {
            "allocated_ids": token_to_id,
            "task_count_after": next_numeric_id,
            "task_count_before": task_count_before,
        },
    )


def normalize_task_reference(raw_value: Any, location: str) -> str:
    """Normalize one task reference and validate supported token/ID format."""
    value = str(raw_value or "").strip()
    if TASK_REFERENCE_PATTERN.fullmatch(value) is None:
        raise WorkflowCommandError(
            f"Invalid task reference at {location}: {raw_value!r}. Use task ID or $token.",
            exit_code=4,
        )
    return value


def replace_task_reference_tokens(payload: dict[str, Any], token_to_id: dict[str, str]) -> None:
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
        overlap["tasks"] = [token_to_id.get(task_id, task_id) for task_id in overlap.get("tasks", [])]
