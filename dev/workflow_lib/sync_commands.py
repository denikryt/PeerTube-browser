"""Register and execute sync command routing for workflow CLI."""

from __future__ import annotations

import argparse
import json
import re
from argparse import Namespace
from pathlib import Path
from typing import Any

from .context import WorkflowContext
from .errors import WorkflowCommandError
from .output import emit_json

FEATURE_ID_PATTERN = re.compile(r"^F(?P<feature_num>\d+)-M(?P<milestone_num>\d+)$")
MILESTONE_ID_PATTERN = re.compile(r"^M(?P<milestone_num>\d+)$")


def register_sync_router(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register sync command routing."""
    sync_parser = subparsers.add_parser(
        "sync",
        help="Synchronization workflow commands.",
    )
    sync_subparsers = sync_parser.add_subparsers(dest="sync_target", required=True)

    feature_parser = sync_subparsers.add_parser(
        "feature",
        help="Sync feature-level remote metadata/body without child issue materialization.",
    )
    feature_parser.add_argument("--feature-id", help="Target one feature ID.")
    feature_parser.add_argument("--milestone-id", help="Target all features from one milestone ID.")
    feature_parser.add_argument(
        "--all",
        action="store_true",
        help="Target all features across milestones.",
    )
    feature_parser.add_argument("--write", action="store_true", help="Apply remote sync side effects.")
    feature_parser.add_argument(
        "--github",
        dest="github",
        action="store_true",
        default=True,
        help="Enable GitHub sync calls.",
    )
    feature_parser.add_argument(
        "--no-github",
        dest="github",
        action="store_false",
        help="Skip GitHub sync calls.",
    )
    feature_parser.add_argument(
        "--pause-seconds",
        type=float,
        default=1.0,
        help="Pause between feature sync requests in write+github mode.",
    )
    feature_parser.add_argument(
        "--max-retries",
        type=int,
        default=4,
        help="Max retry attempts for transient GitHub request failures.",
    )
    feature_parser.add_argument(
        "--request-timeout",
        type=float,
        default=20.0,
        help="Per-request GitHub CLI timeout in seconds for write mode.",
    )
    feature_parser.set_defaults(handler=_handle_sync_feature)


def _handle_sync_feature(args: Namespace, context: WorkflowContext) -> int:
    """Resolve sync targets and emit deterministic dry-run payload."""
    dev_map = _load_json(context.dev_map_path)
    selector_mode = _resolve_sync_feature_selector_mode(args)
    target_features = _resolve_sync_feature_targets(
        selector_mode=selector_mode,
        feature_id_raw=getattr(args, "feature_id", None),
        milestone_id_raw=getattr(args, "milestone_id", None),
        dev_map=dev_map,
    )

    selector_payload: dict[str, Any] = {
        "all": bool(args.all),
        "feature_id": _normalize_id(str(getattr(args, "feature_id", "") or "").strip()) or None,
        "milestone_id": _normalize_id(str(getattr(args, "milestone_id", "") or "").strip()) or None,
    }
    target_feature_ids = [target["feature_id"] for target in target_features]
    emit_json(
        {
            "action": "would-sync-feature",
            "command": "sync.feature",
            "github_enabled": bool(args.github),
            "request_policy": {
                "max_retries": int(args.max_retries),
                "pause_seconds": float(args.pause_seconds),
                "request_timeout": float(args.request_timeout),
            },
            "root_dir": str(context.root_dir),
            "selector": selector_payload,
            "selector_mode": selector_mode,
            "target_count": len(target_feature_ids),
            "target_feature_ids": target_feature_ids,
            "write": bool(args.write),
        }
    )
    return 0


def _resolve_sync_feature_selector_mode(args: Namespace) -> str:
    """Resolve one selector mode and reject invalid selector combinations."""
    has_feature_selector = bool(str(getattr(args, "feature_id", "") or "").strip())
    has_milestone_selector = bool(str(getattr(args, "milestone_id", "") or "").strip())
    has_all_selector = bool(getattr(args, "all", False))
    enabled_count = sum((has_feature_selector, has_milestone_selector, has_all_selector))
    if enabled_count != 1:
        raise WorkflowCommandError(
            "sync feature requires exactly one selector mode: "
            "--feature-id <id> OR --milestone-id <id> OR --all.",
            exit_code=4,
        )
    if has_feature_selector:
        return "feature-id"
    if has_milestone_selector:
        return "milestone-id"
    return "all"


def _resolve_sync_feature_targets(
    *,
    selector_mode: str,
    feature_id_raw: Any,
    milestone_id_raw: Any,
    dev_map: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve deterministic feature target set for selected sync mode."""
    milestones = dev_map.get("milestones", [])
    if not isinstance(milestones, list):
        raise WorkflowCommandError("DEV_MAP milestones must be a list.", exit_code=4)

    targets: list[dict[str, Any]] = []
    if selector_mode == "feature-id":
        feature_id, feature_milestone_num = _parse_feature_id(str(feature_id_raw or ""))
        milestone_id = f"M{feature_milestone_num}"
        for milestone in milestones:
            if _normalize_id(str(milestone.get("id", ""))) != milestone_id:
                continue
            for feature in _iter_milestone_features(milestone):
                if _normalize_id(str(feature.get("id", ""))) != feature_id:
                    continue
                targets.append(
                    {
                        "feature": feature,
                        "feature_id": feature_id,
                        "milestone": milestone,
                        "milestone_id": milestone_id,
                    }
                )
                break
            break
        if not targets:
            raise WorkflowCommandError(f"Feature {feature_id} not found in DEV_MAP.", exit_code=4)
        return targets

    if selector_mode == "milestone-id":
        milestone_id = _parse_milestone_id(str(milestone_id_raw or ""))
        milestone_node = _find_milestone(dev_map, milestone_id)
        if milestone_node is None:
            raise WorkflowCommandError(f"Milestone {milestone_id} not found in DEV_MAP.", exit_code=4)
        for feature in sorted(_iter_milestone_features(milestone_node), key=lambda item: _normalize_id(str(item.get("id", "")))):
            feature_id = _normalize_id(str(feature.get("id", "")))
            if not feature_id:
                continue
            targets.append(
                {
                    "feature": feature,
                    "feature_id": feature_id,
                    "milestone": milestone_node,
                    "milestone_id": milestone_id,
                }
            )
        if not targets:
            raise WorkflowCommandError(
                f"sync feature selector --milestone-id {milestone_id} resolved zero feature targets.",
                exit_code=4,
            )
        return targets

    for milestone in sorted(milestones, key=lambda item: _normalize_id(str(item.get("id", "")))):
        milestone_id = _normalize_id(str(milestone.get("id", "")))
        if not milestone_id:
            continue
        for feature in sorted(_iter_milestone_features(milestone), key=lambda item: _normalize_id(str(item.get("id", "")))):
            feature_id = _normalize_id(str(feature.get("id", "")))
            if not feature_id:
                continue
            targets.append(
                {
                    "feature": feature,
                    "feature_id": feature_id,
                    "milestone": milestone,
                    "milestone_id": milestone_id,
                }
            )
    if not targets:
        raise WorkflowCommandError("sync feature selector --all resolved zero feature targets.", exit_code=4)
    return targets


def _iter_milestone_features(milestone: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized feature list for one milestone node."""
    features = milestone.get("features", [])
    if not isinstance(features, list):
        raise WorkflowCommandError(
            f"Milestone {_normalize_id(str(milestone.get('id', '')))!r} has invalid features payload in DEV_MAP.",
            exit_code=4,
        )
    return [feature for feature in features if isinstance(feature, dict)]


def _find_milestone(dev_map: dict[str, Any], milestone_id: str) -> dict[str, Any] | None:
    """Find milestone node by normalized milestone ID."""
    for milestone in dev_map.get("milestones", []):
        if _normalize_id(str(milestone.get("id", ""))) == milestone_id:
            return milestone
    return None


def _parse_feature_id(raw_feature_id: str) -> tuple[str, int]:
    """Validate feature ID format and return normalized values."""
    feature_id = _normalize_id(raw_feature_id)
    match = FEATURE_ID_PATTERN.fullmatch(feature_id)
    if match is None:
        raise WorkflowCommandError(
            f"Invalid feature ID {raw_feature_id!r}; expected F<local>-M<milestone>.",
            exit_code=4,
        )
    return feature_id, int(match.group("milestone_num"))


def _parse_milestone_id(raw_milestone_id: str) -> str:
    """Validate milestone ID format and return normalized milestone ID."""
    milestone_id = _normalize_id(raw_milestone_id)
    if MILESTONE_ID_PATTERN.fullmatch(milestone_id) is None:
        raise WorkflowCommandError(
            f"Invalid milestone ID {raw_milestone_id!r}; expected M<milestone>.",
            exit_code=4,
        )
    return milestone_id


def _normalize_id(raw_id: str) -> str:
    """Normalize identifier to canonical uppercase form."""
    return str(raw_id).strip().upper()


def _load_json(path: Path) -> dict[str, Any]:
    """Read JSON payload from one path with deterministic validation errors."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise WorkflowCommandError(f"Required file not found: {path}", exit_code=4) from error
    except json.JSONDecodeError as error:
        raise WorkflowCommandError(f"Invalid JSON in {path}: {error}", exit_code=4) from error
    if not isinstance(payload, dict):
        raise WorkflowCommandError(f"JSON root in {path} must be an object.", exit_code=4)
    return payload
