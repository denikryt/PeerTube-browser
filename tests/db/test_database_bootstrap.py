"""Test explicit database bootstrap entrypoints for current SQLite schemas."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "backend"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from client.backend.db.bootstrap import bootstrap_client_users_db  # noqa: E402
from engine.server.db.bootstrap import (  # noqa: E402
    bootstrap_engine_random_cache_db,
    bootstrap_engine_read_indexes,
    bootstrap_engine_runtime_db,
    bootstrap_engine_similarity_cache_db,
)


def _connect() -> sqlite3.Connection:
    """Create a row-aware temporary SQLite connection for bootstrap tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    """Return user-visible table names from SQLite metadata."""
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _indexes(conn: sqlite3.Connection) -> set[str]:
    """Return user-created index names from SQLite metadata."""
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        if not row["name"].startswith("sqlite_autoindex")
    }


def _create_minimal_engine_content_tables(conn: sqlite3.Connection) -> None:
    """Create only columns required by current Engine read-index SQL."""
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


def test_client_users_bootstrap_creates_current_schema() -> None:
    """Client bootstrap must create users, likes, and the current recency index."""
    conn = _connect()

    bootstrap_client_users_db(conn)

    assert {"users", "likes"}.issubset(_tables(conn))
    assert "likes_user_updated_idx" in _indexes(conn)


def test_engine_runtime_bootstrap_creates_runtime_tables_and_noops_missing_read_indexes() -> None:
    """Engine runtime bootstrap must create runtime tables and tolerate no content tables."""
    conn = _connect()

    bootstrap_engine_runtime_db(conn)

    assert {
        "interaction_raw_events",
        "interaction_signals",
        "instance_denylist",
        "channel_moderation",
    }.issubset(_tables(conn))
    assert "idx_videos_uuid_instance" not in _indexes(conn)


def test_engine_read_index_bootstrap_creates_current_indexes_for_existing_content_tables() -> None:
    """Read-index bootstrap must preserve current conditional index creation."""
    conn = _connect()
    _create_minimal_engine_content_tables(conn)

    bootstrap_engine_read_indexes(conn)

    assert {
        "idx_channels_followers_videos_name",
        "idx_channels_videos",
        "idx_channels_name",
        "idx_channels_instance",
        "idx_videos_uuid_instance",
        "idx_videos_id_instance",
        "idx_video_embeddings_id_instance",
    }.issubset(_indexes(conn))


def test_similarity_cache_bootstrap_creates_current_schema() -> None:
    """Similarity-cache bootstrap must create current cache tables and rank index."""
    conn = _connect()

    bootstrap_engine_similarity_cache_db(conn)

    assert {"similarity_sources", "similarity_items"}.issubset(_tables(conn))
    assert "similarity_source_rank_idx" in _indexes(conn)


def test_random_cache_bootstrap_creates_current_schema() -> None:
    """Random-cache bootstrap must create the current random index-id table."""
    conn = _connect()

    bootstrap_engine_random_cache_db(conn)

    assert "random_index_ids" in _tables(conn)
