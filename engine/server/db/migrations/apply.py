"""Apply Engine current-shape SQLite migration resources.

Stage 6 centralizes SQL resources while preserving the existing runtime
`ensure_*` wrappers. The helpers here intentionally do not create a migration
history table because current callers expect idempotent schema creation rather
than ordered historical migration state.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

MIGRATIONS_ROOT = Path(__file__).resolve().parent
MAIN_DIR = MIGRATIONS_ROOT / "main"
SIMILARITY_CACHE_DIR = MIGRATIONS_ROOT / "similarity_cache"
RANDOM_CACHE_DIR = MIGRATIONS_ROOT / "random_cache"

_TARGET_TABLE_PATTERN = re.compile(r"--\s*target_table:\s*([A-Za-z0-9_]+)")


def apply_sql_migrations(conn: sqlite3.Connection, directory: Path) -> None:
    """Execute all SQL migration resource files in filename order.

    This generic helper is used only for resources that are safe to execute
    unconditionally. Conditional read indexes use `apply_main_read_indexes` so
    missing content tables keep the same no-op behavior as legacy helpers.
    """
    for path in sorted(directory.glob("*.sql")):
        conn.executescript(path.read_text(encoding="utf-8"))
    conn.commit()


def apply_interaction_event_migration(conn: sqlite3.Connection) -> None:
    """Apply only the Engine interaction event current-shape schema."""
    conn.executescript((MAIN_DIR / "0001_interaction_events.sql").read_text(encoding="utf-8"))
    conn.commit()


def apply_moderation_migration(conn: sqlite3.Connection) -> None:
    """Apply only the Engine moderation current-shape schema."""
    conn.executescript((MAIN_DIR / "0002_moderation.sql").read_text(encoding="utf-8"))
    conn.commit()


def apply_main_read_indexes(conn: sqlite3.Connection) -> None:
    """Apply read indexes only when their target tables already exist.

    Legacy index helpers skipped missing content tables. This function keeps
    that contract while storing the index SQL in a central resource file.
    """
    sql = (MAIN_DIR / "0003_read_indexes.sql").read_text(encoding="utf-8")
    for target, statement in _iter_targeted_statements(sql):
        if _table_exists(conn, target):
            conn.execute(statement)
    conn.commit()


def apply_main_runtime_migrations(conn: sqlite3.Connection) -> None:
    """Apply Engine runtime schemas and conditional read indexes."""
    apply_interaction_event_migration(conn)
    apply_moderation_migration(conn)
    apply_main_read_indexes(conn)


def apply_similarity_cache_migrations(conn: sqlite3.Connection) -> None:
    """Apply the current similarity-cache schema resources."""
    apply_sql_migrations(conn, SIMILARITY_CACHE_DIR)


def apply_random_cache_migrations(conn: sqlite3.Connection) -> None:
    """Apply the current random-cache schema resources."""
    apply_sql_migrations(conn, RANDOM_CACHE_DIR)


def _iter_targeted_statements(sql: str) -> list[tuple[str, str]]:
    """Return `(target_table, statement)` pairs from targeted SQL comments.

    The parser is intentionally small because `0003_read_indexes.sql` is a
    project-owned resource with one `-- target_table:` marker per statement.
    """
    statements: list[tuple[str, str]] = []
    current_target: str | None = None
    current_lines: list[str] = []
    for raw_line in sql.splitlines():
        match = _TARGET_TABLE_PATTERN.match(raw_line.strip())
        if match:
            if current_target and current_lines:
                statements.append((current_target, "\n".join(current_lines).strip().rstrip(";")))
            current_target = match.group(1)
            current_lines = []
            continue
        if current_target is None or not raw_line.strip():
            continue
        current_lines.append(raw_line)
        if raw_line.strip().endswith(";"):
            statements.append((current_target, "\n".join(current_lines).strip().rstrip(";")))
            current_target = None
            current_lines = []
    if current_target and current_lines:
        statements.append((current_target, "\n".join(current_lines).strip().rstrip(";")))
    return statements


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Return whether a table exists in the connected SQLite database."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table,),
    ).fetchone() is not None
