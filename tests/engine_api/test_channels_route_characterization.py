"""Characterize Engine health and channel route behavior."""
from __future__ import annotations

import threading
from types import SimpleNamespace

from conftest import RouteCapturingHandler, import_similar_handler_module


def test_health_response_uses_current_server_fields(monkeypatch) -> None:
    """The health route must keep the current ok/total/embeddingDim response."""
    similar = import_similar_handler_module(monkeypatch)
    server = SimpleNamespace(rate_limiter=None, embeddings_count=42, embeddings_dim=384)
    handler = RouteCapturingHandler("/api/health", server=server)

    similar.SimilarHandler.do_GET(handler)

    assert handler.status == 200
    assert handler.parsed_body() == {"ok": True, "total": 42, "embeddingDim": 384}


def test_channels_query_defaults_caps_and_response_shape(monkeypatch) -> None:
    """Channel query parsing must preserve current defaults, caps, and passthrough fields."""
    similar = import_similar_handler_module(monkeypatch)
    captured = {}

    def fake_fetch_channels(_db, **kwargs):
        """Capture normalized fetch parameters at the data-access boundary."""
        captured.update(kwargs)
        return ([{"channel_id": "c1"}], 1)

    monkeypatch.setattr(
        "engine.server.api.services.channel_service.fetch_channels", fake_fetch_channels
    )
    server = SimpleNamespace(rate_limiter=None, db=object(), db_lock=threading.RLock())
    handler = RouteCapturingHandler(
        "/api/channels?limit=9999&offset=bad&maxVideos=-1&q=abc&instance=example.org&sort=videos&dir=asc",
        server=server,
    )

    similar.SimilarHandler.do_GET(handler)
    body = handler.parsed_body()

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
    assert handler.status == 200
    assert isinstance(body["generatedAt"], int)
    assert body["total"] == 1
    assert body["rows"] == [{"channel_id": "c1"}]


def test_channels_invalid_or_zero_limit_defaults_to_100(monkeypatch) -> None:
    """Invalid and non-positive channel limits must keep the current default of 100."""
    similar = import_similar_handler_module(monkeypatch)
    seen_limits = []

    def fake_fetch_channels(_db, **kwargs):
        """Record the normalized limit for each channel request."""
        seen_limits.append(kwargs["limit"])
        return ([], 0)

    monkeypatch.setattr(
        "engine.server.api.services.channel_service.fetch_channels", fake_fetch_channels
    )
    server = SimpleNamespace(rate_limiter=None, db=object(), db_lock=threading.RLock())

    for raw_limit in ("bad", "0"):
        handler = RouteCapturingHandler(f"/api/channels?limit={raw_limit}", server=server)
        similar.SimilarHandler.do_GET(handler)
        assert handler.status == 200

    assert seen_limits == [100, 100]
