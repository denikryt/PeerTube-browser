"""Characterize Engine ingest-mode route behavior through FastAPI."""
from __future__ import annotations

from app import create_app
from conftest import make_engine_state
from fastapi.testclient import TestClient
from test_internal_events_ingest_characterization import _event


def test_ingest_disabled_returns_current_501_shape() -> None:
    """Disabled bridge ingest must preserve the current route-level 501 response."""
    state = make_engine_state(engine_ingest_mode="activitypub")
    try:
        client = TestClient(create_app(state))
        response = client.post("/internal/events/ingest", json=_event())
    finally:
        state.db.close()

    assert response.status_code == 501
    assert response.json() == {
        "error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE",
        "mode": "activitypub",
    }


def test_ingest_enabled_delegates_to_current_handler(engine_event_server) -> None:
    """Bridge mode must continue to execute the existing ingest handler path."""
    state = make_engine_state(
        db=engine_event_server.db,
        db_lock=engine_event_server.db_lock,
        engine_ingest_mode="bridge",
    )
    client = TestClient(create_app(state))

    response = client.post("/internal/events/ingest", json=_event("evt-route-1"))
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["ingested"] == 1
    assert body["duplicates"] == 0
