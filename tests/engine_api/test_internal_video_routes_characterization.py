"""Characterize Engine internal video route adapters."""
from __future__ import annotations

import sqlite3
import threading
from types import SimpleNamespace

import numpy as np
from conftest import RouteCapturingHandler, import_similar_handler_module


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


def test_internal_video_resolve_route_preserves_missing_identity_error(monkeypatch) -> None:
    """Route dispatch must preserve missing identity errors for internal resolve."""
    similar = import_similar_handler_module(monkeypatch)
    server = SimpleNamespace(
        rate_limiter=None, db=_connect_internal_video_db(), db_lock=threading.RLock()
    )
    handler = RouteCapturingHandler(
        "/internal/videos/resolve", method="POST", body={}, server=server
    )

    similar.SimilarHandler.do_POST(handler)

    assert handler.status == 400
    assert handler.parsed_body() == {"error": "Missing video_id or uuid"}
    server.db.close()


def test_internal_video_resolve_route_preserves_success_shape(monkeypatch) -> None:
    """Route dispatch must delegate to the existing identity resolver."""
    similar = import_similar_handler_module(monkeypatch)
    server = SimpleNamespace(
        rate_limiter=None, db=_connect_internal_video_db(), db_lock=threading.RLock()
    )
    handler = RouteCapturingHandler(
        "/internal/videos/resolve",
        method="POST",
        body={"uuid": "uuid-123", "host": "example.org"},
        server=server,
    )

    similar.SimilarHandler.do_POST(handler)
    body = handler.parsed_body()

    assert handler.status == 200
    assert body["ok"] is True
    assert body["video"] == {
        "video_id": "123",
        "video_uuid": "uuid-123",
        "instance_domain": "example.org",
        "channel_id": "c1",
        "title": "Title",
    }
    server.db.close()


def test_internal_videos_metadata_route_preserves_missing_and_empty_entries(monkeypatch) -> None:
    """Metadata route must keep current missing-entry and empty-valid-entry behavior."""
    similar = import_similar_handler_module(monkeypatch)
    server = SimpleNamespace(
        rate_limiter=None, db=_connect_internal_video_db(), db_lock=threading.RLock()
    )

    missing = RouteCapturingHandler(
        "/internal/videos/metadata", method="POST", body={}, server=server
    )
    similar.SimilarHandler.do_POST(missing)
    assert missing.status == 400
    assert missing.parsed_body() == {"error": "Missing entries"}

    empty = RouteCapturingHandler(
        "/internal/videos/metadata", method="POST", body={"entries": ["bad", {}]}, server=server
    )
    similar.SimilarHandler.do_POST(empty)
    assert empty.status == 200
    assert empty.parsed_body() == {"ok": True, "count": 0, "rows": []}
    server.db.close()


def test_internal_videos_metadata_route_preserves_success_shape(monkeypatch) -> None:
    """Metadata route must return rows from the current metadata reader."""
    similar = import_similar_handler_module(monkeypatch)
    server = SimpleNamespace(
        rate_limiter=None,
        db=_connect_internal_video_db(),
        db_lock=threading.RLock(),
        video_error_threshold=2,
    )
    handler = RouteCapturingHandler(
        "/internal/videos/metadata",
        method="POST",
        body={"entries": [{"video_id": "123", "instance_domain": "example.org"}]},
        server=server,
    )

    similar.SimilarHandler.do_POST(handler)
    body = handler.parsed_body()

    assert handler.status == 200
    assert body["ok"] is True
    assert body["count"] == 1
    assert body["rows"][0]["video_id"] == "123"
    assert body["rows"][0]["title"] == "Title"
    server.db.close()
