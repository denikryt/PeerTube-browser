"""Resolve canonical repository paths for workflow commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkflowContext:
    """Store canonical local tracker paths used by workflow commands."""

    root_dir: Path
    dev_map_path: Path
    task_list_path: Path
    pipeline_path: Path
    feature_plans_path: Path


def build_default_context() -> WorkflowContext:
    """Build context from the repository-relative module location."""
    root_dir = Path(__file__).resolve().parents[2]
    return WorkflowContext(
        root_dir=root_dir,
        dev_map_path=root_dir / "dev" / "map" / "DEV_MAP.json",
        task_list_path=root_dir / "dev" / "TASK_LIST.md",
        pipeline_path=root_dir / "dev" / "TASK_EXECUTION_PIPELINE.md",
        feature_plans_path=root_dir / "dev" / "FEATURE_PLANS.md",
    )

