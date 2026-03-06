"""Provide JSON tracker writer helpers for task list payloads."""

from __future__ import annotations

import re
from typing import Any

from .errors import WorkflowCommandError

MARKDOWN_LINK_PATTERN = re.compile(r"\[(?P<label>[^\]]+)\]\([^)]+\)")
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[(?P<label>[^\]]*)\]\([^)]+\)")
MARKDOWN_EMPHASIS_PATTERN = re.compile(r"(?<!\w)(\*\*|__|\*|_)(?P<body>[^*_]+)\1(?!\w)")


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

def _normalize_task_list_entry(task_id: str, marker: str, entry: dict[str, Any], entry_index: int) -> dict[str, Any]:
    """Normalize one task-list entry into canonical JSON structure."""
    normalized_steps = [
        _strip_markdown_inline(step)
        for step in _required_list_field(entry, "concrete_steps", f"task_list_entries[{entry_index}]")
    ]
    normalized_steps = [step for step in normalized_steps if step]
    if not normalized_steps:
        raise WorkflowCommandError(
            f"task_list_entries[{entry_index}].concrete_steps must contain at least one non-empty step.",
            exit_code=4,
        )
    return {
        "id": task_id,
        "marker": marker,
        "title": _strip_markdown_inline(_required_string_field(entry, "title", f"task_list_entries[{entry_index}]")),
        "problem": _strip_markdown_inline(_required_string_field(entry, "problem", f"task_list_entries[{entry_index}]")),
        "solution_option": _strip_markdown_inline(
            _required_string_field(entry, "solution_option", f"task_list_entries[{entry_index}]")
        ),
        "concrete_steps": normalized_steps,
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


def _strip_markdown_inline(text: str) -> str:
    """Normalize simple markdown inline markup to plain text."""
    value = str(text).strip()
    if not value:
        return ""
    value = MARKDOWN_IMAGE_PATTERN.sub(lambda match: match.group("label"), value)
    value = MARKDOWN_LINK_PATTERN.sub(lambda match: match.group("label"), value)
    value = value.replace("`", "")
    while True:
        next_value = MARKDOWN_EMPHASIS_PATTERN.sub(lambda match: match.group("body"), value)
        if next_value == value:
            break
        value = next_value
    value = value.replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", value).strip()
