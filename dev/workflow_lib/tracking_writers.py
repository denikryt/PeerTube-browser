"""Provide JSON tracker writer helpers for task list and execution pipeline."""

from __future__ import annotations

from typing import Any

from .errors import WorkflowCommandError


def apply_task_list_delta(
    task_list_payload: dict[str, Any],
    entries: list[dict[str, Any]],
    expected_marker: str,
) -> tuple[dict[str, Any], int]:
    """Append new task-list entries to JSON payload."""
    tasks = task_list_payload.setdefault("tasks", [])
    if not isinstance(tasks, list):
        raise WorkflowCommandError("TASK_LIST payload tasks must be a list.", exit_code=4)
    existing_ids = {str(task.get("id", "")).strip() for task in tasks if isinstance(task, dict)}

    appended_entries: list[dict[str, Any]] = []
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
        appended_entries.append(_normalize_task_list_entry(task_id=task_id, marker=marker, entry=entry, entry_index=entry_index))
        existing_ids.add(task_id)

    if appended_entries:
        tasks.extend(appended_entries)
    task_list_payload["schema_version"] = str(task_list_payload.get("schema_version", "")).strip() or "1.0"
    return task_list_payload, len(appended_entries)


def apply_pipeline_delta(
    pipeline_payload: dict[str, Any],
    delta_payload: dict[str, Any],
    update_pipeline: bool,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Append execution, block, and overlap records to pipeline JSON payload."""
    if not delta_payload:
        return pipeline_payload, {"blocks_added": 0, "overlaps_added": 0, "sequence_rows_added": 0}
    if not update_pipeline:
        raise WorkflowCommandError(
            "Delta contains pipeline payload but --update-pipeline was not provided.",
            exit_code=4,
        )

    execution_items = delta_payload.get("execution_sequence_append", [])
    block_items = delta_payload.get("functional_blocks_append", [])
    overlap_items = delta_payload.get("overlaps_append", [])
    if not isinstance(execution_items, list):
        raise WorkflowCommandError("pipeline.execution_sequence_append must be a list.", exit_code=4)
    if not isinstance(block_items, list):
        raise WorkflowCommandError("pipeline.functional_blocks_append must be a list.", exit_code=4)
    if not isinstance(overlap_items, list):
        raise WorkflowCommandError("pipeline.overlaps_append must be a list.", exit_code=4)

    execution_sequence = pipeline_payload.setdefault("execution_sequence", [])
    functional_blocks = pipeline_payload.setdefault("functional_blocks", [])
    overlaps = pipeline_payload.setdefault("overlaps", [])
    if not isinstance(execution_sequence, list):
        raise WorkflowCommandError("Pipeline payload execution_sequence must be a list.", exit_code=4)
    if not isinstance(functional_blocks, list):
        raise WorkflowCommandError("Pipeline payload functional_blocks must be a list.", exit_code=4)
    if not isinstance(overlaps, list):
        raise WorkflowCommandError("Pipeline payload overlaps must be a list.", exit_code=4)

    appended_execution: list[dict[str, Any]] = []
    for item_index, item in enumerate(execution_items):
        if not isinstance(item, dict):
            raise WorkflowCommandError(
                f"pipeline.execution_sequence_append[{item_index}] must be an object.",
                exit_code=4,
            )
        tasks = _required_list_field(item, "tasks", f"pipeline.execution_sequence_append[{item_index}]")
        description = str(item.get("description", "")).strip()
        normalized_item: dict[str, Any] = {"tasks": tasks}
        if description:
            normalized_item["description"] = description
        appended_execution.append(normalized_item)
    execution_sequence.extend(appended_execution)

    appended_blocks: list[dict[str, Any]] = []
    for block_index, block in enumerate(block_items):
        if not isinstance(block, dict):
            raise WorkflowCommandError(
                f"pipeline.functional_blocks_append[{block_index}] must be an object.",
                exit_code=4,
            )
        appended_blocks.append(
            {
                "title": _required_string_field(block, "title", f"pipeline.functional_blocks_append[{block_index}]"),
                "tasks": _required_list_field(block, "tasks", f"pipeline.functional_blocks_append[{block_index}]"),
                "scope": _required_string_field(block, "scope", f"pipeline.functional_blocks_append[{block_index}]"),
                "outcome": _required_string_field(
                    block,
                    "outcome",
                    f"pipeline.functional_blocks_append[{block_index}]",
                ),
            }
        )
    functional_blocks.extend(appended_blocks)

    appended_overlaps: list[dict[str, Any]] = []
    for overlap_index, overlap in enumerate(overlap_items):
        if not isinstance(overlap, dict):
            raise WorkflowCommandError(
                f"pipeline.overlaps_append[{overlap_index}] must be an object.",
                exit_code=4,
            )
        appended_overlaps.append(
            {
                "left": _required_string_field(overlap, "left", f"pipeline.overlaps_append[{overlap_index}]"),
                "right": _required_string_field(overlap, "right", f"pipeline.overlaps_append[{overlap_index}]"),
                "description": _required_string_field(
                    overlap,
                    "description",
                    f"pipeline.overlaps_append[{overlap_index}]",
                ),
            }
        )
    overlaps.extend(appended_overlaps)

    pipeline_payload["schema_version"] = str(pipeline_payload.get("schema_version", "")).strip() or "1.0"
    return (
        pipeline_payload,
        {
            "blocks_added": len(appended_blocks),
            "overlaps_added": len(appended_overlaps),
            "sequence_rows_added": len(appended_execution),
        },
    )


def _normalize_task_list_entry(task_id: str, marker: str, entry: dict[str, Any], entry_index: int) -> dict[str, Any]:
    """Normalize one task-list entry into canonical JSON structure."""
    return {
        "id": task_id,
        "marker": marker,
        "title": _required_string_field(entry, "title", f"task_list_entries[{entry_index}]"),
        "problem": _required_string_field(entry, "problem", f"task_list_entries[{entry_index}]"),
        "solution_option": _required_string_field(entry, "solution_option", f"task_list_entries[{entry_index}]"),
        "concrete_steps": _required_list_field(entry, "concrete_steps", f"task_list_entries[{entry_index}]"),
    }


def _required_string_field(payload: dict[str, Any], key: str, location: str) -> str:
    """Read and validate one required non-empty string field."""
    value = str(payload.get(key, "")).strip()
    if not value:
        raise WorkflowCommandError(f"Missing required field {location}.{key}.", exit_code=4)
    return value


def _required_list_field(payload: dict[str, Any], key: str, location: str) -> list[str]:
    """Read and validate one required non-empty list[str] field."""
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

