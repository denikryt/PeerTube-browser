"""Static regression tests for removed internal compatibility shims."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PATHS = [
    ROOT / "engine/server/api/handlers/similar.py",
    ROOT / "engine/crawler/src/db.ts",
]
SERVER_CONFIG_FORBIDDEN_TOKENS = [
    "RECOMMENDATION_PIPELINE",
    "DEFAULT_POPULAR_POOL_SIZE",
    "DEFAULT_FRESH_POOL_SIZE",
    "validate_recommendation_config",
]
SEARCH_ROOTS = [
    ROOT / "engine/server/api",
    ROOT / "engine/crawler/src",
    ROOT / "engine/crawler/test",
    ROOT / "tests",
]
EXCLUDED_PARTS = {
    "__pycache__",
    "node_modules",
    "dist",
    "dist-test",
}
FORBIDDEN_IMPORT_TOKENS = [
    "handlers.similar",
    "import_module(\"handlers.similar\")",
    "import_module('handlers.similar')",
    "from similar import",
    "import similar",
    'from "./db.js"',
    "from './db.js'",
    'from "./db"',
    "from './db'",
]


def _source_files() -> list[Path]:
    """Return runtime and test source files covered by the shim-removal guard."""
    files: list[Path] = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path == Path(__file__).resolve():
                continue
            if not path.is_file() or EXCLUDED_PARTS.intersection(path.parts):
                continue
            if path.suffix in {".py", ".ts"}:
                files.append(path)
    return files


def test_removed_compatibility_shim_files_do_not_exist() -> None:
    """The deleted facade/re-export files must not reappear under their old paths."""
    missing = [str(path.relative_to(ROOT)) for path in FORBIDDEN_PATHS if path.exists()]

    assert missing == []


def test_server_config_no_longer_reexports_recommendation_config() -> None:
    """server_config.py should no longer own recommendation-domain config symbols."""
    text = (ROOT / "engine/server/api/server_config.py").read_text()
    found = [token for token in SERVER_CONFIG_FORBIDDEN_TOKENS if token in text]

    assert found == []


def test_removed_shim_import_paths_do_not_return() -> None:
    """Runtime and test code should import direct owners instead of old shims."""
    matches: list[str] = []
    for path in _source_files():
        text = path.read_text()
        for token in FORBIDDEN_IMPORT_TOKENS:
            if token in text:
                matches.append(f"{path.relative_to(ROOT)}: {token}")

    assert matches == []
