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
          category_id TEXT,
          language TEXT,
          language_label TEXT,
          published_at INTEGER,
          video_url TEXT,
          duration INTEGER,
          thumbnail_url TEXT,
          thumbnail_candidates_json TEXT,
          embed_path TEXT,
          views INTEGER,
          likes INTEGER,
          dislikes INTEGER,
          comments_count INTEGER,
          nsfw INTEGER,
          preview_path TEXT,
          popularity REAL DEFAULT 0,
          invalid_reason TEXT,
          error_count INTEGER,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE instance_denylist (host TEXT PRIMARY KEY, is_active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE channel_moderation (channel_id TEXT, instance_domain TEXT, status TEXT, PRIMARY KEY(channel_id, instance_domain));
        """
    )
    conn.execute(
        "INSERT INTO channels(channel_id, channel_name, display_name, instance_domain, followers_count) VALUES (?, ?, ?, ?, ?)",
        ("c1", "linuxchannel", "Linux Lab", "a.example", 10),
    )
    conn.executemany(
        """
        INSERT INTO videos(video_id, video_uuid, instance_domain, channel_id, channel_name, title, description, tags_json, category, published_at, thumbnail_url, thumbnail_candidates_json, views, likes, comments_count, popularity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("v1", "u1", "a.example", "c1", "linuxchannel", "Linux desktop review", "secretword only here", '["opensource", "fediverse"]', "Technology", 3000, "/legacy.jpg", '[{"url":"https://cdn.example/linux-large.jpg","width":850,"height":480},{"url":"https://cdn.example/linux-small.jpg","width":280,"height":157}]', 100, 5, 2, 10),
            ("v2", "u2", "b.example", "c2", "cooking", "Pasta demo", "linux absent", '["food"]', "Cooking", 2000, "/legacy2.jpg", None, 20, 1, 0, 1),
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
            assert rows[0]["thumbnail_urls"] == [
                "https://cdn.example/linux-large.jpg",
                "https://cdn.example/linux-small.jpg",
            ]
            assert "thumbnail_candidates_json" not in rows[0]
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


def test_filter_and_visibility_apply_before_search_page_cut() -> None:
    """A hidden/non-matching top hit cannot consume a filtered search page slot."""
    from engine.server.data.video_filters import VideoFilters

    conn = _db()
    try:
        conn.execute("UPDATE videos SET language = 'en' WHERE video_id = 'v1'")
        conn.execute("UPDATE videos SET title = 'Linux second', language = 'uk', category_id = '3' WHERE video_id = 'v2'")
        rebuild_video_search_index(conn)
        rows, next_offset = search_videos(
            conn,
            query="linux",
            limit=1,
            offset=0,
            filters=VideoFilters(language="uk"),
        )
        assert [row["video_id"] for row in rows] == ["v2"]
        assert rows[0]["language"] == "uk"
        assert rows[0]["category_id"] == "3"
        assert next_offset is None
    finally:
        conn.close()


def test_search_filter_no_match_is_empty_not_error() -> None:
    """A valid but unmatched filter returns an ordinary terminal empty page."""
    from engine.server.data.video_filters import VideoFilters

    conn = _db()
    try:
        rebuild_video_search_index(conn)
        assert search_videos(conn, query="linux", limit=5, offset=0, filters=VideoFilters(language="uk")) == ([], None)
    finally:
        conn.close()
