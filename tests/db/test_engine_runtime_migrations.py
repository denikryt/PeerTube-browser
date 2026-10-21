"""Test Engine main/runtime current-shape migration resources."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.channels import ensure_channels_indexes  # noqa: E402
from data.interaction_events import ensure_interaction_event_schema  # noqa: E402
from data.moderation import ensure_moderation_schema  # noqa: E402
from data.videos import ensure_video_indexes  # noqa: E402
from db.migrations.apply import apply_main_read_indexes, apply_main_runtime_migrations  # noqa: E402


def _connect() -> sqlite3.Connection:
    """Create a row-aware temporary SQLite connection for schema assertions."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _create_minimal_content_tables(conn: sqlite3.Connection) -> None:
    """Create only the columns needed by current Engine read-index helpers."""
    conn.executescript(
        """
        CREATE TABLE channels (
          channel_id TEXT,
          instance_domain TEXT,
          followers_count INTEGER,
          videos_count INTEGER,
          channel_name TEXT
        );
        CREATE TABLE videos (
          video_id TEXT,
          video_uuid TEXT,
          instance_domain TEXT
        );
        CREATE TABLE video_embeddings (
          video_id TEXT,
          instance_domain TEXT
        );
        """
    )


def _indexes(conn: sqlite3.Connection) -> set[str]:
    """Return non-autoindex names from sqlite_master."""
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        if not row["name"].startswith("sqlite_autoindex")
    }


def _tables(conn: sqlite3.Connection) -> set[str]:
    """Return user-visible table names from sqlite_master."""
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Return primary-key columns in declared order."""
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})") if row[5] > 0]


def _schema_signature(conn: sqlite3.Connection) -> dict[str, object]:
    """Return stable table/index facts for wrapper-vs-migration comparisons."""
    return {
        "tables": _tables(conn),
        "indexes": _indexes(conn),
        "interaction_raw_pk": _pk_columns(conn, "interaction_raw_events"),
        "interaction_signals_pk": _pk_columns(conn, "interaction_signals"),
        "instance_denylist_pk": _pk_columns(conn, "instance_denylist"),
        "channel_moderation_pk": _pk_columns(conn, "channel_moderation"),
    }


def test_engine_main_runtime_migrations_create_runtime_tables_and_indexes() -> None:
    """Main runtime migrations must create current Engine tables and read indexes."""
    conn = _connect()
    _create_minimal_content_tables(conn)

    apply_main_runtime_migrations(conn)

    assert {
        "interaction_raw_events",
        "interaction_signals",
        "instance_denylist",
        "channel_moderation",
    }.issubset(_tables(conn))
    assert {
        "interaction_raw_events_video_idx",
        "idx_instance_denylist_active",
        "idx_channel_moderation_status_instance",
        "idx_channels_followers_videos_name",
        "idx_channels_videos",
        "idx_channels_name",
        "idx_channels_instance",
        "idx_videos_uuid_instance",
        "idx_videos_id_instance",
        "idx_video_embeddings_id_instance",
    }.issubset(_indexes(conn))
    assert _pk_columns(conn, "interaction_raw_events") == ["event_id"]
    assert _pk_columns(conn, "interaction_signals") == ["video_uuid", "instance_domain"]


def test_engine_main_runtime_migrations_are_idempotent() -> None:
    """Applying current-shape Engine migrations twice must preserve schema signature."""
    conn = _connect()
    _create_minimal_content_tables(conn)

    apply_main_runtime_migrations(conn)
    before = _schema_signature(conn)
    apply_main_runtime_migrations(conn)

    assert _schema_signature(conn) == before


def test_engine_runtime_ensure_wrappers_match_main_runtime_migrations() -> None:
    """Legacy Engine ensure helpers must match migration-created runtime schema."""
    migration_conn = _connect()
    wrapper_conn = _connect()
    _create_minimal_content_tables(migration_conn)
    _create_minimal_content_tables(wrapper_conn)

    apply_main_runtime_migrations(migration_conn)
    ensure_interaction_event_schema(wrapper_conn)
    ensure_moderation_schema(wrapper_conn)
    ensure_channels_indexes(wrapper_conn)
    ensure_video_indexes(wrapper_conn)

    assert _schema_signature(wrapper_conn) == _schema_signature(migration_conn)


def test_main_read_indexes_are_noop_when_content_tables_are_missing() -> None:
    """Conditional read-index behavior must stay safe for empty databases."""
    conn = _connect()

    apply_main_read_indexes(conn)

    assert _indexes(conn) == set()
