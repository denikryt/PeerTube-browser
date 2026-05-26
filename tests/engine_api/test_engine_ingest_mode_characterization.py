"""Characterize Engine ingest-mode route behavior."""
from __future__ import annotations

from types import SimpleNamespace

from conftest import RouteCapturingHandler, import_similar_handler_module
from test_internal_events_ingest_characterization import _event


def test_ingest_disabled_returns_current_501_shape(monkeypatch) -> None:
    """Disabled bridge ingest must preserve the current route-level 501 response."""
    similar = import_similar_handler_module(monkeypatch)
    server = SimpleNamespace(rate_limiter=None, engine_ingest_mode="activitypub")
    handler = RouteCapturingHandler(
        "/internal/events/ingest", method="POST", body=_event(), server=server
    )

    similar.SimilarHandler.do_POST(handler)

    assert handler.status == 501
    assert handler.parsed_body() == {
        "error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE",
        "mode": "activitypub",
    }


def test_ingest_enabled_delegates_to_current_handler(monkeypatch, engine_event_server) -> None:
    """Bridge mode must continue to execute the existing ingest handler path."""
    similar = import_similar_handler_module(monkeypatch)
    engine_event_server.rate_limiter = None
    engine_event_server.engine_ingest_mode = "bridge"
    handler = RouteCapturingHandler(
        "/internal/events/ingest",
        method="POST",
        body=_event("evt-route-1"),
        server=engine_event_server,
    )

    similar.SimilarHandler.do_POST(handler)
    body = handler.parsed_body()

    assert handler.status == 200
    assert body["ok"] is True
    assert body["ingested"] == 1
    assert body["duplicates"] == 0
