"""Provide tracker writer helpers for TASK_LIST and TASK_EXECUTION_PIPELINE."""

from __future__ import annotations

import re
from typing import Any

from .errors import WorkflowCommandError


TASK_LIST_HEADING_PATTERN = re.compile(r"^###\s+(?P<task_id>[0-9]+[a-z]?)\)\s+")


def apply_task_list_delta(task_list_text: str, entries: list[dict[str, Any]], expected_marker: str) -> tuple[str, int]:
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


def apply_pipeline_delta(
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


def _find_section_bounds(lines: list[str], section_heading_prefix: str) -> tuple[int, int] | None:
    """Return [start,end) line bounds for one markdown section."""
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
