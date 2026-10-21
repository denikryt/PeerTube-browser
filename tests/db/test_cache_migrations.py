"""Test Engine cache database current-shape migration resources."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.random_cache import ensure_random_cache_schema  # noqa: E402
from data.similarity_cache import ensure_similarity_schema  # noqa: E402
from db.migrations.apply import (  # noqa: E402
    apply_random_cache_migrations,
    apply_similarity_cache_migrations,
)


def _connect() -> sqlite3.Connection:
    """Create a row-aware temporary SQLite connection for cache schema tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    """Return user-visible table names."""
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _indexes(conn: sqlite3.Connection) -> set[str]:
    """Return non-autoindex names."""
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        if not row["name"].startswith("sqlite_autoindex")
    }


def _pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Return primary-key columns in declared order."""
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})") if row[5] > 0]


def _signature(conn: sqlite3.Connection) -> dict[str, object]:
    """Return schema facts that must match between cache wrappers and migrations."""
    return {"tables": _tables(conn), "indexes": _indexes(conn)}


def test_similarity_cache_migration_creates_current_tables_indexes_and_pk() -> None:
    """Similarity cache migration must preserve cache table identity contracts."""
    conn = _connect()

    apply_similarity_cache_migrations(conn)

    assert {"similarity_sources", "similarity_items"}.issubset(_tables(conn))
    assert "similarity_source_rank_idx" in _indexes(conn)
    assert _pk_columns(conn, "similarity_items") == [
        "source_video_id",
        "source_instance_domain",
        "similar_video_id",
        "similar_instance_domain",
    ]


def test_random_cache_migration_creates_current_random_rowids_table() -> None:
    """Random cache migration must preserve the position/video_rowid table shape."""
    conn = _connect()

    apply_random_cache_migrations(conn)

    assert "random_rowids" in _tables(conn)
    assert _pk_columns(conn, "random_rowids") == ["position"]


def test_cache_migrations_are_idempotent() -> None:
    """Cache current-shape resources must be safe to apply repeatedly."""
    similarity_conn = _connect()
    random_conn = _connect()

    apply_similarity_cache_migrations(similarity_conn)
    similarity_before = _signature(similarity_conn)
    apply_similarity_cache_migrations(similarity_conn)
    apply_random_cache_migrations(random_conn)
    random_before = _signature(random_conn)
    apply_random_cache_migrations(random_conn)

    assert _signature(similarity_conn) == similarity_before
    assert _signature(random_conn) == random_before


def test_cache_ensure_wrappers_match_migration_schemas() -> None:
    """Existing cache ensure helpers must match centralized migration resources."""
    similarity_migration = _connect()
    similarity_wrapper = _connect()
    random_migration = _connect()
    random_wrapper = _connect()

    apply_similarity_cache_migrations(similarity_migration)
    ensure_similarity_schema(similarity_wrapper)
    apply_random_cache_migrations(random_migration)
    ensure_random_cache_schema(random_wrapper)

    assert _signature(similarity_wrapper) == _signature(similarity_migration)
    assert _signature(random_wrapper) == _signature(random_migration)
