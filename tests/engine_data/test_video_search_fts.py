"""Behavior tests for the SQLite FTS5 lightweight video search index."""
from __future__ import annotations

import sqlite3

from engine.server.data.video_search import rebuild_video_search_index, search_videos


def _db() -> sqlite3.Connection:
    """Create the minimal Engine video/channel schema required by search."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE channels (
          channel_id TEXT NOT NULL,
          channel_name TEXT,
          display_name TEXT,
          instance_domain TEXT NOT NULL,
          channel_url TEXT,
          videos_count INTEGER,
          followers_count INTEGER,
          avatar_url TEXT,
          health_status TEXT,
          health_checked_at INTEGER,
          health_error TEXT,
          last_error TEXT,
          last_error_at INTEGER,
          last_error_source TEXT,
          PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE videos (
          video_id TEXT NOT NULL,
          video_uuid TEXT,
          video_numeric_id INTEGER,
          instance_domain TEXT NOT NULL,
          channel_id TEXT,
          channel_name TEXT,
          channel_url TEXT,
          account_name TEXT,
          account_url TEXT,
          title TEXT,
          description TEXT,
          tags_json TEXT,
          category TEXT,
          published_at INTEGER,
          video_url TEXT,
          duration INTEGER,
          thumbnail_url TEXT,
          embed_path TEXT,
          views INTEGER,
          likes INTEGER,
          dislikes INTEGER,
          comments_count INTEGER,
          nsfw INTEGER,
          preview_path TEXT,
          popularity REAL DEFAULT 0,
          invalid_reason TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        """
    )
    conn.execute(
        "INSERT INTO channels(channel_id, channel_name, display_name, instance_domain, followers_count) VALUES (?, ?, ?, ?, ?)",
        ("c1", "linuxchannel", "Linux Lab", "a.example", 10),
    )
    conn.executemany(
        """
        INSERT INTO videos(video_id, video_uuid, instance_domain, channel_id, channel_name, title, description, tags_json, category, published_at, views, likes, comments_count, popularity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("v1", "u1", "a.example", "c1", "linuxchannel", "Linux desktop review", "secretword only here", '["opensource", "fediverse"]', "Technology", 3000, 100, 5, 2, 10),
            ("v2", "u2", "b.example", "c2", "cooking", "Pasta demo", "linux absent", '["food"]', "Cooking", 2000, 20, 1, 0, 1),
        ],
    )
    return conn


def test_rebuild_creates_tables_and_searches_indexed_fields() -> None:
    """Rebuild creates the FTS tables and finds title/channel/tags/category/instance terms."""
    conn = _db()
    try:
        assert rebuild_video_search_index(conn) == {"rows": 2}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'video_search_%'")}
        assert "video_search_docs" in tables
        assert "video_search_fts" in tables
        for query in ("Linux", "Lab", "opensource", "Technology", "a.example"):
            rows, _next = search_videos(conn, query=query, limit=10, offset=0)
            assert rows[0]["video_id"] == "v1"
            assert rows[0]["instance_domain"] == "a.example"
    finally:
        conn.close()


def test_description_only_terms_are_not_indexed_and_rebuild_is_idempotent() -> None:
    """Search v1 excludes descriptions and repeated rebuilds preserve one doc per video."""
    conn = _db()
    try:
        rebuild_video_search_index(conn)
        rebuild_video_search_index(conn)
        assert conn.execute("SELECT COUNT(*) FROM video_search_docs").fetchone()[0] == 2
        rows, next_offset = search_videos(conn, query="secretword", limit=10, offset=0)
        assert rows == []
        assert next_offset is None
    finally:
        conn.close()


def test_malformed_query_is_safe() -> None:
    """Punctuation-only user text never reaches SQLite as invalid FTS syntax."""
    conn = _db()
    try:
        rebuild_video_search_index(conn)
        assert search_videos(conn, query='""():', limit=10, offset=0) == ([], None)
    finally:
        conn.close()
