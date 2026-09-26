"""Characterize recommendation request parsing without importing FAISS-backed server."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))
sys.modules.pop("services", None)

from services import recommendation_service as rec_service  # noqa: E402


def test_recommendations_likes_payload_error_rejects_too_many_likes() -> None:
    """Oversized Client likes payloads must preserve the current 400 error body."""
    payload = {"likes": [{"uuid": str(index), "host": "example.org"} for index in range(3)]}

    error = rec_service._recommendations_likes_payload_error("/recommendations", payload, max_items=2)

    assert error == {
        "error": "Too many likes in request body",
        "code": "too_many_likes",
        "max_likes": 2,
        "max_allowed": 2,
        "received": 3,
    }


def test_recommendations_likes_payload_error_reports_invalid_entry_index_and_reason() -> None:
    """Malformed likes entries should report current reason and index."""
    not_object = rec_service._recommendations_likes_payload_error("/recommendations", {"likes": ["bad"]}, 10)
    missing_uuid = rec_service._recommendations_likes_payload_error("/recommendations", {"likes": [{"host": "example.org"}]}, 10)
    missing_host = rec_service._recommendations_likes_payload_error("/recommendations", {"likes": [{"uuid": "uuid"}]}, 10)

    assert not_object == {"error": "Invalid likes payload", "reason": "likes entry must be an object", "index": 0}
    assert missing_uuid == {"error": "Invalid likes payload", "reason": "likes.uuid must be a non-empty string", "index": 0}
    assert missing_host == {"error": "Invalid likes payload", "reason": "likes.host must be a non-empty string", "index": 0}


def test_parse_client_likes_normalizes_uuid_host_and_skips_invalid_items() -> None:
    """Client likes parsing keeps only valid uuid/host pairs in Engine field names."""
    likes = rec_service._parse_client_likes(
        {
            "likes": [
                {"uuid": " uuid-1 ", "host": " example.org "},
                {"uuid": "", "host": "example.org"},
                {"uuid": "uuid-2"},
                "bad",
            ]
        }
    )

    assert likes == [{"video_uuid": "uuid-1", "instance_domain": "example.org"}]


def test_finite_recommendation_final_filter_accepts_match_and_rejects_mismatch() -> None:
    """The temporary final boundary is strict without trying to refill the legacy batch."""
    import sqlite3
    import threading
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from data.video_filters import VideoFilters

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE instance_denylist(host TEXT PRIMARY KEY, is_active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE channel_moderation(channel_id TEXT, instance_domain TEXT, status TEXT, PRIMARY KEY(channel_id,instance_domain));
        """
    )
    server = SimpleNamespace(
        db=conn,
        db_lock=threading.RLock(),
        enable_instance_ignore=True,
        enable_channel_blocklist=True,
        embeddings_count=2,
    )
    rows = [
        {"video_id":"match","instance_domain":"one.example","channel_id":"c1","language":"uk","category":"Education","category_id":"13","tags_json":'["linux"]'},
        {"video_id":"miss","instance_domain":"one.example","channel_id":"c2","language":"en","category":"Education","category_id":"13","tags_json":'["linux"]'},
    ]
    result = rec_service.build_rows_response(
        server, rows, False, "req", datetime.now(timezone.utc), {"user_id":"u"}, VideoFilters(language="uk")
    )
    assert [row["video_id"] for row in result.payload["rows"]] == ["match"]
    assert result.payload["rows"][0]["language"] == "uk"
    conn.close()


def test_finite_recommendation_filter_can_underfill_to_empty() -> None:
    """A valid filter may empty the finite batch instead of admitting a mismatch."""
    import sqlite3
    import threading
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from data.video_filters import VideoFilters

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE instance_denylist(host TEXT PRIMARY KEY, is_active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE channel_moderation(channel_id TEXT, instance_domain TEXT, status TEXT, PRIMARY KEY(channel_id,instance_domain));
        """
    )
    server = SimpleNamespace(db=conn, db_lock=threading.RLock(), enable_instance_ignore=True, enable_channel_blocklist=True, embeddings_count=1)
    result = rec_service.build_rows_response(
        server,
        [{"video_id":"miss","instance_domain":"one.example","channel_id":"c1","language":"en","tags_json":"[]"}],
        False,
        "req",
        datetime.now(timezone.utc),
        {"user_id":"u"},
        VideoFilters(language="uk"),
    )
    assert result.payload["rows"] == []
    conn.close()


def test_finite_recommendation_random_fallback_uses_same_strict_filter(monkeypatch) -> None:
    """Negative/positive: legacy fallback cannot bypass Home filters and may underfill."""
    import sqlite3
    import threading
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from data.video_filters import VideoFilters

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE instance_denylist(host TEXT PRIMARY KEY, is_active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE channel_moderation(channel_id TEXT, instance_domain TEXT, status TEXT, PRIMARY KEY(channel_id,instance_domain));
        """
    )

    class EmptyStrategy:
        def generate_recommendations(self, *_args, **_kwargs):
            return []

    server = SimpleNamespace(
        db=conn,
        db_lock=threading.RLock(),
        enable_instance_ignore=True,
        enable_channel_blocklist=True,
        embeddings_count=2,
        recommendation_strategy=EmptyStrategy(),
    )
    monkeypatch.setattr(
        rec_service,
        "fetch_random_rows_from_server",
        lambda _server, _limit: [
            {"video_id": "match", "instance_domain": "one.example", "channel_id": "c1", "language": "uk", "category": "Education", "tags_json": '["linux"]'},
            {"video_id": "miss", "instance_domain": "one.example", "channel_id": "c2", "language": "en", "category": "Education", "tags_json": '["linux"]'},
        ],
    )
    result = rec_service.handle_home(
        server,
        "guest",
        48,
        False,
        False,
        "req",
        datetime.now(timezone.utc),
        "home",
        VideoFilters(language="uk"),
    )
    assert [row["video_id"] for row in result.payload["rows"]] == ["match"]
    assert result.payload["seed"]["random"] is True
    conn.close()


def test_index_id_metadata_row_filters_without_requerying_metadata_boundary(monkeypatch) -> None:
    """Positive/negative: ANN-style resolved metadata already contains every final filter input."""
    import sqlite3
    import threading
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from data.metadata import fetch_metadata_by_index_ids
    from data.video_filters import VideoFilters
    from engine.server.db.migrations.apply import apply_video_index_ids_migration

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE channels(channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT, PRIMARY KEY(channel_id,instance_domain));
        CREATE TABLE videos(
          video_id TEXT, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT, channel_id TEXT,
          channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT,
          tags_json TEXT, category TEXT, category_id TEXT, language TEXT, language_label TEXT, published_at INTEGER,
          video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER,
          dislikes INTEGER, comments_count INTEGER, nsfw INTEGER, preview_path TEXT, last_checked_at INTEGER,
          error_count INTEGER DEFAULT 0, PRIMARY KEY(video_id,instance_domain)
        );
        CREATE TABLE video_embeddings(video_id TEXT, instance_domain TEXT, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY(video_id,instance_domain));
        CREATE TABLE instance_denylist(host TEXT PRIMARY KEY, is_active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE channel_moderation(channel_id TEXT, instance_domain TEXT, status TEXT, PRIMARY KEY(channel_id,instance_domain));
        """
    )
    apply_video_index_ids_migration(conn)
    conn.execute("INSERT INTO channels VALUES ('c','example.org','Channel',NULL)")
    conn.execute(
        """INSERT INTO videos VALUES ('v','u',1,'example.org','c','c',NULL,NULL,NULL,'Title',NULL,'["linux"]','Education','0013','uk','Ukrainian',1,NULL,1,NULL,NULL,1,1,0,0,0,NULL,1,0)"""
    )
    conn.execute("INSERT INTO video_embeddings VALUES ('v','example.org',3,'test')")
    conn.execute("INSERT INTO video_index_ids(index_id,video_id,instance_domain,is_active,created_at,updated_at) VALUES (9,'v','example.org',1,1,1)")
    row = fetch_metadata_by_index_ids(conn, [9])[9]
    assert (row["language"], row["category"], row["category_id"], row["tags_json"], row["instance_domain"]) == (
        "uk", "Education", "0013", '["linux"]', "example.org"
    )

    server = SimpleNamespace(
        db=conn,
        db_lock=threading.RLock(),
        enable_instance_ignore=True,
        enable_channel_blocklist=True,
        embeddings_count=1,
    )
    result = rec_service.build_rows_response(
        server,
        [row],
        False,
        "req",
        datetime.now(timezone.utc),
        {"user_id": "u"},
        VideoFilters(language="uk", category="education", tag="linux", instance="example.org"),
    )
    assert [item["video_id"] for item in result.payload["rows"]] == ["v"]
    assert result.payload["rows"][0]["category_id"] == "0013"

    mismatch = rec_service.build_rows_response(
        server,
        [row],
        False,
        "req2",
        datetime.now(timezone.utc),
        {"user_id": "u"},
        VideoFilters(language="en"),
    )
    assert mismatch.payload["rows"] == []
    conn.close()
