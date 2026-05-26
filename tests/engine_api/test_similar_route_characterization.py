"""Characterize Engine similar/recommendation route behavior through FastAPI."""
from __future__ import annotations

import importlib
import sqlite3
import threading

import pytest
from app import create_app
from conftest import make_engine_state
from fastapi.testclient import TestClient


def test_videos_path_similar_injects_path_id_before_execution(monkeypatch) -> None:
    """``/videos/{id}/similar`` must keep injecting the path id as ``id`` params."""
    import routes.recommendations as route

    captured = {}

    def fake_handle_similar(_handler, _server, params):
        """Capture params passed to the recommendation execution boundary."""
        captured.update(params)
        from http_utils import respond_json

        respond_json(_handler, 200, {"rows": [], "count": 0})

    monkeypatch.setattr(route, "handle_similar", fake_handle_similar)
    state = make_engine_state()
    try:
        client = TestClient(create_app(state))
        response = client.get("/videos/abc123/similar?limit=5")
    finally:
        state.db.close()

    assert response.status_code == 200
    assert captured["id"] == ["abc123"]
    assert captured["limit"] == ["5"]


def test_debug_disabled_returns_current_403() -> None:
    """Debug requests must keep the current disabled-debug error before DB access."""
    state = make_engine_state(
        default_limit=10,
        refresh_similarity_cache=False,
        recommendations_debug_enabled=False,
    )
    try:
        client = TestClient(create_app(state))
        response = client.get("/videos/abc123/similar?debug=1")
    finally:
        state.db.close()

    assert response.status_code == 403
    assert response.json() == {"error": "Debug mode is disabled"}


def test_oversized_recommendations_body_returns_current_invalid_json_error() -> None:
    """Oversized POST bodies must keep the current Invalid JSON body response."""
    state = make_engine_state(use_client_likes=False)
    try:
        client = TestClient(create_app(state))
        response = client.post(
            "/recommendations",
            content=b"",
            headers={"content-type": "application/json", "content-length": "1000001"},
        )
    finally:
        state.db.close()

    assert response.status_code == 400
    assert response.json() == {"error": "Invalid JSON body"}


def test_invalid_recommendations_likes_payload_preserves_current_error() -> None:
    """Malformed recommendation likes must keep the current validation response."""
    state = make_engine_state(use_client_likes=False)
    try:
        client = TestClient(create_app(state))
        response = client.post(
            "/recommendations",
            json={"likes": [{"uuid": "uuid-only"}]},
        )
    finally:
        state.db.close()

    assert response.status_code == 400
    assert response.json() == {
        "error": "Invalid likes payload",
        "reason": "likes.host must be a non-empty string",
        "index": 0,
    }


def test_request_context_is_cleared_after_recommendation_error(monkeypatch) -> None:
    """Client likes request context must be cleared even when recommendation execution fails."""
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
    state = make_engine_state(
        use_client_likes=True,
        db=conn,
        db_lock=threading.RLock(),
    )
    try:
        client = TestClient(create_app(state))
        with pytest.raises(RuntimeError, match="controlled failure"):
            client.post(
                "/recommendations",
                json={"likes": [{"uuid": "uuid-123", "host": "example.org"}]},
            )
    finally:
        conn.close()

    assert request_context.fetch_recent_likes_request("local-user", 10) == []
