"""Characterize batched embedding lookup used by recommendation layers."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.embeddings import fetch_embeddings_by_ids  # noqa: E402


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
