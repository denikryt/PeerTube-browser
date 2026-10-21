"""Path constants and required-file checks for the updater worker.

This module owns repository-relative path discovery used by both the direct
``updater-worker.py`` wrapper and the internal updater package.  It preserves
current direct-script path semantics without changing installer entrypoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

JOBS_DIR = Path(__file__).resolve().parents[1]
SERVER_DIR = JOBS_DIR.parents[1]
REPO_ROOT = JOBS_DIR.parents[3]


@dataclass(frozen=True)
class ResolvedUpdaterPaths:
    """Resolved filesystem paths consumed by the updater pipeline.

    The type is a narrow seam between CLI/default resolution and orchestration;
    it does not introduce new path defaults or deployment behavior.
    """

    repo_root: Path
    script_dir: Path
    crawler_dir: Path
    crawler_dist: Path
    schema_path: Path
    prod_db: Path
    staging_db: Path
    index_path: Path
    index_meta_path: Path
    similarity_db: Path
    merge_rules: Path
    lock_file: Path


def from_args(args) -> ResolvedUpdaterPaths:
    """Resolve updater paths from parsed args using current path semantics."""

    crawler_dir = Path(args.crawler_dir).resolve()
    crawler_dist = crawler_dir / "dist"
    return ResolvedUpdaterPaths(
        repo_root=REPO_ROOT,
        script_dir=JOBS_DIR,
        crawler_dir=crawler_dir,
        crawler_dist=crawler_dist,
        schema_path=(crawler_dir / "schema.sql").resolve(),
        prod_db=Path(args.prod_db).resolve(),
        staging_db=Path(args.staging_db).resolve(),
        index_path=Path(args.index_path).resolve(),
        index_meta_path=Path(args.index_meta_path).resolve(),
        similarity_db=Path(args.similarity_db).resolve(),
        merge_rules=Path(args.merge_rules).resolve(),
        lock_file=Path(args.lock_file).resolve(),
    )


def required_runtime_files(paths: ResolvedUpdaterPaths) -> tuple[Path, ...]:
    """Return the files the current updater requires before executing stages."""

    return (
        paths.prod_db,
        paths.schema_path,
        paths.merge_rules,
        paths.crawler_dist / "instances-cli.js",
        paths.crawler_dist / "channels-cli.js",
        paths.crawler_dist / "videos-cli.js",
        paths.crawler_dist / "channels-videos-count-cli.js",
        paths.script_dir / "merge-staging-db.py",
        paths.script_dir / "build-video-embeddings.py",
        paths.script_dir / "recompute-popularity.py",
        paths.script_dir / "precompute-similar-ann.py",
        paths.script_dir / "build-ann-index.py",
    )


def validate_required_files(paths: ResolvedUpdaterPaths) -> None:
    """Raise the current FileNotFoundError shape for missing updater inputs."""

    for required in required_runtime_files(paths):
        if not required.exists():
            raise FileNotFoundError(f"Required file is missing: {required}")
