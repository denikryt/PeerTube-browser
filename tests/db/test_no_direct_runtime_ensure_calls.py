"""Prevent production code from depending directly on transitional schema wrappers."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_CALLS = {
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
    ROOT / "engine" / "server" / "db" / "jobs",
]
ALLOWED_FILES = {
    ROOT / "client" / "backend" / "lib" / "users_store.py",
    ROOT / "engine" / "server" / "data" / "interaction_events.py",
    ROOT / "engine" / "server" / "data" / "moderation.py",
    ROOT / "engine" / "server" / "data" / "channels.py",
    ROOT / "engine" / "server" / "data" / "videos.py",
    ROOT / "engine" / "server" / "data" / "similarity_cache.py",
    ROOT / "engine" / "server" / "data" / "random_cache.py",
}
IGNORED_PARTS = {"__pycache__", "tests"}


def _production_files() -> list[Path]:
    """Return production Python files covered by the direct-call guard."""
    files: list[Path] = []
    for root in PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            if path in ALLOWED_FILES:
                continue
            if any(part in IGNORED_PARTS for part in path.parts):
                continue
            files.append(path)
    return files


def _called_names(path: Path) -> set[str]:
    """Parse a file and return direct function names called inside it."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def test_production_code_uses_bootstrap_instead_of_direct_ensure_wrappers() -> None:
    """Production runtime paths must not call transitional schema wrappers directly."""
    offenders: list[str] = []
    for path in _production_files():
        forbidden = sorted(_called_names(path).intersection(FORBIDDEN_CALLS))
        if forbidden:
            rel = path.relative_to(ROOT).as_posix()
            offenders.append(f"{rel}: {', '.join(forbidden)}")

    assert offenders == []
