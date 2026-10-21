"""Prevent production code from depending on removed schema ensure wrappers."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REMOVED_WRAPPERS = {
    "ensure_user_schema",
    "ensure_interaction_event_schema",
    "ensure_moderation_schema",
    "ensure_channels_indexes",
    "ensure_video_indexes",
    "ensure_similarity_schema",
    "ensure_random_cache_schema",
}
PRODUCTION_ROOTS = [
    ROOT / "client" / "backend",
    ROOT / "engine" / "server" / "api",
    ROOT / "engine" / "server" / "data",
    ROOT / "engine" / "server" / "db" / "jobs",
]
IGNORED_PARTS = {"__pycache__", "tests"}
ALLOWED_LOCAL_ENSURE_FILES = {
    # These job/test-local helpers are not the removed schema-ownership cleanup runtime wrappers.
    ROOT / "engine" / "server" / "db" / "jobs" / "precompute-similar-ann.py",
    ROOT / "engine" / "server" / "db" / "jobs" / "recompute-popularity.py",
    ROOT / "engine" / "server" / "db" / "jobs" / "sync-whitelist.py",
}


def _production_files() -> list[Path]:
    """Return production Python files covered by the removed-wrapper guard."""
    files: list[Path] = []
    for root in PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            if any(part in IGNORED_PARTS for part in path.parts):
                continue
            files.append(path)
    return files


def _defined_names(tree: ast.AST) -> set[str]:
    """Return function names defined inside one Python syntax tree."""
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def _called_names(tree: ast.AST) -> set[str]:
    """Return direct function names called inside one Python syntax tree."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def _imported_names(tree: ast.AST) -> set[str]:
    """Return imported symbol names and aliases from one Python syntax tree."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def test_removed_schema_wrappers_are_not_defined_imported_or_called() -> None:
    """Removed schema wrappers from the schema-ownership cleanup must not remain in production code."""
    offenders: list[str] = []
    for path in _production_files():
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        names = _defined_names(tree) | _imported_names(tree) | _called_names(tree)
        forbidden = sorted(names.intersection(REMOVED_WRAPPERS))
        if forbidden and path not in ALLOWED_LOCAL_ENSURE_FILES:
            rel = path.relative_to(ROOT).as_posix()
            offenders.append(f"{rel}: {', '.join(forbidden)}")

    assert offenders == []
