"""Load and persist workflow tracker state from canonical JSON files."""

from __future__ import annotations

import json
import re
from typing import Any

from .context import WorkflowContext
from .errors import WorkflowCommandError
from .tracker_json_contracts import (
    build_issue_dependency_index_contract_payload,
    build_issue_overlaps_contract_payload,
    validate_issue_dependency_index_contract_payload,
    validate_issue_overlaps_contract_payload,
)


TASK_HEADING_PATTERN = re.compile(
    r"^###\s+(?P<task_id>[0-9]+[a-z]?)\)\s+(?:(?P<marker>\[[^\]]+\]\[[^\]]+\])\s+)?(?P<title>.+)$"
)
EXECUTION_LINE_PATTERN = re.compile(r"^\s*(?P<number>\d+)\.\s+(?P<body>.+)$")
BOLD_TOKEN_PATTERN = re.compile(r"\*\*([^*]+)\*\*")
BLOCK_TITLE_PATTERN = re.compile(r"^- \*\*(?P<title>.+)\*\*$")
OVERLAP_LINE_PATTERN = re.compile(
    r"^\s*-\s+\*\*(?P<left>[0-9]+[a-z]?)\s*<->\s*(?P<right>[0-9]+[a-z]?)\*\*:\s*(?P<description>.+)\s*$"
)
MARKDOWN_LINK_PATTERN = re.compile(r"\[(?P<label>[^\]]+)\]\([^)]+\)")
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[(?P<label>[^\]]*)\]\([^)]+\)")
MARKDOWN_EMPHASIS_PATTERN = re.compile(r"(?<!\w)(\*\*|__|\*|_)(?P<body>[^*_]+)\1(?!\w)")
MARKDOWN_HEADING_PREFIX_PATTERN = re.compile(r"^(?:>+\s*)?(?:#{1,6}\s+)?")


def load_task_list_payload(context: WorkflowContext) -> dict[str, Any]:
    """Load task-list payload from JSON file or fallback Markdown source."""
    if context.task_list_path.exists():
        payload = _load_json_file(context.task_list_path)
        if not isinstance(payload.get("tasks"), list):
            raise WorkflowCommandError("TASK_LIST.json must contain tasks list.", exit_code=4)
        return payload
    if context.legacy_task_list_path.exists():
        markdown_text = context.legacy_task_list_path.read_text(encoding="utf-8")
        return parse_task_list_markdown(markdown_text)
    return {"schema_version": "1.0", "tasks": []}


def write_task_list_payload(context: WorkflowContext, payload: dict[str, Any]) -> None:
    """Persist task-list payload to canonical JSON path."""
    _write_json_file(context.task_list_path, payload)

def load_issue_overlaps_payload(context: WorkflowContext) -> dict[str, Any]:
    """Load dedicated issue-overlaps payload or return an empty canonical structure."""
    if context.issue_overlaps_path.exists():
        payload = _load_json_file(context.issue_overlaps_path)
        validate_issue_overlaps_contract_payload(payload, str(context.issue_overlaps_path))
        return payload
    return build_issue_overlaps_contract_payload([])


def write_issue_overlaps_payload(context: WorkflowContext, payload: dict[str, Any]) -> None:
    """Persist validated issue-overlaps payload to canonical JSON path."""
    validate_issue_overlaps_contract_payload(payload, str(context.issue_overlaps_path))
    _write_json_file(context.issue_overlaps_path, payload)


def load_issue_dependency_index_payload(context: WorkflowContext) -> dict[str, Any]:
    """Load dependency-index payload or return an empty canonical structure."""
    if context.issue_dependency_index_path.exists():
        payload = _load_json_file(context.issue_dependency_index_path)
        validate_issue_dependency_index_contract_payload(payload, str(context.issue_dependency_index_path))
        return payload
    return build_issue_dependency_index_contract_payload(
        {
            "feature_scope": "all",
            "by_issue": {},
            "by_surface": {},
        }
    )


def write_issue_dependency_index_payload(context: WorkflowContext, payload: dict[str, Any]) -> None:
    """Persist validated dependency-index payload to canonical JSON path."""
    validate_issue_dependency_index_contract_payload(payload, str(context.issue_dependency_index_path))
    _write_json_file(context.issue_dependency_index_path, payload)


def parse_task_list_markdown(task_list_text: str) -> dict[str, Any]:
    """Parse legacy TASK_LIST markdown into canonical JSON payload shape."""
    lines = task_list_text.splitlines()
    headings: list[tuple[int, re.Match[str]]] = []
    for line_index, line in enumerate(lines):
        match = TASK_HEADING_PATTERN.match(line.strip())
        if match is not None:
            headings.append((line_index, match))

    tasks: list[dict[str, Any]] = []
    for heading_index, (start_line, match) in enumerate(headings):
        end_line = headings[heading_index + 1][0] if heading_index + 1 < len(headings) else len(lines)
        section_lines = lines[start_line:end_line]
        marker = str(match.group("marker") or "").strip() or "[M?][F?]"
        title = _strip_markdown_inline(str(match.group("title") or "").strip())
        problem = _extract_prefixed_line(section_lines, "**Problem:**")
        solution_option = _extract_prefixed_line(section_lines, "**Solution option:**")
        concrete_steps = _extract_numbered_steps(section_lines)
        if not concrete_steps:
            concrete_steps = _extract_solution_details_bullets(section_lines)
        concrete_steps = [step for step in (_strip_markdown_inline(item) for item in concrete_steps) if step]
        if not concrete_steps:
            concrete_steps = [_strip_markdown_inline("Review legacy TASK_LIST section details.")]
        tasks.append(
            {
                "id": str(match.group("task_id")),
                "marker": marker,
                "title": title or str(match.group("task_id")),
                "problem": _strip_markdown_inline(problem) or "Legacy TASK_LIST task entry.",
                "solution_option": _strip_markdown_inline(solution_option) or "Legacy TASK_LIST task entry.",
                "concrete_steps": concrete_steps,
            }
        )

    return {"schema_version": "1.0", "tasks": tasks}

def _extract_prefixed_line(lines: list[str], prefix: str) -> str:
    """Extract one line suffix by markdown prefix."""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.split(":", 1)[1].strip()
    return ""


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
    value = MARKDOWN_HEADING_PREFIX_PATTERN.sub("", value, count=1)
    return re.sub(r"\s+", " ", value).strip()


def _extract_numbered_steps(lines: list[str]) -> list[str]:
    """Extract numbered concrete steps from one markdown task section."""
    steps: list[str] = []
    in_steps = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#### **Concrete steps:**"):
            in_steps = True
            continue
        if not in_steps:
            continue
        match = re.match(r"^\d+\.\s+(?P<step>.+)$", stripped)
        if match is not None:
            steps.append(match.group("step").strip())
        elif stripped and not stripped.startswith("#"):
            break
    return steps


def _extract_solution_details_bullets(lines: list[str]) -> list[str]:
    """Extract bullet points from legacy Solution details sections."""
    bullets: list[str] = []
    in_details = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#### **Solution details:**"):
            in_details = True
            continue
        if not in_details:
            continue
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
        elif stripped and stripped.startswith("### "):
            break
    return bullets


def _extract_task_ids_from_text(text: str) -> list[str]:
    """Extract ordered task IDs from markdown execution line text."""
    ordered: list[str] = []
    seen: set[str] = set()
    for token in BOLD_TOKEN_PATTERN.findall(text):
        for part in token.split("/"):
            task_id = part.strip()
            if re.fullmatch(r"[0-9]+[a-z]?", task_id) is None:
                continue
            if task_id in seen:
                continue
            seen.add(task_id)
            ordered.append(task_id)
    return ordered


def _find_section_bounds(lines: list[str], heading_prefix: str) -> tuple[int, int] | None:
    """Find [start,end) bounds for one markdown section by heading prefix."""
    start_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip().startswith(heading_prefix):
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


def _load_json_file(path: Any) -> dict[str, Any]:
    """Read one JSON file into dict payload."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise WorkflowCommandError(f"Required file not found: {path}", exit_code=4) from error
    except json.JSONDecodeError as error:
        raise WorkflowCommandError(f"Invalid JSON in {path}: {error}", exit_code=4) from error
    if not isinstance(payload, dict):
        raise WorkflowCommandError(f"JSON root in {path} must be an object.", exit_code=4)
    return payload


def _write_json_file(path: Any, payload: dict[str, Any]) -> None:
    """Persist one JSON file with stable formatting."""
    path.write_text(f"{json.dumps(payload, indent=2, ensure_ascii=False)}\n", encoding="utf-8")
