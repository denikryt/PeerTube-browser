"""Planner regressions for the production-shaped Discovery SQL hot paths.

These tests exercise the real provider functions, capture the SQL they execute,
and run ``EXPLAIN QUERY PLAN`` against the same statement and bound parameters.
They protect both sides of the optimization contract: the intended index lookup
must be visible and the old temp-sort/JSON-expansion hot paths must stay absent.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.random_videos import fetch_fresh_page, fetch_popular_page  # noqa: E402
from data.serving_moderation import ServingVisibility  # noqa: E402
from data.video_filters import VideoFilters  # noqa: E402
from engine.server.db.migrations.apply import apply_main_read_indexes  # noqa: E402


class _RecordingConnection(sqlite3.Connection):
    """Record the last production Discovery provider statement and parameters."""

    provider_statement: tuple[str, list[object]] | None = None

    def execute(self, sql: str, parameters=(), /):  # type: ignore[override]
        """Capture provider SQL while preserving normal sqlite3 execution."""
        if "WITH eligible AS" in sql:
            self.provider_statement = (sql, list(parameters))
        return super().execute(sql, parameters)


def _conn() -> _RecordingConnection:
    """Create a production-shaped canonical DB with current read indexes and data."""
    conn = sqlite3.connect(":memory:", factory=_RecordingConnection)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE channels (
          channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT,
          followers_count INTEGER, videos_count INTEGER, channel_name TEXT,
          PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE instance_denylist (host TEXT PRIMARY KEY, is_active INTEGER);
        CREATE TABLE channel_moderation (
          channel_id TEXT, instance_domain TEXT, status TEXT,
          PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT);
        CREATE TABLE videos (
          video_id TEXT, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT,
          channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT,
          account_url TEXT, title TEXT, description TEXT, tags_json TEXT, category TEXT,
          category_id TEXT, language TEXT, language_label TEXT, published_at INTEGER,
          video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER,
          likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER,
          preview_path TEXT, popularity REAL, last_checked_at INTEGER,
          error_count INTEGER DEFAULT 0, invalid_reason TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_tags (
          tag TEXT NOT NULL,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          PRIMARY KEY(tag, video_id, instance_domain)
        ) WITHOUT ROWID;
        """
    )
    conn.execute("ALTER TABLE videos ADD COLUMN thumbnail_candidates_json TEXT")
    apply_main_read_indexes(conn)
    conn.executemany(
        """
        INSERT INTO videos(
          video_id, video_uuid, instance_domain, channel_id, channel_name, title,
          tags_json, category, language, published_at, popularity, error_count, invalid_reason
        ) VALUES (?, ?, 'example.org', 'channel', 'Channel', ?, '[]', 'Education', 'en', ?, ?, 0, NULL)
        """,
        [
            (
                f"v{index:05d}",
                f"uuid-{index}",
                f"Title {index}",
                None if index % 10 == 0 else index,
                float(index % 100),
            )
            for index in range(5000)
        ],
    )
    conn.execute(
        "INSERT INTO video_tags(tag,video_id,instance_domain) VALUES ('linux','v00050','example.org')"
    )
    conn.commit()
    # Give SQLite production-like statistics before asserting plan shape.
    conn.execute("ANALYZE")
    return conn


def _plan_after_provider_call(conn: _RecordingConnection) -> list[str]:
    """Explain the exact provider statement captured from the production function."""
    assert conn.provider_statement is not None
    sql, params = conn.provider_statement
    rows = sqlite3.Connection.execute(conn, "EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return [str(row[3]) for row in rows]


def _visibility_without_policy_subqueries() -> ServingVisibility:
    """Keep the planner test focused on ordering/tag access rather than moderation indexes."""
    return ServingVisibility(
        error_threshold=None,
        apply_instance_filter=False,
        apply_channel_filter=False,
    )


def test_fresh_provider_uses_exact_order_index_without_temp_sort() -> None:
    """Positive/negative: Fresh walks its exact index and does not materialize ORDER BY."""
    conn = _conn()

    fetch_fresh_page(
        conn,
        limit_plus_one=21,
        filters=VideoFilters(),
        visibility=_visibility_without_policy_subqueries(),
        after={
            "published_is_null": 0,
            "published_sort": 2500,
            "instance_domain": "example.org",
            "video_id": "v02500",
        },
    )
    plan = _plan_after_provider_call(conn)

    assert any("USING INDEX idx_videos_fresh_order" in detail for detail in plan), plan
    assert not any("TEMP B-TREE" in detail.upper() for detail in plan), plan


def test_trending_provider_uses_exact_order_index_without_temp_sort() -> None:
    """Positive/negative: Trending walks the popularity tuple index without a global sort."""
    conn = _conn()

    fetch_popular_page(
        conn,
        limit_plus_one=21,
        filters=VideoFilters(),
        visibility=_visibility_without_policy_subqueries(),
        after={
            "popularity": 50.0,
            "instance_domain": "example.org",
            "video_id": "v02500",
        },
    )
    plan = _plan_after_provider_call(conn)

    assert any("USING INDEX idx_videos_trending_order" in detail for detail in plan), plan
    assert not any("TEMP B-TREE" in detail.upper() for detail in plan), plan


def test_tag_filter_uses_video_tags_primary_key_without_runtime_json_expansion() -> None:
    """Positive/negative: request-time tag membership is an indexed relation lookup, not JSON scan."""
    conn = _conn()

    fetch_popular_page(
        conn,
        limit_plus_one=21,
        filters=VideoFilters(tag="linux"),
        visibility=_visibility_without_policy_subqueries(),
    )
    plan = _plan_after_provider_call(conn)
    assert conn.provider_statement is not None
    sql, _ = conn.provider_statement

    assert any(
        "SEARCH vt USING PRIMARY KEY (tag=? AND video_id=? AND instance_domain=?)" in detail
        for detail in plan
    ), plan
    assert "json_each" not in sql.lower()
    assert not any("SCAN vt" in detail for detail in plan), plan
