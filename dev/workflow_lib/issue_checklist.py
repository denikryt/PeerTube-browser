"""Helper utilities for feature-issue checklist body synchronization."""

from __future__ import annotations

import re
from typing import Any, Iterable


PLANNED_WORK_SECTION_HEADING = "## Planned work/issues"
CHECKLIST_LINE_PATTERN = re.compile(r"^(?P<prefix>\s*-\s*\[)(?P<state>[ xX])(?P<suffix>\]\s*)(?P<label>.*)$")
ISSUE_ID_LABEL_PATTERN = re.compile(r"^(?P<issue_id>I[0-9]+-F[0-9]+-M[0-9]+)\b")
H2_HEADING_PATTERN = re.compile(r"^##\s+")


def append_missing_issue_checklist_rows(
    feature_issue_body: str,
    issue_nodes: Iterable[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Append missing child-issue checklist rows and return updated body plus appended issue IDs."""
    existing_ids = _collect_existing_issue_ids(feature_issue_body)
    rows_to_append: list[str] = []
    appended_issue_ids: list[str] = []
    for issue_node in issue_nodes:
        issue_id = str(issue_node.get("id", "")).strip().upper()
        if not issue_id or issue_id in existing_ids:
            continue
        issue_title = str(issue_node.get("title", "")).strip()
        issue_status = str(issue_node.get("status", "")).strip()
        rows_to_append.append(build_issue_checklist_row(issue_id, issue_title, issue_status == "Done"))
        appended_issue_ids.append(issue_id)
        existing_ids.add(issue_id)

    if not rows_to_append:
        return feature_issue_body, []

    lines = feature_issue_body.splitlines()
    section_start = _find_planned_work_section_start(lines)
    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(PLANNED_WORK_SECTION_HEADING)
        insert_index = len(lines)
    else:
        section_end = _find_section_end(lines, section_start)
        last_checklist_index = _find_last_checklist_line_index(lines, section_start, section_end)
        insert_index = section_end if last_checklist_index is None else last_checklist_index + 1

    lines[insert_index:insert_index] = rows_to_append
    return _render_issue_body(lines), appended_issue_ids


def mark_issue_checklist_row_done(
    feature_issue_body: str,
    issue_id: str,
) -> tuple[str, bool, bool]:
    """Mark one feature-issue checklist row as checked by issue ID."""
    target_issue_id = str(issue_id).strip().upper()
    lines = feature_issue_body.splitlines()
    row_found = False
    row_updated = False

    for index, line in enumerate(lines):
        checklist_match = CHECKLIST_LINE_PATTERN.match(line)
        if checklist_match is None:
            continue
        line_issue_id = _extract_issue_id_from_label(checklist_match.group("label"))
        if line_issue_id != target_issue_id:
            continue
        row_found = True
        if checklist_match.group("state").lower() == "x":
            break
        lines[index] = (
            f"{checklist_match.group('prefix')}x{checklist_match.group('suffix')}{checklist_match.group('label')}"
        )
        row_updated = True
        break

    if not row_updated:
        return feature_issue_body, row_found, False
    return _render_issue_body(lines), row_found, True


def build_issue_checklist_row(issue_id: str, issue_title: str, checked: bool) -> str:
    """Build one markdown checkbox row for a feature child issue."""
    checkbox = "x" if checked else " "
    suffix = f": {issue_title}" if issue_title else ""
    return f"- [{checkbox}] {issue_id}{suffix}"


def _collect_existing_issue_ids(feature_issue_body: str) -> set[str]:
    """Collect issue IDs already referenced in checklist rows."""
    existing_ids: set[str] = set()
    for line in feature_issue_body.splitlines():
        checklist_match = CHECKLIST_LINE_PATTERN.match(line)
        if checklist_match is None:
            continue
        issue_id = _extract_issue_id_from_label(checklist_match.group("label"))
        if issue_id:
            existing_ids.add(issue_id)
    return existing_ids


def _extract_issue_id_from_label(label: str) -> str | None:
    """Extract canonical issue ID from checklist label text."""
    match = ISSUE_ID_LABEL_PATTERN.match(str(label).strip())
    if match is None:
        return None
    return match.group("issue_id").upper()


def _find_planned_work_section_start(lines: list[str]) -> int | None:
    """Locate the planned-work section heading line index."""
    target = PLANNED_WORK_SECTION_HEADING.lower()
    for index, line in enumerate(lines):
        if line.strip().lower() == target:
            return index
    return None


def _find_section_end(lines: list[str], section_start: int) -> int:
    """Find section end index using next H2 heading or body end."""
    for index in range(section_start + 1, len(lines)):
        if H2_HEADING_PATTERN.match(lines[index].strip()):
            return index
    return len(lines)


def _find_last_checklist_line_index(lines: list[str], section_start: int, section_end: int) -> int | None:
    """Return last checklist line index inside one body section."""
    for index in range(section_end - 1, section_start, -1):
        if CHECKLIST_LINE_PATTERN.match(lines[index]) is not None:
            return index
    return None


def _render_issue_body(lines: list[str]) -> str:
    """Render markdown body with normalized trailing newline."""
    rendered = "\n".join(lines).rstrip()
    return f"{rendered}\n" if rendered else ""

