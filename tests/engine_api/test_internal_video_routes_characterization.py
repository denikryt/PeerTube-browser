"""Characterize Engine internal video route adapters through FastAPI."""
from __future__ import annotations

import sqlite3
import threading

import numpy as np
from app import create_app
from conftest import make_engine_state
from fastapi.testclient import TestClient


def _connect_internal_video_db() -> sqlite3.Connection:
    """Create the minimal schema used by internal video read handlers."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE channels (
          channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT,
          PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE videos (
          video_id TEXT, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT,
          channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT,
          title TEXT, description TEXT, tags_json TEXT, category TEXT, published_at INTEGER,
          video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER,
          likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER, preview_path TEXT,
          last_checked_at INTEGER, error_count INTEGER DEFAULT 0,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_embeddings (
          video_id TEXT, instance_domain TEXT, embedding BLOB,
          embedding_dim INTEGER, model_name TEXT
        );
        """
    )
    conn.execute("INSERT INTO channels VALUES ('c1', 'example.org', 'Channel', '/avatar.png')")
    conn.execute(
        """
        INSERT INTO videos VALUES (
          '123', 'uuid-123', 123, 'example.org', 'c1', 'chan', 'https://example.org/c/chan',
          'acct', 'https://example.org/a/acct', 'Title', 'Desc', '[]', 'Cat', 1000,
          'https://example.org/w/uuid-123', 60, '/thumb.jpg', '/embed/123', 10, 1, 0, 2,
          0, '/preview.jpg', 1000, 0
        )
        """
    )
    embedding = np.array([1.0, 0.0], dtype=np.float32).tobytes()
    conn.execute(
        "INSERT INTO video_embeddings VALUES ('123', 'example.org', ?, 2, 'test')",
        (embedding,),
    )
    conn.commit()
    return conn


def _client_with_internal_video_db() -> tuple[TestClient, sqlite3.Connection]:
    """Build a FastAPI client backed by the internal-video fixture DB."""
    conn = _connect_internal_video_db()
    state = make_engine_state(db=conn, db_lock=threading.RLock(), video_error_threshold=2)
    return TestClient(create_app(state)), conn


def test_internal_video_resolve_route_preserves_missing_identity_error() -> None:
    """Route dispatch must preserve missing identity errors for internal resolve."""
    client, conn = _client_with_internal_video_db()
    try:
        response = client.post("/internal/videos/resolve", json={})
    finally:
        conn.close()

    assert response.status_code == 400
    assert response.json() == {"error": "Missing video_id or uuid"}


def test_internal_video_resolve_route_preserves_success_shape() -> None:
    """Route dispatch must delegate to the existing identity resolver."""
    client, conn = _client_with_internal_video_db()
    try:
        response = client.post(
            "/internal/videos/resolve",
            json={"uuid": "uuid-123", "host": "example.org"},
        )
    finally:
        conn.close()

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["video"] == {
        "video_id": "123",
        "video_uuid": "uuid-123",
        "instance_domain": "example.org",
        "channel_id": "c1",
        "title": "Title",
    }


def test_internal_videos_metadata_route_preserves_missing_and_empty_entries() -> None:
    """Metadata route must keep current missing-entry and empty-valid-entry behavior."""
    client, conn = _client_with_internal_video_db()
    try:
        missing = client.post("/internal/videos/metadata", json={})
        empty = client.post("/internal/videos/metadata", json={"entries": ["bad", {}]})
    finally:
        conn.close()

    assert missing.status_code == 400
    assert missing.json() == {"error": "Missing entries"}
    assert empty.status_code == 200
    assert empty.json() == {"ok": True, "count": 0, "rows": []}


def test_internal_videos_metadata_route_preserves_success_shape() -> None:
    """Metadata route must return rows from the current metadata reader."""
    client, conn = _client_with_internal_video_db()
    try:
        response = client.post(
            "/internal/videos/metadata",
            json={"entries": [{"video_id": "123", "instance_domain": "example.org"}]},
        )
    finally:
        conn.close()

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["count"] == 1
    assert body["rows"][0]["video_id"] == "123"
    assert body["rows"][0]["title"] == "Title"
