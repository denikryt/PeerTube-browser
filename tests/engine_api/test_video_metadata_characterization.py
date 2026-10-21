"""Characterize Engine video metadata lookup and dynamic merge behavior."""
from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from handlers import video as video_handler  # noqa: E402


def _connect() -> sqlite3.Connection:
    """Create a minimal DB for video endpoint helper tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE channels (
          channel_id TEXT, instance_domain TEXT, channel_name TEXT, display_name TEXT,
          followers_count INTEGER, avatar_url TEXT, PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE instances (
          host TEXT PRIMARY KEY, last_error TEXT, last_error_at INTEGER, last_error_source TEXT
        );
        CREATE TABLE videos (
          video_id TEXT, video_uuid TEXT, instance_domain TEXT, channel_id TEXT, channel_name TEXT,
          channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, embed_path TEXT,
          published_at INTEGER, video_url TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, tags_json TEXT,
          category TEXT, nsfw INTEGER, thumbnail_url TEXT, thumbnail_candidates_json TEXT, preview_path TEXT,
          last_checked_at INTEGER, error_count INTEGER DEFAULT 0, popularity REAL DEFAULT 0,
          PRIMARY KEY(video_id, instance_domain)
        );
        """
    )
    conn.execute("INSERT INTO channels VALUES ('c1', 'example.org', 'slug', 'DB Channel', 10, '/avatar-db.png')")
    conn.execute("INSERT INTO instances(host) VALUES ('example.org')")
    conn.execute(
        """
        INSERT INTO videos VALUES (
          '123', 'uuid-123', 'example.org', 'c1', 'slug', 'https://example.org/video-channels/slug',
          'acct', 'https://example.org/accounts/acct', 'DB Title', 'DB description', '/embed/123',
          1000, 'https://example.org/w/uuid-123', 10, 1, 0, '["db"]', 'DB Category', 0,
          'https://example.org/thumb-large.jpg',
          '[{"url":"https://example.org/thumb-large.jpg","width":850,"height":480},{"url":"https://example.org/thumb-small.jpg","width":280,"height":157}]',
          '/lazy-static/previews/db.jpg', 1000, 0, 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO videos VALUES (
          'bad', 'uuid-bad', 'example.org', 'c1', 'slug', 'https://example.org/video-channels/slug',
          'acct', 'https://example.org/accounts/acct', 'Bad', 'Bad', '/embed/bad',
          1000, 'https://example.org/w/uuid-bad', 10, 1, 0, '["db"]', 'DB Category', 0,
          'https://example.org/bad.jpg', NULL, '/lazy-static/previews/bad.jpg', 1000, 5, 0
        )
        """
    )
    conn.commit()
    return conn


def test_fetch_video_row_resolves_by_id_or_uuid_and_host_and_filters_error_threshold() -> None:
    """Lookup helper must preserve current id/uuid/host and error threshold behavior."""
    conn = _connect()

    by_id = video_handler.fetch_video_row(conn, "123", "example.org", error_threshold=2)
    by_uuid = video_handler.fetch_video_row(conn, "uuid-123", "example.org", error_threshold=2)
    wrong_host = video_handler.fetch_video_row(conn, "123", "other.org", error_threshold=2)
    over_threshold = video_handler.fetch_video_row(conn, "bad", "example.org", error_threshold=2)

    assert by_id["title"] == "DB Title"
    assert by_uuid["video_id"] == "123"
    assert wrong_host is None
    assert over_threshold is None


def test_dynamic_video_metadata_overrides_db_fields_and_uses_db_fallbacks(monkeypatch) -> None:
    """Video response should merge live instance metadata over DB fallback fields."""
    conn = _connect()
    server = SimpleNamespace(db=conn, db_lock=threading.RLock(), video_error_threshold=2)
    monkeypatch.setattr(
        video_handler,
        "fetch_instance_video_dynamic",
        lambda _host, _video_id: {
            "title": "Dynamic Title",
            "views": 99,
            "likes": 7,
            "channel_display": "Dynamic Channel",
            "tags_json": '["dynamic"]',
            "nsfw": 1,
        },
    )

    result = video_handler.handle_video_request(server, {"id": ["123"], "host": ["example.org"]})
    body = result.payload

    assert result.status == 200
    assert body["title"] == "Dynamic Title"
    assert body["views"] == 99
    assert body["likes"] == 7
    assert body["channelName"] == "Dynamic Channel"
    # The current client-facing response does not expose tags/category/nsfw directly;
    # this assertion protects the visible embed URL and dynamic overrides only.
    assert "tags" not in body
    assert "category" not in body
    assert body["embedUrl"] == "https://example.org/embed/123"
    assert body["thumbnail_url"] == "https://example.org/thumb-large.jpg"
    assert body["thumbnail_urls"] == [
        "https://example.org/thumb-large.jpg",
        "https://example.org/thumb-small.jpg",
    ]
    assert body["preview_path"] == "/lazy-static/previews/db.jpg"


def test_missing_video_id_and_missing_row_return_current_errors() -> None:
    """Video handler error shapes are part of the current Client-facing contract."""
    server = SimpleNamespace(db=_connect(), db_lock=threading.RLock(), video_error_threshold=2)

    missing_id = video_handler.handle_video_request(server, {})
    assert missing_id.status == 400
    assert missing_id.payload == {"error": "Missing video id"}

    missing_row = video_handler.handle_video_request(server, {"id": ["missing"], "host": ["example.org"]})
    assert missing_row.status == 404
    assert missing_row.payload == {"error": "Video not found"}


def test_dynamic_refresh_persists_runtime_counters_but_not_prepared_discovery_sources(monkeypatch) -> None:
    """Live refresh may persist counters, but tags/category remain crawler-owned inputs."""
    conn = _connect()
    server = SimpleNamespace(
        db=conn,
        db_lock=threading.RLock(),
        video_error_threshold=2,
        popularity_like_weight=2.0,
    )
    monkeypatch.setattr(
        video_handler,
        "fetch_instance_video_dynamic",
        lambda _host, _video_id: {
            "title": "Dynamic Title",
            "views": 99,
            "likes": 7,
            "dislikes": 2,
            "channel_display": "Dynamic Channel",
            "tags_json": '["dynamic"]',
            "category": "Dynamic Category",
            "nsfw": 1,
        },
    )

    result = video_handler.handle_video_request(
        server, {"id": ["123"], "host": ["example.org"]}
    )
    row = conn.execute(
        "SELECT views, likes, dislikes, tags_json, category, nsfw, last_checked_at FROM videos "
        "WHERE video_id='123' AND instance_domain='example.org'"
    ).fetchone()

    assert result.status == 200
    assert (row["views"], row["likes"], row["dislikes"], row["nsfw"]) == (99, 7, 2, 1)
    assert row["last_checked_at"] > 1000
    assert row["tags_json"] == '["db"]'
    assert row["category"] == "DB Category"


def test_dynamic_refresh_still_uses_live_metadata_in_response(monkeypatch) -> None:
    """Not persisting prepared inputs must not make the live detail response stale."""
    conn = _connect()
    server = SimpleNamespace(db=conn, db_lock=threading.RLock(), video_error_threshold=2)
    monkeypatch.setattr(
        video_handler,
        "fetch_instance_video_dynamic",
        lambda _host, _video_id: {"title": "Live title", "views": 88, "likes": 4},
    )

    result = video_handler.handle_video_request(
        server, {"id": ["123"], "host": ["example.org"]}
    )

    assert result.payload["title"] == "Live title"
    assert result.payload["views"] == 88


def test_live_detail_cannot_override_persisted_thumbnail_candidate_state(monkeypatch) -> None:
    """Negative: request-time PeerTube metadata never replaces persisted thumbnail state."""
    conn = _connect()
    server = SimpleNamespace(db=conn, db_lock=threading.RLock(), video_error_threshold=2)
    monkeypatch.setattr(
        video_handler,
        "fetch_instance_video_dynamic",
        lambda _host, _video_id: {
            "title": "Live title",
            "thumbnail_url": "https://live.example/other.jpg",
            "thumbnail_urls": ["https://live.example/other.jpg"],
            "preview_path": "/live-preview.jpg",
        },
    )

    result = video_handler.handle_video_request(
        server, {"id": ["123"], "host": ["example.org"]}
    )

    assert result.payload["thumbnail_urls"] == [
        "https://example.org/thumb-large.jpg",
        "https://example.org/thumb-small.jpg",
    ]
    assert result.payload["thumbnail_url"] == "https://example.org/thumb-large.jpg"
    assert result.payload["preview_path"] == "/lazy-static/previews/db.jpg"
