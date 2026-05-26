"""Characterize Client /client/events/publish bridge behavior."""
from __future__ import annotations


def test_client_publish_event_adds_missing_identity_fields_and_publishes_to_bridge(
    start_json_engine, start_client_backend
) -> None:
    """The publish route must enrich bare events before forwarding them to Engine."""
    fake_engine = start_json_engine(
        {("POST", "/internal/events/ingest"): lambda _record: (200, {"ok": True})}
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.post(
        "/client/events/publish",
        json={"event_type": "Like", "actor_id": "local-user"},
    )
    status, body = response.status_code, response.json()

    published = fake_engine.requests[0]["body"]
    assert status == 200
    assert body == {"ok": True, "response": {"ok": True}}
    assert published["event_id"].startswith("client-")
    assert isinstance(published["published_at"], int)
    assert published["event_type"] == "Like"
    assert published["actor_id"] == "local-user"


def test_client_publish_event_activitypub_mode_returns_current_not_implemented_shape(
    start_json_engine, start_client_backend
) -> None:
    """The reserved activitypub mode must remain a controlled not-implemented branch."""
    fake_engine = start_json_engine(
        {("POST", "/internal/events/ingest"): lambda _record: (200, {"ok": True})}
    )
    client = start_client_backend(
        f"http://127.0.0.1:{fake_engine.server_port}",
        publish_mode="activitypub",
    )

    response = client.post(
        "/client/events/publish",
        json={"event_type": "Like"},
    )
    status, body = response.status_code, response.json()

    assert status == 502
    assert body == {
        "ok": False,
        "error": "CLIENT_PUBLISH_MODE=activitypub is not implemented yet",
        "mode": "activitypub",
    }
    assert fake_engine.requests == []
