"""Characterize random, recent, and popular Engine fallback feed queries."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.popularity import compute_popularity  # noqa: E402
from data.random_videos import fetch_popular_videos, fetch_random_rows, fetch_recent_videos  # noqa: E402


def _connect() -> sqlite3.Connection:
    """Create the minimal fallback-feed schema used by data query tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT, PRIMARY KEY(channel_id, instance_domain));
        CREATE TABLE interaction_signals (video_uuid TEXT, instance_domain TEXT, likes_count INTEGER DEFAULT 0, undo_likes_count INTEGER DEFAULT 0, signal_score REAL DEFAULT 0, PRIMARY KEY(video_uuid, instance_domain));
        CREATE TABLE videos (
          video_id TEXT, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT, channel_id TEXT,
          channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT,
          tags_json TEXT, category TEXT, published_at INTEGER, video_url TEXT, duration INTEGER, thumbnail_url TEXT,
          embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER,
          preview_path TEXT, popularity REAL, last_checked_at INTEGER, error_count INTEGER DEFAULT 0,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY(video_id, instance_domain));
        """
    )
    for video_id, published, views, likes, popularity, error_count in [
        ("old", 1000, 10, 1, 1.0, 0),
        ("new", 3000, 20, 2, 2.0, 0),
        ("bad", 4000, 999, 99, 999.0, 5),
        ("popular", 2000, 100, 20, 50.0, 0),
    ]:
        conn.execute("INSERT OR IGNORE INTO channels VALUES ('c', 'example.org', 'Channel', '/avatar.png')")
        conn.execute(
            """
            INSERT INTO videos VALUES (?, ?, ?, 'example.org', 'c', 'c', 'https://example.org/c/c', 'acct',
            'https://example.org/a/acct', ?, 'desc', '[]', 'cat', ?, 'https://example.org/w/x', 60,
            '/thumb.jpg', '/embed', ?, ?, 0, 0, 0, '/preview.jpg', ?, 1000, ?)
            """,
            (video_id, f"uuid-{video_id}", len(video_id), f"Title {video_id}", published, views, likes, popularity, error_count),
        )
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'example.org', 3, 'test')", (video_id,))
    conn.commit()
    return conn


def test_recent_videos_are_newest_first_and_exclude_over_threshold_errors() -> None:
    """Recent fallback should prefer newest usable rows and respect limit."""
    rows = fetch_recent_videos(_connect(), limit=2, error_threshold=2)

    assert [row["video_id"] for row in rows] == ["new", "popular"]


def test_popular_videos_use_current_popularity_order_and_error_filter() -> None:
    """Popular fallback should order by popularity while excluding unusable rows."""
    rows = fetch_popular_videos(_connect(), limit=2, error_threshold=2)

    assert [row["video_id"] for row in rows] == ["popular", "new"]


def test_random_rows_return_usable_unique_rows_with_limit() -> None:
    """Random fallback should respect limit and filter high-error rows."""
    rows = fetch_random_rows(_connect(), limit=3, error_threshold=2)

    ids = [row["video_id"] for row in rows]
    assert len(ids) == 3
    assert "bad" not in ids
    assert len(set(ids)) == len(ids)


def test_compute_popularity_combines_views_likes_and_age_decay() -> None:
    """The shared popularity score formula is a product ranking invariant."""
    score = compute_popularity(views=100, likes=10, published_at=1_000_000, like_weight=2.0, now_ms_value=1_000_000 + 30 * 86_400_000)

    assert score == 60.0
