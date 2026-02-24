#!/usr/bin/env python3
"""Convert legacy markdown trackers to canonical JSON tracker files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEV_DIR = Path(__file__).resolve().parent
if str(DEV_DIR) not in sys.path:
    sys.path.insert(0, str(DEV_DIR))

from workflow_lib.context import build_default_context
from workflow_lib.tracker_json_contracts import (  # noqa: E402
    PIPELINE_CONTRACT_VERSION,
    TASK_LIST_CONTRACT_VERSION,
    validate_pipeline_contract_payload,
    validate_task_list_contract_payload,
)
from workflow_lib.tracker_store import (  # noqa: E402
    parse_pipeline_markdown,
    parse_task_list_markdown,
    write_pipeline_payload,
    write_task_list_payload,
)


TASK_ID_PATTERN = re.compile(r"^[0-9]+[a-z]?$")
MARKER_PATTERN = re.compile(r"^\[(?P<milestone>M\d+)\]\[(?P<owner>F\d+|SI\d+)\]$")
FEATURE_PATTERN = re.compile(r"^F(?P<feature_num>\d+)-M\d+$")
STANDALONE_PATTERN = re.compile(r"^SI(?P<si_num>\d+)-M\d+$")


@dataclass(frozen=True)
class DevMapOwnership:
    """Represent task ownership extracted from DEV_MAP."""

    milestone_id: str
    owner_marker: str
    owner_path: str
    task_id: str


def parse_args() -> argparse.Namespace:
    """Parse migration command arguments."""
    parser = argparse.ArgumentParser(
        prog="migrate_trackers_to_json",
        description="Convert TASK_LIST.md and TASK_EXECUTION_PIPELINE.md to canonical JSON tracker files.",
    )
    parser.add_argument("--write", action="store_true", help="Write converted JSON files.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when warnings are produced during DEV_MAP link validation.",
    )
    return parser.parse_args()


def main() -> int:
    """Run markdown-to-JSON conversion with schema/link validation."""
    args = parse_args()
    context = build_default_context()

    task_list_markdown = context.legacy_task_list_path.read_text(encoding="utf-8")
    pipeline_markdown = context.legacy_pipeline_path.read_text(encoding="utf-8")
    task_list_payload = parse_task_list_markdown(task_list_markdown)
    pipeline_payload = parse_pipeline_markdown(pipeline_markdown)

    validate_task_list_contract_payload(task_list_payload, "migration.task_list")
    validate_pipeline_contract_payload(pipeline_payload, "migration.pipeline")
    _validate_schema_metadata(context.root_dir / "dev" / "map" / "TASK_LIST_JSON_SCHEMA.json", TASK_LIST_CONTRACT_VERSION)
    _validate_schema_metadata(
        context.root_dir / "dev" / "map" / "TASK_EXECUTION_PIPELINE_JSON_SCHEMA.json",
        PIPELINE_CONTRACT_VERSION,
    )

    dev_map = json.loads(context.dev_map_path.read_text(encoding="utf-8"))
    ownership_map = _collect_dev_map_ownership(dev_map)
    task_list_link_errors, task_list_link_warnings = _validate_task_list_links(task_list_payload, ownership_map)
    pipeline_link_errors, pipeline_link_warnings = _validate_pipeline_links(pipeline_payload, task_list_payload)

    errors = task_list_link_errors + pipeline_link_errors
    warnings = task_list_link_warnings + pipeline_link_warnings
    if args.write and not errors:
        write_task_list_payload(context, task_list_payload)
        write_pipeline_payload(context, pipeline_payload)

    payload = {
        "command": "migrate.trackers-to-json",
        "errors": errors,
        "pipeline_references": _count_pipeline_task_references(pipeline_payload),
        "pipeline_rows": len(pipeline_payload.get("execution_sequence", [])),
        "strict": bool(args.strict),
        "task_entries": len(task_list_payload.get("tasks", [])),
        "warnings": warnings,
        "write": bool(args.write),
        "written_files": [str(context.task_list_path), str(context.pipeline_path)] if args.write and not errors else [],
    }
    print(json.dumps(payload, ensure_ascii=False))

    if errors:
        return 4
    if args.strict and warnings:
        return 4
    return 0


def _validate_schema_metadata(schema_path: Path, expected_version: str) -> None:
    """Validate schema metadata consistency with expected contract version."""
    schema_payload = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_version = str(schema_payload.get("properties", {}).get("schema_version", {}).get("const", "")).strip()
    if schema_version != expected_version:
        raise SystemExit(
            f"workflow command error: schema {schema_path} has schema_version const {schema_version!r}; "
            f"expected {expected_version!r}."
        )


def _collect_dev_map_ownership(dev_map: dict[str, Any]) -> dict[str, DevMapOwnership]:
    """Collect task ownership mapping from DEV_MAP hierarchy."""
    ownership: dict[str, DevMapOwnership] = {}
    for milestone in dev_map.get("milestones", []):
        milestone_id = str(milestone.get("id", ""))
        for feature in milestone.get("features", []):
            feature_marker = _feature_owner_marker(str(feature.get("id", "")))
            for issue in feature.get("issues", []):
                issue_id = str(issue.get("id", ""))
                for task in issue.get("tasks", []):
                    task_id = str(task.get("id", "")).strip()
                    if not task_id or task_id in ownership:
                        continue
                    ownership[task_id] = DevMapOwnership(
                        task_id=task_id,
                        milestone_id=milestone_id,
                        owner_marker=feature_marker,
                        owner_path=issue_id,
                    )
        for standalone_issue in milestone.get("standalone_issues", []):
            owner_marker = _standalone_owner_marker(str(standalone_issue.get("id", "")))
            standalone_id = str(standalone_issue.get("id", ""))
            for task in standalone_issue.get("tasks", []):
                task_id = str(task.get("id", "")).strip()
                if not task_id or task_id in ownership:
                    continue
                ownership[task_id] = DevMapOwnership(
                    task_id=task_id,
                    milestone_id=milestone_id,
                    owner_marker=owner_marker,
                    owner_path=standalone_id,
                )
    return ownership


def _feature_owner_marker(feature_id: str) -> str:
    """Build TASK_LIST marker owner token from feature ID."""
    match = FEATURE_PATTERN.fullmatch(feature_id.upper())
    if match is None:
        return "F?"
    return f"F{int(match.group('feature_num'))}"


def _standalone_owner_marker(standalone_id: str) -> str:
    """Build TASK_LIST marker owner token from standalone issue ID."""
    match = STANDALONE_PATTERN.fullmatch(standalone_id.upper())
    if match is None:
        return "SI?"
    return f"SI{int(match.group('si_num'))}"


def _validate_task_list_links(
    task_list_payload: dict[str, Any],
    ownership_map: dict[str, DevMapOwnership],
) -> tuple[list[str], list[str]]:
    """Validate task-list entries against DEV_MAP ownership links."""
    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    tasks = task_list_payload.get("tasks", [])
    if not isinstance(tasks, list):
        return ["task_list_payload.tasks must be a list."], warnings
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"task_list.tasks[{index}] must be an object.")
            continue
        task_id = str(task.get("id", "")).strip()
        marker = str(task.get("marker", "")).strip()
        if task_id in seen_ids:
            errors.append(f"Duplicate task id in TASK_LIST.json payload: {task_id}")
            continue
        seen_ids.add(task_id)
        if TASK_ID_PATTERN.fullmatch(task_id) is None:
            warnings.append(f"TASK_LIST task id {task_id!r} is not in canonical task-id format.")
            continue
        marker_match = MARKER_PATTERN.fullmatch(marker)
        if marker_match is None:
            errors.append(f"Invalid TASK_LIST marker for task {task_id}: {marker!r}.")
            continue
        owner = ownership_map.get(task_id)
        if owner is None:
            warnings.append(f"TASK_LIST task {task_id} is not present in DEV_MAP ownership map.")
            continue
        if marker_match.group("milestone") != owner.milestone_id:
            errors.append(
                f"TASK_LIST marker milestone mismatch for task {task_id}: "
                f"{marker_match.group('milestone')} != {owner.milestone_id}."
            )
        if marker_match.group("owner") != owner.owner_marker:
            errors.append(
                f"TASK_LIST marker owner mismatch for task {task_id}: "
                f"{marker_match.group('owner')} != {owner.owner_marker} ({owner.owner_path})."
            )
    return errors, warnings


def _validate_pipeline_links(
    pipeline_payload: dict[str, Any],
    task_list_payload: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Validate pipeline task references against TASK_LIST payload."""
    errors: list[str] = []
    warnings: list[str] = []
    task_ids = {
        str(task.get("id", "")).strip()
        for task in task_list_payload.get("tasks", [])
        if isinstance(task, dict)
    }
    for item_index, item in enumerate(pipeline_payload.get("execution_sequence", [])):
        if not isinstance(item, dict):
            errors.append(f"pipeline.execution_sequence[{item_index}] must be an object.")
            continue
        for task_id in item.get("tasks", []):
            _validate_pipeline_task_id(str(task_id).strip(), task_ids, errors, warnings, f"execution_sequence[{item_index}]")
    for block_index, block in enumerate(pipeline_payload.get("functional_blocks", [])):
        if not isinstance(block, dict):
            errors.append(f"pipeline.functional_blocks[{block_index}] must be an object.")
            continue
        for task_id in block.get("tasks", []):
            _validate_pipeline_task_id(str(task_id).strip(), task_ids, errors, warnings, f"functional_blocks[{block_index}]")
    for overlap_index, overlap in enumerate(pipeline_payload.get("overlaps", [])):
        if not isinstance(overlap, dict):
            errors.append(f"pipeline.overlaps[{overlap_index}] must be an object.")
            continue
        overlap_tasks = overlap.get("tasks")
        if not isinstance(overlap_tasks, list) or len(overlap_tasks) != 2:
            errors.append(f"pipeline.overlaps[{overlap_index}].tasks must be a list with exactly 2 items.")
            continue
        for task_index, task_id in enumerate(overlap_tasks):
            _validate_pipeline_task_id(
                str(task_id).strip(),
                task_ids,
                errors,
                warnings,
                f"overlaps[{overlap_index}].tasks[{task_index}]",
            )
    return errors, warnings


def _validate_pipeline_task_id(
    task_id: str,
    known_task_ids: set[str],
    errors: list[str],
    warnings: list[str],
    location: str,
) -> None:
    """Validate one pipeline task reference and append error/warning lists."""
    if TASK_ID_PATTERN.fullmatch(task_id) is None:
        warnings.append(f"Pipeline task reference {task_id!r} at {location} is not canonical task-id format.")
        return
    if task_id not in known_task_ids:
        warnings.append(f"Pipeline task reference {task_id} at {location} is not present in TASK_LIST payload.")


def _count_pipeline_task_references(pipeline_payload: dict[str, Any]) -> int:
    """Count total task references across all pipeline sections."""
    total = 0
    for item in pipeline_payload.get("execution_sequence", []):
        if isinstance(item, dict):
            total += len(item.get("tasks", []))
    for block in pipeline_payload.get("functional_blocks", []):
        if isinstance(block, dict):
            total += len(block.get("tasks", []))
    for overlap in pipeline_payload.get("overlaps", []):
        if isinstance(overlap, dict):
            tasks = overlap.get("tasks", [])
            if isinstance(tasks, list):
                total += len(tasks)
    return total


if __name__ == "__main__":
    raise SystemExit(main())
