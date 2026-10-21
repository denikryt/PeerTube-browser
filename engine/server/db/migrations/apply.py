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
_TARGET_COLUMNS_PATTERN = re.compile(r"--\s*target_columns:\s*([A-Za-z0-9_, ]+)")


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
    for target, required_columns, statement in _iter_targeted_statements(sql):
        if not _table_exists(conn, target):
            continue
        # Metadata-backed expression indexes are optional on legacy/minimal
        # content schemas. Skip only indexes that declare missing columns;
        # unrelated migration failures must still surface.
        if required_columns and not _table_has_columns(conn, target, required_columns):
            continue
        conn.execute(statement)
    conn.commit()


def apply_video_index_ids_migration(conn: sqlite3.Connection) -> None:
    """Apply the stable ANN index identity mapping schema."""
    conn.executescript((MAIN_DIR / "0004_video_index_ids.sql").read_text(encoding="utf-8"))
    conn.commit()


def apply_main_runtime_migrations(conn: sqlite3.Connection) -> None:
    """Apply Engine runtime schemas, stable index ids, and conditional read indexes."""
    apply_interaction_event_migration(conn)
    apply_moderation_migration(conn)
    apply_video_index_ids_migration(conn)
    apply_main_read_indexes(conn)


def apply_similarity_cache_migrations(conn: sqlite3.Connection) -> None:
    """Apply the current similarity-cache schema resources."""
    apply_sql_migrations(conn, SIMILARITY_CACHE_DIR)


def apply_random_cache_migrations(conn: sqlite3.Connection) -> None:
    """Apply the current random-cache schema resources."""
    apply_sql_migrations(conn, RANDOM_CACHE_DIR)


def _iter_targeted_statements(sql: str) -> list[tuple[str, tuple[str, ...], str]]:
    """Return index statements with explicit table/column prerequisites.

    Optional ``-- target_columns:`` markers keep metadata-v1 expression indexes
    safe on older/minimal ``videos`` tables while preserving table-only guards
    for the long-standing read indexes.
    """
    statements: list[tuple[str, tuple[str, ...], str]] = []
    current_target: str | None = None
    current_columns: tuple[str, ...] = ()
    current_lines: list[str] = []
    for raw_line in sql.splitlines():
        stripped = raw_line.strip()
        table_match = _TARGET_TABLE_PATTERN.match(stripped)
        if table_match:
            if current_target and current_lines:
                statements.append(
                    (current_target, current_columns, "\n".join(current_lines).strip().rstrip(";"))
                )
            current_target = table_match.group(1)
            current_columns = ()
            current_lines = []
            continue
        columns_match = _TARGET_COLUMNS_PATTERN.match(stripped)
        if columns_match and current_target is not None and not current_lines:
            current_columns = tuple(
                column.strip()
                for column in columns_match.group(1).split(",")
                if column.strip()
            )
            continue
        if current_target is None or not stripped:
            continue
        current_lines.append(raw_line)
        if stripped.endswith(";"):
            statements.append(
                (current_target, current_columns, "\n".join(current_lines).strip().rstrip(";"))
            )
            current_target = None
            current_columns = ()
            current_lines = []
    if current_target and current_lines:
        statements.append(
            (current_target, current_columns, "\n".join(current_lines).strip().rstrip(";"))
        )
    return statements


def _table_has_columns(
    conn: sqlite3.Connection, table: str, columns: tuple[str, ...]
) -> bool:
    """Return whether every explicitly required column exists on ``table``."""
    existing = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
    return all(column in existing for column in columns)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Return whether a table exists in the connected SQLite database."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table,),
    ).fetchone() is not None
