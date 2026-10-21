"""Characterize Engine similarity candidate row-building behavior."""
from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.similarity_candidates import SimilarityCandidatesPolicy, get_similar_candidates  # noqa: E402


def _connect() -> sqlite3.Connection:
    """Create the minimal metadata schema used by similarity candidate tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE channels (
          channel_id TEXT,
          instance_domain TEXT,
          display_name TEXT,
          avatar_url TEXT,
          PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE videos (
          video_id TEXT,
          video_uuid TEXT,
          video_numeric_id INTEGER,
          instance_domain TEXT,
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
          last_checked_at INTEGER,
          error_count INTEGER DEFAULT 0,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_embeddings (
          video_id TEXT,
          instance_domain TEXT,
          embedding_dim INTEGER,
          model_name TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        """
    )
    return conn


def _insert_video(conn: sqlite3.Connection, video_id: str, channel_id: str, title: str) -> None:
    """Insert one metadata row and its embedding marker."""
    conn.execute(
        "INSERT OR IGNORE INTO channels VALUES (?, ?, ?, ?)",
        (channel_id, "example.org", f"Channel {channel_id}", f"/{channel_id}.png"),
    )
    conn.execute(
        """
        INSERT INTO videos (
          video_id, video_uuid, video_numeric_id, instance_domain, channel_id, channel_name,
          channel_url, account_name, account_url, title, description, tags_json, category,
          published_at, video_url, duration, thumbnail_url, embed_path, views, likes, dislikes,
          comments_count, nsfw, preview_path, last_checked_at, error_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            video_id,
            f"uuid-{video_id}",
            int(video_id.strip("v") or 0),
            "example.org",
            channel_id,
            channel_id,
            f"https://example.org/c/{channel_id}",
            channel_id,
            f"https://example.org/a/{channel_id}",
            title,
            "description",
            "[]",
            "category",
            1000,
            f"https://example.org/w/uuid-{video_id}",
            60,
            "/thumb.jpg",
            "/embed",
            10,
            1,
            0,
            0,
            0,
            "/preview.jpg",
            1000,
            0,
        ),
    )
    conn.execute("INSERT INTO video_embeddings VALUES (?, ?, ?, ?)", (video_id, "example.org", 3, "test"))
    conn.commit()


def _server(conn: sqlite3.Connection) -> SimpleNamespace:
    """Build the subset of Engine server state required by candidate resolution."""
    return SimpleNamespace(
        db=conn,
        db_lock=threading.RLock(),
        similarity_db=None,
        similarity_db_lock=threading.RLock(),
        video_error_threshold=2,
        similarity_max_per_author=1,
        similarity_exclude_source_author=True,
    )


def test_similarity_candidates_exclude_seed_source_author_apply_author_cap_and_preserve_score() -> None:
    """Resolved candidates must keep current filtering and score mapping behavior."""
    conn = _connect()
    for video_id, channel_id in [("v1", "source"), ("v2", "source"), ("v3", "other"), ("v4", "other"), ("v5", "third")]:
        _insert_video(conn, video_id, channel_id, f"Video {video_id}")
    server = _server(conn)
    server.compute_similar_items = lambda _server, _seed, _limit: [
        {"video_id": "v1", "instance_domain": "example.org", "score": 0.99},
        {"video_id": "v2", "instance_domain": "example.org", "score": 0.98},
        {"video_id": "v3", "instance_domain": "example.org", "score": 0.70},
        {"video_id": "v4", "instance_domain": "example.org", "score": 0.60},
        {"video_id": "v5", "instance_domain": "example.org", "score": 0.50},
    ]
    seed = {"video_id": "v1", "instance_domain": "example.org", "channel_id": "source", "embedding": [1, 0, 0]}

    rows = get_similar_candidates(server, seed, 10, SimilarityCandidatesPolicy(use_cache=False, allow_cache_write=False))

    assert [(row["video_id"], row["score"]) for row in rows] == [("v3", 0.70), ("v5", 0.50)]
    assert all(row["channel_id"] != "source" for row in rows)
