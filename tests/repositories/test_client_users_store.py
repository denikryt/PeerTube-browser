"""Characterize Client-owned user and like persistence behavior."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "backend"))

from lib import users_store  # noqa: E402


def _connect() -> sqlite3.Connection:
    """Create a row-aware in-memory database for users_store tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_ensure_user_schema_creates_users_likes_and_updated_index() -> None:
    """Schema creation must preserve the Client profile storage contract."""
    conn = _connect()
    users_store.ensure_user_schema(conn)

    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    indexes = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }

    assert {"users", "likes"}.issubset(tables)
    assert "likes_user_updated_idx" in indexes


def test_record_like_is_idempotent_for_user_video_instance_key() -> None:
    """Repeating the same like must update recency instead of duplicating rows."""
    conn = _connect()
    users_store.ensure_user_schema(conn)
    video = {"video_id": "123", "video_uuid": "uuid-123", "instance_domain": "example.org"}

    users_store.record_like(conn, "local-user", "like", video, max_likes=100)
    users_store.record_like(conn, "local-user", "like", video, max_likes=100)

    count = conn.execute("SELECT COUNT(*) FROM likes WHERE user_id = ?", ("local-user",)).fetchone()[0]
    assert count == 1


def test_fetch_recent_likes_orders_by_updated_at_and_applies_limit(monkeypatch) -> None:
    """Recent likes must expose newest-first lightweight identities for Engine metadata lookup."""
    conn = _connect()
    users_store.ensure_user_schema(conn)
    timestamps = iter([100, 1000, 2000, 3000, 4000, 5000])
    monkeypatch.setattr(users_store, "now_ms", lambda: next(timestamps))

    for video_id in ["1", "2", "3"]:
        users_store.record_like(
            conn,
            "local-user",
            "like",
            {"video_id": video_id, "video_uuid": f"uuid-{video_id}", "instance_domain": "example.org"},
            max_likes=100,
        )

    rows = users_store.fetch_recent_likes(conn, "local-user", limit=2)

    assert [row["video_id"] for row in rows] == ["3", "2"]
    assert set(rows[0]) == {"video_id", "video_uuid", "instance_domain", "updated_at"}


def test_remove_like_deletes_only_the_canonical_identity() -> None:
    """Unliking a video must remove the stored row by user/video/instance identity."""
    conn = _connect()
    users_store.ensure_user_schema(conn)
    users_store.record_like(
        conn,
        "local-user",
        "like",
        {"video_id": "123", "video_uuid": "uuid-123", "instance_domain": "example.org"},
        max_likes=100,
    )

    users_store.remove_like(conn, "local-user", "123", "example.org")

    count = conn.execute("SELECT COUNT(*) FROM likes").fetchone()[0]
    assert count == 0
