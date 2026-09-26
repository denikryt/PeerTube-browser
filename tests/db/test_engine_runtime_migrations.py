"""Test Engine main/runtime current-shape migration resources."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))

from engine.server.data.video_filters import VideoFilters, build_video_filter_sql  # noqa: E402
from engine.server.db.migrations.apply import apply_main_read_indexes, apply_main_runtime_migrations  # noqa: E402


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




def _create_filterable_videos_table(conn: sqlite3.Connection) -> None:
    """Create the metadata-v1 columns needed by normalized filter indexes."""
    conn.execute(
        """
        CREATE TABLE videos (
          video_id TEXT,
          video_uuid TEXT,
          instance_domain TEXT,
          language TEXT,
          category TEXT
        )
        """
    )


def _query_plan_details(
    conn: sqlite3.Connection, filters: VideoFilters
) -> list[str]:
    """Return SQLite planner details for the production filter predicate."""
    clause, params = build_video_filter_sql("v", filters)
    return [
        str(row[3])
        for row in conn.execute(
            f"EXPLAIN QUERY PLAN SELECT v.video_id FROM videos v WHERE 1=1 {clause}",
            params,
        )
    ]

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
        "idx_videos_instance_normalized",
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


def test_main_read_indexes_are_noop_when_content_tables_are_missing() -> None:
    """Conditional read-index behavior must stay safe for empty databases."""
    conn = _connect()

    apply_main_read_indexes(conn)

    assert _indexes(conn) == set()

def test_main_read_indexes_skip_optional_filter_indexes_without_metadata_columns() -> None:
    """Legacy/minimal video tables must keep usable read indexes without optional metadata."""
    conn = _connect()
    _create_minimal_content_tables(conn)

    apply_main_read_indexes(conn)

    indexes = _indexes(conn)
    assert "idx_videos_instance_normalized" in indexes
    assert "idx_videos_language_normalized" not in indexes
    assert "idx_videos_category_normalized" not in indexes


def test_normalized_filter_indexes_match_production_predicates_and_are_used() -> None:
    """Metadata-v1 filter indexes must match the real normalized WHERE expressions."""
    conn = _connect()
    conn.executescript(
        """
        CREATE TABLE channels (
          channel_id TEXT,
          instance_domain TEXT,
          followers_count INTEGER,
          videos_count INTEGER,
          channel_name TEXT
        );
        CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT);
        """
    )
    _create_filterable_videos_table(conn)
    conn.executemany(
        "INSERT INTO videos(video_id, video_uuid, instance_domain, language, category) VALUES (?, ?, ?, ?, ?)",
        [
            (str(index), str(index), f" Host{index % 50}.Example.org ", None if index % 37 == 0 else (" UK " if index % 11 == 0 else "en"), " Education " if index % 13 == 0 else "Music")
            for index in range(5000)
        ],
    )

    apply_main_read_indexes(conn)
    conn.execute("ANALYZE")

    indexes = _indexes(conn)
    assert {
        "idx_videos_language_normalized",
        "idx_videos_category_normalized",
        "idx_videos_instance_normalized",
    }.issubset(indexes)

    cases = [
        (VideoFilters(language="uk"), "idx_videos_language_normalized"),
        (VideoFilters(language="_unknown"), "idx_videos_language_normalized"),
        (VideoFilters(category="education"), "idx_videos_category_normalized"),
        (VideoFilters(instance="host1.example.org"), "idx_videos_instance_normalized"),
    ]
    for filters, expected_index in cases:
        plan = _query_plan_details(conn, filters)
        assert any(expected_index in detail for detail in plan), (filters, plan)
