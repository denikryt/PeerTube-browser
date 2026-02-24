"""Define and validate canonical JSON contracts for workflow tracker payloads."""

from __future__ import annotations

from typing import Any

from .errors import WorkflowCommandError


TASK_LIST_CONTRACT_VERSION = "1.0"
PIPELINE_CONTRACT_VERSION = "1.0"


def build_task_list_contract_payload(entries: list[dict[str, Any]], expected_marker: str) -> dict[str, Any]:
    """Build canonical task-list JSON payload from sync entries."""
    normalized_tasks: list[dict[str, Any]] = []
    for entry in entries:
        task = dict(entry)
        marker = str(task.get("marker", "")).strip()
        if not marker:
            task["marker"] = expected_marker
        normalized_tasks.append(task)
    return {
        "schema_version": TASK_LIST_CONTRACT_VERSION,
        "tasks": normalized_tasks,
    }


def build_pipeline_contract_payload(pipeline_payload: dict[str, Any]) -> dict[str, Any]:
    """Build canonical pipeline JSON payload from sync pipeline section."""
    return {
        "schema_version": PIPELINE_CONTRACT_VERSION,
        "execution_sequence": pipeline_payload.get("execution_sequence_append", []),
        "functional_blocks": pipeline_payload.get("functional_blocks_append", []),
        "overlaps": pipeline_payload.get("overlaps_append", []),
    }


def validate_task_list_contract_payload(payload: dict[str, Any], location: str) -> None:
    """Validate task-list JSON payload shape and required fields."""
    schema_version = str(payload.get("schema_version", "")).strip()
    if schema_version != TASK_LIST_CONTRACT_VERSION:
        raise WorkflowCommandError(
            f"{location}: unsupported task-list schema_version {schema_version!r}; "
            f"expected {TASK_LIST_CONTRACT_VERSION}.",
            exit_code=4,
        )

    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise WorkflowCommandError(f"{location}: task-list tasks must be a list.", exit_code=4)

    for task_index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise WorkflowCommandError(f"{location}: tasks[{task_index}] must be an object.", exit_code=4)
        _require_non_empty_string(task, "id", f"{location}.tasks[{task_index}]")
        _require_non_empty_string(task, "marker", f"{location}.tasks[{task_index}]")
        _require_non_empty_string(task, "title", f"{location}.tasks[{task_index}]")
        _require_non_empty_string(task, "problem", f"{location}.tasks[{task_index}]")
        _require_non_empty_string(task, "solution_option", f"{location}.tasks[{task_index}]")
        _require_non_empty_string_list(task, "concrete_steps", f"{location}.tasks[{task_index}]")


def validate_pipeline_contract_payload(payload: dict[str, Any], location: str) -> None:
    """Validate pipeline JSON payload shape and required fields."""
    schema_version = str(payload.get("schema_version", "")).strip()
    if schema_version != PIPELINE_CONTRACT_VERSION:
        raise WorkflowCommandError(
            f"{location}: unsupported pipeline schema_version {schema_version!r}; "
            f"expected {PIPELINE_CONTRACT_VERSION}.",
            exit_code=4,
        )

    execution_sequence = payload.get("execution_sequence")
    if not isinstance(execution_sequence, list):
        raise WorkflowCommandError(f"{location}: execution_sequence must be a list.", exit_code=4)
    for item_index, item in enumerate(execution_sequence):
        if not isinstance(item, dict):
            raise WorkflowCommandError(
                f"{location}: execution_sequence[{item_index}] must be an object.",
                exit_code=4,
            )
        _require_non_empty_string_list(item, "tasks", f"{location}.execution_sequence[{item_index}]")
        description = item.get("description")
        if description is not None and not isinstance(description, str):
            raise WorkflowCommandError(
                f"{location}: execution_sequence[{item_index}].description must be a string when provided.",
                exit_code=4,
            )

    functional_blocks = payload.get("functional_blocks")
    if not isinstance(functional_blocks, list):
        raise WorkflowCommandError(f"{location}: functional_blocks must be a list.", exit_code=4)
    for block_index, block in enumerate(functional_blocks):
        if not isinstance(block, dict):
            raise WorkflowCommandError(
                f"{location}: functional_blocks[{block_index}] must be an object.",
                exit_code=4,
            )
        _require_non_empty_string(block, "title", f"{location}.functional_blocks[{block_index}]")
        _require_non_empty_string_list(block, "tasks", f"{location}.functional_blocks[{block_index}]")
        _require_non_empty_string(block, "scope", f"{location}.functional_blocks[{block_index}]")
        _require_non_empty_string(block, "outcome", f"{location}.functional_blocks[{block_index}]")

    overlaps = payload.get("overlaps")
    if not isinstance(overlaps, list):
        raise WorkflowCommandError(f"{location}: overlaps must be a list.", exit_code=4)
    for overlap_index, overlap in enumerate(overlaps):
        if not isinstance(overlap, dict):
            raise WorkflowCommandError(f"{location}: overlaps[{overlap_index}] must be an object.", exit_code=4)
        tasks = _require_non_empty_string_list(overlap, "tasks", f"{location}.overlaps[{overlap_index}]")
        if len(tasks) != 2:
            raise WorkflowCommandError(
                f"{location}: overlaps[{overlap_index}].tasks must contain exactly 2 task IDs.",
                exit_code=4,
            )
        _require_non_empty_string(overlap, "description", f"{location}.overlaps[{overlap_index}]")


def _require_non_empty_string(payload: dict[str, Any], key: str, location: str) -> str:
    """Read one required non-empty string value."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WorkflowCommandError(f"{location}.{key} must be a non-empty string.", exit_code=4)
    return value


def _require_non_empty_string_list(payload: dict[str, Any], key: str, location: str) -> list[str]:
    """Read one required non-empty list[str] value."""
    raw_value = payload.get(key)
    if not isinstance(raw_value, list) or not raw_value:
        raise WorkflowCommandError(f"{location}.{key} must be a non-empty list.", exit_code=4)
    normalized: list[str] = []
    for index, item in enumerate(raw_value):
        if not isinstance(item, str) or not item.strip():
            raise WorkflowCommandError(f"{location}.{key}[{index}] must be a non-empty string.", exit_code=4)
        normalized.append(item)
    return normalized
