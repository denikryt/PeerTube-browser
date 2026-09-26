"""Characterize Client /api/user-action like behavior through real HTTP."""
from __future__ import annotations


def _resolve_response(_record):
    """Return the canonical Engine identity used by Client like actions."""
    return 200, {
        "video": {
            "video_id": "123",
            "video_uuid": "uuid-123",
            "instance_domain": "example.org",
            "video_url": "https://example.org/w/uuid-123",
        }
    }


def test_like_action_writes_client_db_and_publishes_normalized_engine_event(
    client_db, start_json_engine, start_client_backend
) -> None:
    """A user like must persist locally and publish the current bridge payload shape."""
    fake_engine = start_json_engine(
        {
            ("POST", "/internal/videos/resolve"): _resolve_response,
            ("POST", "/internal/events/ingest"): lambda _record: (200, {"ok": True}),
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.post(
        "/api/user-action",
        json={"action": "like", "uuid": "uuid-123", "host": "example.org", "user_id": "local-user"},
    )
    status, body = response.status_code, response.json()

    row = client_db.execute(
        "SELECT video_id, video_uuid, instance_domain FROM likes WHERE user_id = ?",
        ("local-user",),
    ).fetchone()
    ingest_request = [
        request
        for request in fake_engine.requests
        if request["path"] == "/internal/events/ingest"
    ][0]
    event = ingest_request["body"]

    assert status == 200
    assert body["ok"] is True
    assert body["bridge_ok"] is True
    assert body["bridge_error"] is None
    assert body["user_id"] == "local-user"
    assert isinstance(body["updatedAt"], int)
    assert tuple(row) == ("123", "uuid-123", "example.org")
    assert event["event_id"].startswith("client-")
    assert event["event_type"] == "Like"
    assert event["actor_id"] == "local-user"
    assert event["object"] == {
        "video_uuid": "uuid-123",
        "instance_domain": "example.org",
        "canonical_url": "https://example.org/w/uuid-123",
    }
    assert event["source_instance"] == "example.org"
    assert event["raw_payload"]["action"] == "like"


def test_like_action_keeps_local_like_but_returns_502_when_bridge_ingest_fails(
    client_db, start_json_engine, start_client_backend
) -> None:
    """Current partial failure semantics keep the local like and report bridge failure."""
    fake_engine = start_json_engine(
        {
            ("POST", "/internal/videos/resolve"): _resolve_response,
            ("POST", "/internal/events/ingest"): lambda _record: (500, {"error": "boom"}),
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.post(
        "/api/user-action",
        json={"action": "like", "uuid": "uuid-123", "host": "example.org", "user_id": "local-user"},
    )
    status, body = response.status_code, response.json()

    count = client_db.execute(
        "SELECT COUNT(*) FROM likes WHERE user_id = ?", ("local-user",)
    ).fetchone()[0]
    assert status == 502
    assert body["ok"] is False
    assert body["bridge_ok"] is False
    assert body["bridge_error"]
    assert count == 1
