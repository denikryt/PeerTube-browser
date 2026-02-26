"""Register and execute sync command routing for workflow CLI."""

from __future__ import annotations

import argparse
from argparse import Namespace
from typing import Any

from .context import WorkflowContext
from .output import emit_json


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
    """Emit deterministic sync feature command surface payload."""
    selector_payload: dict[str, Any] = {
        "all": bool(args.all),
        "feature_id": str(getattr(args, "feature_id", "") or "").strip() or None,
        "milestone_id": str(getattr(args, "milestone_id", "") or "").strip() or None,
    }
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
            "write": bool(args.write),
        }
    )
    return 0
