"""Behavior tests for the stable index-id synchronization job."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
JOB = ROOT / "engine" / "server" / "db" / "jobs" / "sync-video-index-ids.py"


def _load_job() -> Any:
    """Load the hyphenated sync job module through importlib."""
    spec = importlib.util.spec_from_file_location("sync_video_index_ids_job", JOB)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _db() -> sqlite3.Connection:
    """Create the smallest DB shape the sync job needs."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE videos (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          PRIMARY KEY (video_id, instance_domain)
        );
        CREATE TABLE video_embeddings (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          embedding BLOB,
          embedding_dim INTEGER,
          PRIMARY KEY (video_id, instance_domain)
        );
        """
    )
    return conn


def _add_video(conn: sqlite3.Connection, video_id: str = "v1", host: str = "h1") -> None:
    """Insert one minimal video row."""
    conn.execute("INSERT INTO videos (video_id, instance_domain) VALUES (?, ?)", (video_id, host))


def _add_embedding(conn: sqlite3.Connection, video_id: str = "v1", host: str = "h1") -> None:
    """Insert one minimal embedding row."""
    conn.execute(
        "INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim) VALUES (?, ?, X'0000', 1)",
        (video_id, host),
    )


def test_sync_creates_active_mapping_and_keeps_index_id_on_repeat() -> None:
    """A current video+embedding pair gets exactly one stable index id."""
    job = _load_job()
    conn = _db()
    _add_video(conn)
    _add_embedding(conn)

    first = job.sync_video_index_ids(conn)
    first_id = conn.execute("SELECT index_id FROM video_index_ids").fetchone()[0]
    second = job.sync_video_index_ids(conn)
    second_id = conn.execute("SELECT index_id FROM video_index_ids").fetchone()[0]

    assert first.inserted == 1
    assert second.inserted == 0
    assert first_id == second_id
    assert conn.execute("SELECT is_active FROM video_index_ids").fetchone()[0] == 1


def test_sync_retires_missing_embedding_and_reactivates_same_index_id() -> None:
    """Missing embeddings make mappings inactive without assigning a replacement id later."""
    job = _load_job()
    conn = _db()
    _add_video(conn)
    _add_embedding(conn)
    job.sync_video_index_ids(conn)
    index_id = conn.execute("SELECT index_id FROM video_index_ids").fetchone()[0]

    conn.execute("DELETE FROM video_embeddings")
    job.sync_video_index_ids(conn)
    retired = conn.execute("SELECT is_active, retired_reason FROM video_index_ids").fetchone()

    _add_embedding(conn)
    job.sync_video_index_ids(conn)
    restored = conn.execute("SELECT index_id, is_active, retired_reason FROM video_index_ids").fetchone()

    assert dict(retired) == {"is_active": 0, "retired_reason": "missing_embedding"}
    assert restored["index_id"] == index_id
    assert restored["is_active"] == 1
    assert restored["retired_reason"] is None


def test_sync_retires_missing_video() -> None:
    """A mapping remains historical when its content metadata row disappears."""
    job = _load_job()
    conn = _db()
    _add_video(conn)
    _add_embedding(conn)
    job.sync_video_index_ids(conn)

    conn.execute("DELETE FROM videos")
    job.sync_video_index_ids(conn)

    row = conn.execute("SELECT is_active, retired_reason FROM video_index_ids").fetchone()
    assert dict(row) == {"is_active": 0, "retired_reason": "missing_video"}
