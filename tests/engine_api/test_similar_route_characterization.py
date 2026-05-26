"""Characterize Engine similar/recommendation route behavior before route extraction."""
from __future__ import annotations

import importlib
import io
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from conftest import RouteCapturingHandler, import_similar_handler_module


def test_videos_path_similar_injects_path_id_before_execution(monkeypatch) -> None:
    """``/videos/{id}/similar`` must keep injecting the path id as ``id`` params."""
    similar = import_similar_handler_module(monkeypatch)
    route = importlib.import_module("routes.recommendations")
    captured = {}

    def fake_handle_similar(_handler, _server, params):
        """Capture params passed to the recommendation execution boundary."""
        captured.update(params)

    monkeypatch.setattr(route, "handle_similar", fake_handle_similar)
    handler = RouteCapturingHandler(
        "/videos/abc123/similar?limit=5",
        server=SimpleNamespace(rate_limiter=None),
    )

    similar.SimilarHandler.do_GET(handler)

    assert captured["id"] == ["abc123"]
    assert captured["limit"] == ["5"]


def test_debug_disabled_returns_current_403(monkeypatch) -> None:
    """Debug requests must keep the current disabled-debug error before DB access."""
    similar = import_similar_handler_module(monkeypatch)
    server = SimpleNamespace(
        rate_limiter=None,
        default_limit=10,
        refresh_similarity_cache=False,
        recommendations_debug_enabled=False,
    )
    handler = RouteCapturingHandler("/videos/abc123/similar?debug=1", server=server)

    similar.SimilarHandler.do_GET(handler)

    assert handler.status == 403
    assert handler.parsed_body() == {"error": "Debug mode is disabled"}


def test_oversized_recommendations_body_returns_current_invalid_json_error(monkeypatch) -> None:
    """Oversized POST bodies must keep the current Invalid JSON body response."""
    similar = import_similar_handler_module(monkeypatch)
    handler = RouteCapturingHandler(
        "/recommendations",
        method="POST",
        body={},
        server=SimpleNamespace(rate_limiter=None, use_client_likes=False),
    )
    handler.headers.replace_header("content-length", "1000001")
    handler.rfile = io.BytesIO(b"")

    similar.SimilarHandler.do_POST(handler)

    assert handler.status == 400
    assert handler.parsed_body() == {"error": "Invalid JSON body"}


def test_invalid_recommendations_likes_payload_preserves_current_error(monkeypatch) -> None:
    """Malformed recommendation likes must keep the current validation response."""
    similar = import_similar_handler_module(monkeypatch)
    handler = RouteCapturingHandler(
        "/recommendations",
        method="POST",
        body={"likes": [{"uuid": "uuid-only"}]},
        server=SimpleNamespace(rate_limiter=None, use_client_likes=False),
    )

    similar.SimilarHandler.do_POST(handler)

    assert handler.status == 400
    assert handler.parsed_body() == {
        "error": "Invalid likes payload",
        "reason": "likes.host must be a non-empty string",
        "index": 0,
    }


def test_request_context_is_cleared_after_recommendation_error(monkeypatch) -> None:
    """Client likes request context must be cleared even when recommendation execution fails."""
    similar = import_similar_handler_module(monkeypatch)
    recommendation_service = importlib.import_module(
        "engine.server.api.services.recommendation_service"
    )
    request_context = importlib.import_module("request_context")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE videos (video_id TEXT, video_uuid TEXT, instance_domain TEXT)")
    conn.execute("INSERT INTO videos VALUES ('123', 'uuid-123', 'example.org')")
    conn.commit()

    def fail_after_context(_handler, _server, _params):
        """Raise after Client likes have been put into request context."""
        assert request_context.fetch_recent_likes_request("local-user", 10) == [
            {"video_id": "123", "video_uuid": "uuid-123", "instance_domain": "example.org"}
        ]
        raise RuntimeError("controlled failure")

    monkeypatch.setattr(recommendation_service, "handle_similar", fail_after_context)
    server = SimpleNamespace(
        rate_limiter=None,
        use_client_likes=True,
        db=conn,
        db_lock=threading.RLock(),
    )
    handler = RouteCapturingHandler(
        "/recommendations",
        method="POST",
        body={"likes": [{"uuid": "uuid-123", "host": "example.org"}]},
        server=server,
    )

    with pytest.raises(RuntimeError, match="controlled failure"):
        similar.SimilarHandler.do_POST(handler)

    assert request_context.fetch_recent_likes_request("local-user", 10) == []
    conn.close()
