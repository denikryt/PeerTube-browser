"""Characterize Engine health and channel route behavior through FastAPI."""
from __future__ import annotations

from app import create_app
from conftest import make_engine_state
from fastapi.testclient import TestClient


def test_health_response_uses_current_server_fields(engine_client) -> None:
    """The health route must keep the current ok/total/embeddingDim response."""
    response = engine_client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "total": 42, "embeddingDim": 384}


def test_channels_query_defaults_caps_and_response_shape(monkeypatch) -> None:
    """Channel query parsing must preserve current defaults, caps, and passthrough fields."""
    import routes.channels as channels_route

    captured = {}

    def fake_fetch_channel_rows(_server, query):
        """Capture normalized fetch parameters at the data-access boundary."""
        captured.update(query.__dict__)
        return ([{"channel_id": "c1"}], 1)

    monkeypatch.setattr(channels_route, "fetch_channel_rows", fake_fetch_channel_rows)
    state = make_engine_state()
    try:
        client = TestClient(create_app(state))
        response = client.get(
            "/api/channels?limit=9999&offset=bad&maxVideos=-1&q=abc&instance=example.org&sort=videos&dir=asc"
        )
    finally:
        state.db.close()

    body = response.json()
    assert captured == {
        "limit": 500,
        "offset": 0,
        "query": "abc",
        "instance": "example.org",
        "min_followers": 0,
        "min_videos": 0,
        "max_videos": None,
        "sort": "videos",
        "direction": "asc",
    }
    assert response.status_code == 200
    assert isinstance(body["generatedAt"], int)
    assert body["total"] == 1
    assert body["rows"] == [{"channel_id": "c1"}]


def test_channels_invalid_or_zero_limit_defaults_to_100(monkeypatch) -> None:
    """Invalid and non-positive channel limits must keep the current default of 100."""
    import routes.channels as channels_route

    seen_limits = []

    def fake_fetch_channel_rows(_server, query):
        """Record the normalized limit for each channel request."""
        seen_limits.append(query.limit)
        return ([], 0)

    monkeypatch.setattr(channels_route, "fetch_channel_rows", fake_fetch_channel_rows)
    state = make_engine_state()
    try:
        client = TestClient(create_app(state))
        for raw_limit in ("bad", "0"):
            response = client.get(f"/api/channels?limit={raw_limit}")
            assert response.status_code == 200
    finally:
        state.db.close()

    assert seen_limits == [100, 100]
