"""Test Client users DB current-shape migration resources."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "backend"))

from lib.users_store import ensure_user_schema  # noqa: E402

from client.backend.db.migrate import apply_client_user_migrations  # noqa: E402


def _connect() -> sqlite3.Connection:
    """Create a row-aware temporary SQLite connection for schema assertions."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    """Return user-visible table names in a test database."""
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _indexes(conn: sqlite3.Connection) -> set[str]:
    """Return user-created index names in a test database."""
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        if not row["name"].startswith("sqlite_autoindex")
    }


def _columns(conn: sqlite3.Connection, table: str) -> tuple[tuple[object, ...], ...]:
    """Return stable column metadata for table-shape comparisons."""
    return tuple(
        (row[1], row[2], row[3], row[4], row[5])
        for row in conn.execute(f"PRAGMA table_info({table})")
    )


def _schema_signature(conn: sqlite3.Connection) -> dict[str, object]:
    """Return the schema facts that must match between wrappers and migrations."""
    return {
        "tables": _tables(conn),
        "indexes": _indexes(conn),
        "users_columns": _columns(conn, "users"),
        "likes_columns": _columns(conn, "likes"),
    }


def test_client_user_migration_creates_users_likes_and_updated_index() -> None:
    """Client users migration must create the current profile storage schema."""
    conn = _connect()

    apply_client_user_migrations(conn)

    assert {"users", "likes"}.issubset(_tables(conn))
    assert "likes_user_updated_idx" in _indexes(conn)


def test_client_like_primary_key_is_user_video_instance_in_order() -> None:
    """The like identity contract must remain user_id/video_id/instance_domain."""
    conn = _connect()

    apply_client_user_migrations(conn)

    pk_columns = [row[1] for row in conn.execute("PRAGMA table_info(likes)") if row[5] > 0]
    assert pk_columns == ["user_id", "video_id", "instance_domain"]


def test_client_user_migration_is_idempotent() -> None:
    """Current-shape migration resources must be safe to apply more than once."""
    conn = _connect()

    apply_client_user_migrations(conn)
    before = _schema_signature(conn)
    apply_client_user_migrations(conn)

    assert _schema_signature(conn) == before


def test_client_ensure_user_schema_matches_migration_schema() -> None:
    """The legacy ensure wrapper must produce the same schema as migration resources."""
    migration_conn = _connect()
    wrapper_conn = _connect()

    apply_client_user_migrations(migration_conn)
    ensure_user_schema(wrapper_conn)

    assert _schema_signature(wrapper_conn) == _schema_signature(migration_conn)
