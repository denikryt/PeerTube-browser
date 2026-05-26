"""Compare legacy ensure wrappers with Stage 6 current-shape migrations."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "backend"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.channels import ensure_channels_indexes  # noqa: E402
from data.interaction_events import ensure_interaction_event_schema  # noqa: E402
from data.moderation import ensure_moderation_schema  # noqa: E402
from data.random_cache import ensure_random_cache_schema  # noqa: E402
from data.similarity_cache import ensure_similarity_schema  # noqa: E402
from data.videos import ensure_video_indexes  # noqa: E402
from lib.users_store import ensure_user_schema  # noqa: E402

from client.backend.db.migrate import apply_client_user_migrations  # type: ignore  # noqa: E402
from engine.server.db.migrations.apply import (  # noqa: E402
    apply_main_runtime_migrations,
    apply_random_cache_migrations,
    apply_similarity_cache_migrations,
)


def _connect() -> sqlite3.Connection:
    """Create a row-aware in-memory database for schema comparison tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _create_content_tables(conn: sqlite3.Connection) -> None:
    """Create minimal Engine content tables for conditional read-index tests."""
    conn.executescript(
        """
        CREATE TABLE channels (
          channel_id TEXT,
          instance_domain TEXT,
          followers_count INTEGER,
          videos_count INTEGER,
          channel_name TEXT
        );
        CREATE TABLE videos (video_id TEXT, video_uuid TEXT, instance_domain TEXT);
        CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT);
        """
    )


def _signature(conn: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    """Return a stable schema signature without comparing raw SQLite SQL text."""
    rows: list[tuple[object, ...]] = []
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    for table in tables:
        rows.append(("table", table))
        for column in conn.execute(f"PRAGMA table_info({table})"):
            rows.append(("column", table, column[1], column[2], column[3], column[4], column[5]))
    indexes = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        )
        if not row[0].startswith("sqlite_autoindex")
    ]
    for index in indexes:
        rows.append(("index", index))
    return tuple(rows)


def test_client_user_wrapper_and_migration_have_same_schema_signature() -> None:
    """Client startup wrapper and migration resources must remain equivalent."""
    wrapper = _connect()
    migration = _connect()

    ensure_user_schema(wrapper)
    apply_client_user_migrations(migration)

    assert _signature(wrapper) == _signature(migration)


def test_engine_runtime_wrappers_and_migrations_have_same_schema_signature() -> None:
    """Engine runtime wrappers must keep matching current-shape migrations."""
    wrapper = _connect()
    migration = _connect()
    _create_content_tables(wrapper)
    _create_content_tables(migration)

    ensure_interaction_event_schema(wrapper)
    ensure_moderation_schema(wrapper)
    ensure_channels_indexes(wrapper)
    ensure_video_indexes(wrapper)
    apply_main_runtime_migrations(migration)

    assert _signature(wrapper) == _signature(migration)


def test_engine_cache_wrappers_and_migrations_have_same_schema_signature() -> None:
    """Cache wrappers and migration resources must keep equivalent schemas."""
    similarity_wrapper = _connect()
    similarity_migration = _connect()
    random_wrapper = _connect()
    random_migration = _connect()

    ensure_similarity_schema(similarity_wrapper)
    apply_similarity_cache_migrations(similarity_migration)
    ensure_random_cache_schema(random_wrapper)
    apply_random_cache_migrations(random_migration)

    assert _signature(similarity_wrapper) == _signature(similarity_migration)
    assert _signature(random_wrapper) == _signature(random_migration)
