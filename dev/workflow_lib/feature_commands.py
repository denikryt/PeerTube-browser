"""Register and execute feature workflow commands."""

from __future__ import annotations

import argparse
import json
import re
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from typing import Any

from .context import WorkflowContext
from .errors import WorkflowCommandError
from .output import emit_json


FEATURE_ID_PATTERN = re.compile(r"^F(?P<feature_num>\d+)-M(?P<milestone_num>\d+)$")
MILESTONE_ID_PATTERN = re.compile(r"^M(?P<milestone_num>\d+)$")
TASK_ID_PATTERN = re.compile(r"^[0-9]+[a-z]?$")
SECTION_H2_PATTERN = re.compile(r"^##\s+([^#].*?)\s*$")
SECTION_H3_PATTERN = re.compile(r"^###\s+([^#].*?)\s*$")
REQUIRED_PLAN_HEADINGS = (
    "Dependencies",
    "Decomposition",
    "Issue/Task Decomposition Assessment",
)


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

    approve_parser = feature_subparsers.add_parser(
        "approve",
        help="Approve feature plan and update feature status gate.",
    )
    approve_parser.add_argument("--id", required=True, help="Feature ID.")
    approve_parser.add_argument("--write", action="store_true", help="Write status update to tracker.")
    approve_parser.add_argument("--strict", action="store_true", help="Require strict plan lint pass.")
    approve_parser.set_defaults(handler=_handle_feature_approve)

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


def _handle_feature_create(args: Namespace, context: WorkflowContext) -> int:
    """Create or validate a feature node in DEV_MAP."""
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

    existing_feature = _find_feature(dev_map, feature_id)
    if existing_feature is not None:
        existing_milestone = existing_feature["milestone"]["id"]
        if existing_milestone != milestone_id:
            raise WorkflowCommandError(
                f"Feature {feature_id} already exists under {existing_milestone}, not {milestone_id}.",
                exit_code=4,
            )
        emit_json(
            {
                "action": "already-exists",
                "command": "feature.create",
                "feature_id": feature_id,
                "github_enabled": bool(args.github),
                "milestone_id": milestone_id,
                "write": bool(args.write),
            }
        )
        return 0

    new_feature = _build_feature_node(
        feature_id=feature_id,
        title=(args.title or f"Feature {feature_id}"),
        track=args.track,
    )
    if args.write:
        milestone_node.setdefault("features", []).append(new_feature)
        _touch_updated_at(dev_map)
        _write_json(context.dev_map_path, dev_map)
    emit_json(
        {
            "action": "created" if args.write else "would-create",
            "command": "feature.create",
            "feature_id": feature_id,
            "github_enabled": bool(args.github),
            "milestone_id": milestone_id,
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
    lint_result = _lint_plan_section(section_text, strict=bool(args.strict))
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


def _handle_feature_approve(args: Namespace, context: WorkflowContext) -> int:
    """Approve a feature plan after lint checks and update DEV_MAP status."""
    feature_id, _ = _parse_feature_id(args.id)
    section_text = _extract_feature_plan_section(context.feature_plans_path, feature_id)
    _lint_plan_section(section_text, strict=bool(args.strict))
    dev_map = _load_json(context.dev_map_path)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)

    feature_node = feature_ref["feature"]
    previous_status = str(feature_node.get("status", ""))
    if previous_status == "Done":
        raise WorkflowCommandError(f"Feature {feature_id} is already Done and cannot be re-approved.", exit_code=4)

    action = "already-approved"
    if previous_status != "Approved":
        action = "approved" if args.write else "would-approve"
        if args.write:
            feature_node["status"] = "Approved"
            _touch_updated_at(dev_map)
            _write_json(context.dev_map_path, dev_map)

    emit_json(
        {
            "action": action,
            "command": "feature.approve",
            "feature_id": feature_id,
            "strict": bool(args.strict),
            "status_after": "Approved" if action != "would-approve" else previous_status,
            "status_before": previous_status,
            "write": bool(args.write),
        }
    )
    return 0


def _handle_feature_execution_plan(args: Namespace, context: WorkflowContext) -> int:
    """Build ordered task execution plan for one feature subtree."""
    feature_id, _ = _parse_feature_id(args.id)
    dev_map = _load_json(context.dev_map_path)
    feature_ref = _find_feature(dev_map, feature_id)
    if feature_ref is None:
        raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)
    feature_node = feature_ref["feature"]
    feature_status = str(feature_node.get("status", ""))
    if feature_status not in {"Approved", "Done"}:
        raise WorkflowCommandError(
            f"Feature {feature_id} has status {feature_status}; expected Approved before execution-plan.",
            exit_code=4,
        )

    ordered_tasks = _collect_feature_tasks(feature_node, only_pending=bool(args.only_pending))
    if bool(args.from_pipeline):
        pipeline_order = _parse_pipeline_execution_order(context.pipeline_path)
        ordered_tasks = _apply_pipeline_order(ordered_tasks, pipeline_order)

    emit_json(
        {
            "command": "feature.execution-plan",
            "feature_id": feature_id,
            "feature_status": feature_status,
            "from_pipeline": bool(args.from_pipeline),
            "only_pending": bool(args.only_pending),
            "task_count": len(ordered_tasks),
            "tasks": ordered_tasks,
        }
    )
    return 0


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


def _find_feature(dev_map: dict[str, Any], feature_id: str) -> dict[str, Any] | None:
    """Find feature node and its parent milestone by feature ID."""
    milestones = dev_map.get("milestones", [])
    for milestone in milestones:
        for feature in milestone.get("features", []):
            if feature.get("id") == feature_id:
                return {"feature": feature, "milestone": milestone}
    return None


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


def _lint_plan_section(section_text: str, strict: bool) -> dict[str, list[str]]:
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

    return {"messages": messages}


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


def _parse_pipeline_execution_order(pipeline_path: Path) -> list[str]:
    """Parse task IDs from pipeline execution sequence section."""
    lines = pipeline_path.read_text(encoding="utf-8").splitlines()
    start_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip().startswith("### Execution sequence"):
            start_index = index
            break
    if start_index is None:
        return []

    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if lines[index].startswith("### "):
            end_index = index
            break

    ordered_ids: list[str] = []
    seen: set[str] = set()
    for line in lines[start_index:end_index]:
        for token in re.findall(r"\*\*([^*]+)\*\*", line):
            for part in token.split("/"):
                candidate = part.strip()
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
