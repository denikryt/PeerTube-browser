"""Characterize batched embedding lookup used by recommendation layers."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.embeddings import fetch_embeddings_by_ids, fetch_seed_embeddings_for_likes  # noqa: E402


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE video_embeddings (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          embedding BLOB NOT NULL,
          embedding_dim INTEGER NOT NULL,
          model_name TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        """
    )
    return conn


def _insert_embedding(conn: sqlite3.Connection, video_id: str, instance_domain: str, values: list[float]) -> None:
    vector = np.array(values, dtype=np.float32)
    conn.execute(
        """
        INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name)
        VALUES (?, ?, ?, ?, ?)
        """,
        (video_id, instance_domain, vector.tobytes(), int(vector.shape[0]), "test-model"),
    )


def test_fetch_embeddings_by_ids_uses_video_embedding_identity_without_index_table() -> None:
    """Runtime recommendation scoring should not require video_index_ids for candidate embedding fetches."""
    conn = _connect()
    _insert_embedding(conn, "v1", "example.org", [1.0, 0.0, 0.0])
    _insert_embedding(conn, "v2", "example.org", [0.0, 1.0, 0.0])
    conn.commit()

    result = fetch_embeddings_by_ids(
        conn,
        [
            {"video_id": "v1", "instance_domain": "example.org"},
            {"video_id": "v1", "instance_domain": "example.org"},
            {"video_id": "v2", "instance_domain": "example.org"},
            {"video_id": "missing", "instance_domain": "example.org"},
        ],
    )

    assert sorted(result) == ["v1::example.org", "v2::example.org"]
    np.testing.assert_array_equal(result["v1::example.org"], np.array([1.0, 0.0, 0.0], dtype=np.float32))
    np.testing.assert_array_equal(result["v2::example.org"], np.array([0.0, 1.0, 0.0], dtype=np.float32))


def _connect_seed_lookup() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE videos (
          video_id TEXT NOT NULL,
          video_uuid TEXT,
          instance_domain TEXT NOT NULL,
          channel_id TEXT,
          title TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE INDEX idx_videos_uuid_instance
          ON videos(video_uuid, instance_domain);
        CREATE TABLE video_embeddings (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          embedding BLOB NOT NULL,
          embedding_dim INTEGER NOT NULL,
          model_name TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_index_ids (
          index_id INTEGER PRIMARY KEY AUTOINCREMENT,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 1,
          UNIQUE(video_id, instance_domain)
        );
        """
    )
    return conn


def _insert_seed_video(
    conn: sqlite3.Connection,
    video_id: str,
    video_uuid: str,
    instance_domain: str,
    values: list[float],
    *,
    active: int = 1,
) -> None:
    vector = np.array(values, dtype=np.float32)
    conn.execute(
        """
        INSERT INTO videos(video_id, video_uuid, instance_domain, channel_id, title)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            video_id,
            video_uuid,
            instance_domain,
            f"channel-{video_id}",
            f"Video {video_id}",
        ),
    )
    conn.execute(
        """
        INSERT INTO video_embeddings(
          video_id,
          instance_domain,
          embedding,
          embedding_dim,
          model_name
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (video_id, instance_domain, vector.tobytes(), int(vector.shape[0]), "test-model"),
    )
    conn.execute(
        """
        INSERT INTO video_index_ids(video_id, instance_domain, is_active)
        VALUES (?, ?, ?)
        """,
        (video_id, instance_domain, active),
    )


def test_fetch_seed_embeddings_for_likes_resolves_uuid_and_video_id_pairs() -> None:
    """Recommendation seed lookup must resolve request-sized identity pairs without rowid scans."""
    conn = _connect_seed_lookup()
    _insert_seed_video(conn, "v1", "uuid-1", "example.org", [1.0, 0.0, 0.0])
    _insert_seed_video(conn, "v2", "uuid-2", "example.net", [0.0, 1.0, 0.0])
    _insert_seed_video(
        conn,
        "inactive",
        "uuid-inactive",
        "example.org",
        [0.0, 0.0, 1.0],
        active=0,
    )
    conn.commit()

    result = fetch_seed_embeddings_for_likes(
        conn,
        [
            {"video_uuid": "uuid-1", "instance_domain": "example.org"},
            {"video_id": "v2", "instance_domain": "example.net"},
            {"video_uuid": "uuid-inactive", "instance_domain": "example.org"},
            {"video_uuid": "missing", "instance_domain": "example.org"},
        ],
    )

    assert sorted(result) == [
        "uuid::uuid-1::example.org",
        "uuid::uuid-2::example.net",
        "v1::example.org",
        "v2::example.net",
    ]
    assert result["v1::example.org"]["index_id"] == 1
    assert result["v2::example.net"]["index_id"] == 2
    np.testing.assert_array_equal(
        result["uuid::uuid-1::example.org"]["embedding"],
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )
