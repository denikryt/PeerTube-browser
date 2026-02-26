"""Register and execute sync command routing for workflow CLI."""

from __future__ import annotations

import argparse
import json
import re
import time
from argparse import Namespace
from pathlib import Path
from typing import Any

from .context import WorkflowContext
from .errors import WorkflowCommandError
from .github_adapter import (
    ensure_github_milestone_exists,
    gh_issue_edit,
    resolve_github_repository,
)
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
    """Resolve sync targets and execute feature-only remote sync contract."""
    dev_map = _load_json(context.dev_map_path)
    selector_mode = _resolve_sync_feature_selector_mode(args)
    target_features = _resolve_sync_feature_targets(
        selector_mode=selector_mode,
        feature_id_raw=getattr(args, "feature_id", None),
        milestone_id_raw=getattr(args, "milestone_id", None),
        dev_map=dev_map,
    )
    request_policy = _resolve_sync_request_policy(args)
    sync_result = _run_sync_feature_targets(
        context=context,
        target_features=target_features,
        request_policy=request_policy,
        github_enabled=bool(args.github),
        write=bool(args.write),
    )

    selector_payload: dict[str, Any] = {
        "all": bool(args.all),
        "feature_id": _normalize_id(str(getattr(args, "feature_id", "") or "").strip()) or None,
        "milestone_id": _normalize_id(str(getattr(args, "milestone_id", "") or "").strip()) or None,
    }
    target_feature_ids = [target["feature_id"] for target in target_features]
    emit_json(
        {
            "action": "synced-feature" if bool(args.write) else "would-sync-feature",
            "command": "sync.feature",
            "github_enabled": bool(args.github),
            "request_policy": request_policy,
            "root_dir": str(context.root_dir),
            "selector": selector_payload,
            "selector_mode": selector_mode,
            "sync_summary": sync_result["summary"],
            "sync_results": sync_result["results"],
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


def _run_sync_feature_targets(
    *,
    context: WorkflowContext,
    target_features: list[dict[str, Any]],
    request_policy: dict[str, float | int],
    github_enabled: bool,
    write: bool,
) -> dict[str, Any]:
    """Execute per-feature sync flow and return deterministic aggregate summary."""
    results: list[dict[str, Any]] = []
    summary = {
        "attempted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
    }
    repo_name_with_owner: str | None = None
    milestone_cache: set[str] = set()
    if write and github_enabled:
        repo_name_with_owner = resolve_github_repository(context.root_dir)["name_with_owner"]

    for index, target in enumerate(target_features):
        feature_node = target["feature"]
        feature_id = target["feature_id"]
        milestone_node = target["milestone"]
        milestone_id = target["milestone_id"]
        milestone_title = _resolve_milestone_title(milestone_node, milestone_id)
        result = _sync_one_feature_target(
            feature_node=feature_node,
            feature_id=feature_id,
            milestone_id=milestone_id,
            milestone_title=milestone_title,
            repo_name_with_owner=repo_name_with_owner,
            request_policy=request_policy,
            github_enabled=github_enabled,
            write=write,
            milestone_cache=milestone_cache,
        )
        results.append(result)
        summary["attempted"] += 1
        if result["action"] in {"updated", "would-update"}:
            summary["updated"] += 1
        elif result["action"] in {"skipped", "would-skip"}:
            summary["skipped"] += 1
        if "error" in result:
            summary["errors"].append(result["error"])
        if (
            write
            and github_enabled
            and request_policy["pause_seconds"] > 0
            and index < len(target_features) - 1
        ):
            time.sleep(float(request_policy["pause_seconds"]))
    return {"results": results, "summary": summary}


def _sync_one_feature_target(
    *,
    feature_node: dict[str, Any],
    feature_id: str,
    milestone_id: str,
    milestone_title: str,
    repo_name_with_owner: str | None,
    request_policy: dict[str, float | int],
    github_enabled: bool,
    write: bool,
    milestone_cache: set[str],
) -> dict[str, Any]:
    """Sync one feature issue title/body from local feature metadata."""
    issue_number = _coerce_issue_number(feature_node.get("gh_issue_number"))
    issue_url = str(feature_node.get("gh_issue_url", "")).strip()
    if issue_number is None or not issue_url:
        return {
            "action": "would-skip" if not write else "skipped",
            "feature_id": feature_id,
            "reason": "feature-issue-not-mapped",
            "missing_fields": [
                field
                for field, missing in (
                    ("gh_issue_number", issue_number is None),
                    ("gh_issue_url", not issue_url),
                )
                if missing
            ],
        }

    title = str(feature_node.get("title", "")).strip() or feature_id
    body = _build_feature_issue_body(feature_node)
    if not write:
        return {
            "action": "would-update",
            "feature_id": feature_id,
            "gh_issue_number": issue_number,
            "gh_issue_url": issue_url,
        }
    if not github_enabled:
        return {
            "action": "skipped",
            "feature_id": feature_id,
            "gh_issue_number": issue_number,
            "gh_issue_url": issue_url,
            "reason": "github-disabled",
        }
    if repo_name_with_owner is None:
        return {
            "action": "skipped",
            "feature_id": feature_id,
            "gh_issue_number": issue_number,
            "gh_issue_url": issue_url,
            "reason": "repo-resolution-missing",
        }

    milestone_cache_key = f"{milestone_id}:{milestone_title}"
    try:
        if milestone_cache_key not in milestone_cache:
            ensure_github_milestone_exists(
                repo_name_with_owner=repo_name_with_owner,
                milestone_title=milestone_title,
                milestone_id=milestone_id,
                max_retries=int(request_policy["max_retries"]),
                retry_pause_seconds=float(request_policy["pause_seconds"]),
                timeout_seconds=float(request_policy["request_timeout"]),
            )
            milestone_cache.add(milestone_cache_key)
        gh_issue_edit(
            repo_name_with_owner=repo_name_with_owner,
            issue_number=issue_number,
            title=title,
            body=body,
            milestone_title=milestone_title,
            max_retries=int(request_policy["max_retries"]),
            retry_pause_seconds=float(request_policy["pause_seconds"]),
            timeout_seconds=float(request_policy["request_timeout"]),
        )
    except WorkflowCommandError as error:
        return {
            "action": "failed",
            "error": f"feature {feature_id}: {error}",
            "feature_id": feature_id,
            "gh_issue_number": issue_number,
            "gh_issue_url": issue_url,
        }
    return {
        "action": "updated",
        "feature_id": feature_id,
        "gh_issue_number": issue_number,
        "gh_issue_url": issue_url,
    }


def _resolve_sync_request_policy(args: Namespace) -> dict[str, float | int]:
    """Normalize sync request policy arguments."""
    max_retries = int(getattr(args, "max_retries", 0))
    pause_seconds = float(getattr(args, "pause_seconds", 0.0))
    request_timeout = float(getattr(args, "request_timeout", 20.0))
    if max_retries < 0:
        raise WorkflowCommandError("--max-retries must be >= 0.", exit_code=4)
    if pause_seconds < 0:
        raise WorkflowCommandError("--pause-seconds must be >= 0.", exit_code=4)
    if request_timeout <= 0:
        raise WorkflowCommandError("--request-timeout must be > 0.", exit_code=4)
    return {
        "max_retries": max_retries,
        "pause_seconds": pause_seconds,
        "request_timeout": request_timeout,
    }


def _resolve_milestone_title(milestone_node: dict[str, Any], milestone_id: str) -> str:
    """Resolve non-empty GitHub milestone title from one milestone node."""
    title = str(milestone_node.get("title", "")).strip()
    if not title:
        raise WorkflowCommandError(
            f"Milestone {milestone_id} has empty title in DEV_MAP; cannot sync mapped feature issue.",
            exit_code=4,
        )
    return title


def _build_feature_issue_body(feature_node: dict[str, Any]) -> str:
    """Build feature issue body from feature description only."""
    return _resolve_feature_description(feature_node).strip() + "\n"


def _resolve_feature_description(feature_node: dict[str, Any]) -> str:
    """Resolve feature description with deterministic fallback."""
    description = str(feature_node.get("description", "")).strip()
    if description:
        return description
    return _build_default_feature_description(feature_node)


def _build_default_feature_description(feature_node: dict[str, Any]) -> str:
    """Build concise default feature description from title context."""
    feature_title = str(feature_node.get("title", "")).strip() or str(feature_node.get("id", "")).strip() or "feature scope"
    compact_title = " ".join(feature_title.split()).strip().rstrip(".")
    if not compact_title:
        return "This feature defines the required behavior and expected outcome."
    title_text = compact_title[0].lower() + compact_title[1:] if len(compact_title) > 1 else compact_title.lower()
    return (
        f"This feature addresses {title_text} by defining the required change "
        "and the expected user-visible outcome."
    )


def _coerce_issue_number(raw_issue_number: Any) -> int | None:
    """Normalize optional issue number to positive integer."""
    if raw_issue_number is None:
        return None
    try:
        issue_number = int(raw_issue_number)
    except (TypeError, ValueError):
        return None
    if issue_number <= 0:
        return None
    return issue_number


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
