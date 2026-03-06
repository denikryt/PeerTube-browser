"""Define and validate canonical JSON contracts for workflow tracker payloads."""

from __future__ import annotations

from typing import Any

from .errors import WorkflowCommandError


TASK_LIST_CONTRACT_VERSION = "1.0"
PIPELINE_CONTRACT_VERSION = "1.0"
ISSUE_OVERLAPS_CONTRACT_VERSION = "1.0"
ISSUE_DEP_INDEX_CONTRACT_VERSION = "1.0"


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
    payload = {
        "schema_version": PIPELINE_CONTRACT_VERSION,
        "execution_sequence": pipeline_payload.get("execution_sequence_append", []),
        "functional_blocks": pipeline_payload.get("functional_blocks_append", []),
    }
    overlaps = pipeline_payload.get("overlaps_append")
    if overlaps is not None:
        payload["overlaps"] = overlaps
    return payload


def build_issue_overlaps_contract_payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Build canonical issue-overlaps JSON payload."""
    return {
        "schema_version": ISSUE_OVERLAPS_CONTRACT_VERSION,
        "overlaps": entries,
    }


def build_issue_dependency_index_contract_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Build canonical dependency-index payload with stable top-level keys."""
    return {
        "schema_version": ISSUE_DEP_INDEX_CONTRACT_VERSION,
        "feature_scope": payload.get("feature_scope", "all"),
        "by_issue": payload.get("by_issue", {}),
        "by_surface": payload.get("by_surface", {}),
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

    overlaps = payload.get("overlaps", [])
    if not isinstance(overlaps, list):
        raise WorkflowCommandError(f"{location}: overlaps must be a list when provided.", exit_code=4)
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


def validate_issue_overlaps_contract_payload(payload: dict[str, Any], location: str) -> None:
    """Validate dedicated issue-overlaps payload shape and pair semantics."""
    schema_version = str(payload.get("schema_version", "")).strip()
    if schema_version != ISSUE_OVERLAPS_CONTRACT_VERSION:
        raise WorkflowCommandError(
            f"{location}: unsupported issue-overlaps schema_version {schema_version!r}; "
            f"expected {ISSUE_OVERLAPS_CONTRACT_VERSION}.",
            exit_code=4,
        )

    overlaps = payload.get("overlaps")
    if not isinstance(overlaps, list):
        raise WorkflowCommandError(f"{location}: overlaps must be a list.", exit_code=4)

    seen_pairs: set[tuple[str, str]] = set()
    allowed_types = {"dependency", "conflict", "shared_logic"}
    for overlap_index, overlap in enumerate(overlaps):
        item_location = f"{location}.overlaps[{overlap_index}]"
        if not isinstance(overlap, dict):
            raise WorkflowCommandError(f"{item_location} must be an object.", exit_code=4)
        issues = _require_non_empty_string_list(overlap, "issues", item_location)
        if len(issues) != 2:
            raise WorkflowCommandError(f"{item_location}.issues must contain exactly 2 issue IDs.", exit_code=4)
        if issues[0] == issues[1]:
            raise WorkflowCommandError(f"{item_location}.issues must contain two distinct issue IDs.", exit_code=4)
        for issue_index, issue_id in enumerate(issues):
            if not _looks_like_issue_id(issue_id):
                raise WorkflowCommandError(
                    f"{item_location}.issues[{issue_index}] must use I<local>-F<feature_local>-M<milestone> format.",
                    exit_code=4,
                )
        pair_key = tuple(sorted(issues))
        if pair_key in seen_pairs:
            raise WorkflowCommandError(
                f"{item_location} duplicates overlap pair {pair_key[0]} <-> {pair_key[1]}.",
                exit_code=4,
            )
        seen_pairs.add(pair_key)

        overlap_type = _require_non_empty_string(overlap, "type", item_location)
        if overlap_type not in allowed_types:
            allowed = ", ".join(sorted(allowed_types))
            raise WorkflowCommandError(f"{item_location}.type must be one of: {allowed}.", exit_code=4)
        _require_non_empty_string(overlap, "surface", item_location)
        description = _require_non_empty_string(overlap, "description", item_location)
        _validate_overlap_description(description, item_location)

        order = overlap.get("order")
        if overlap_type == "dependency":
            if not isinstance(order, str) or not order.strip():
                raise WorkflowCommandError(f"{item_location}.order is required for dependency overlaps.", exit_code=4)
            normalized_order = order.strip()
            expected_options = {f"{issues[0]}->{issues[1]}", f"{issues[1]}->{issues[0]}"}
            if normalized_order not in expected_options:
                raise WorkflowCommandError(
                    f"{item_location}.order must reference the same issue IDs as the pair.",
                    exit_code=4,
                )
        elif order is not None and (not isinstance(order, str) or not order.strip()):
            raise WorkflowCommandError(f"{item_location}.order must be a non-empty string when provided.", exit_code=4)


def validate_issue_dependency_index_contract_payload(payload: dict[str, Any], location: str) -> None:
    """Validate dependency-index payload shape used by dependency CLI commands."""
    schema_version = str(payload.get("schema_version", "")).strip()
    if schema_version != ISSUE_DEP_INDEX_CONTRACT_VERSION:
        raise WorkflowCommandError(
            f"{location}: unsupported dependency-index schema_version {schema_version!r}; "
            f"expected {ISSUE_DEP_INDEX_CONTRACT_VERSION}.",
            exit_code=4,
        )
    _require_non_empty_string(payload, "feature_scope", location)

    by_issue = payload.get("by_issue")
    if not isinstance(by_issue, dict):
        raise WorkflowCommandError(f"{location}.by_issue must be an object.", exit_code=4)
    for issue_id, entry in by_issue.items():
        if not isinstance(entry, dict):
            raise WorkflowCommandError(f"{location}.by_issue[{issue_id!r}] must be an object.", exit_code=4)
        if not _looks_like_issue_id(str(issue_id)):
            raise WorkflowCommandError(f"{location}.by_issue contains invalid issue ID key {issue_id!r}.", exit_code=4)
        _require_non_empty_string_list(entry, "surfaces", f"{location}.by_issue[{issue_id!r}]")
        _require_non_empty_string(entry, "feature_id", f"{location}.by_issue[{issue_id!r}]")
        _require_non_empty_string(entry, "status", f"{location}.by_issue[{issue_id!r}]")

    by_surface = payload.get("by_surface")
    if not isinstance(by_surface, dict):
        raise WorkflowCommandError(f"{location}.by_surface must be an object.", exit_code=4)
    for surface_key, entry in by_surface.items():
        if not isinstance(entry, dict):
            raise WorkflowCommandError(f"{location}.by_surface[{surface_key!r}] must be an object.", exit_code=4)
        _require_non_empty_string(entry, "surface", f"{location}.by_surface[{surface_key!r}]")
        issue_ids = _require_non_empty_string_list(entry, "issue_ids", f"{location}.by_surface[{surface_key!r}]")
        for issue_index, issue_id in enumerate(issue_ids):
            if not _looks_like_issue_id(issue_id):
                raise WorkflowCommandError(
                    f"{location}.by_surface[{surface_key!r}].issue_ids[{issue_index}] uses invalid issue ID format.",
                    exit_code=4,
                )


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


def _looks_like_issue_id(issue_id: str) -> bool:
    """Return True when one string matches the canonical issue ID shape."""
    raw_value = str(issue_id).strip()
    if not raw_value.startswith("I") or "-F" not in raw_value or "-M" not in raw_value:
        return False
    parts = raw_value.split("-")
    if len(parts) != 3:
        return False
    if not parts[0][1:].isdigit():
        return False
    if not parts[1].startswith("F") or not parts[1][1:].isdigit():
        return False
    if not parts[2].startswith("M") or not parts[2][1:].isdigit():
        return False
    return True


def _validate_overlap_description(description: str, location: str) -> None:
    """Require short why/impact/action structure for overlap descriptions."""
    normalized = str(description).strip().lower()
    required_tokens = ("why:", "impact:", "action:")
    missing = [token.rstrip(":") for token in required_tokens if token not in normalized]
    if missing:
        raise WorkflowCommandError(
            f"{location}.description must include why:/impact:/action: segments; missing {', '.join(missing)}.",
            exit_code=4,
        )
