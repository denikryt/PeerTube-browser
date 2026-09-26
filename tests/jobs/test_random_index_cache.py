"""Behavior tests for random cache storage based on stable index ids."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.random_cache import fetch_random_index_ids, populate_random_cache  # noqa: E402
from engine.server.db.bootstrap import bootstrap_engine_random_cache_db  # noqa: E402
from engine.server.db.migrations.apply import apply_video_index_ids_migration  # noqa: E402


def _source_db() -> sqlite3.Connection:
    """Create a minimal source DB with active and inactive mappings."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE videos (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          channel_id TEXT,
          PRIMARY KEY (video_id, instance_domain)
        );
        CREATE TABLE video_embeddings (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          PRIMARY KEY (video_id, instance_domain)
        );
        """
    )
    apply_video_index_ids_migration(conn)
    for idx, active in [(101, 1), (102, 1), (103, 0)]:
        video_id = f"v{idx}"
        conn.execute("INSERT INTO videos VALUES (?, ?, ?)", (video_id, "h1", f"c{idx}"))
        conn.execute("INSERT INTO video_embeddings VALUES (?, ?)", (video_id, "h1"))
        conn.execute(
            """
            INSERT INTO video_index_ids (index_id, video_id, instance_domain, is_active, created_at, updated_at)
            VALUES (?, ?, 'h1', ?, 1, 1)
            """,
            (idx, video_id, active),
        )
    return conn


def test_random_cache_writes_and_reads_index_ids_only() -> None:
    """Random cache must not store SQLite embedding rowids after the migration."""
    src = _source_db()
    cache = sqlite3.connect(":memory:")
    cache.row_factory = sqlite3.Row
    bootstrap_engine_random_cache_db(cache)

    count = populate_random_cache(src, cache, 10)
    ids = sorted(fetch_random_index_ids(cache, 10))
    tables = {row[0] for row in cache.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert count == 2
    assert ids == [101, 102]
    assert "random_index_ids" in tables
    assert "random_rowids" not in tables
