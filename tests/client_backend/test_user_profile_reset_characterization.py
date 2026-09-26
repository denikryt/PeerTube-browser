"""Characterize Client /api/user-profile/reset behavior."""
from __future__ import annotations

from lib.users_store import record_like


def test_user_profile_reset_clears_likes_and_returns_current_shape(
    client_db, start_json_engine, start_client_backend
) -> None:
    """Reset must clear only Client-owned profile likes and return an empty profile."""
    record_like(
        client_db,
        "local-user",
        "like",
        {"video_id": "123", "video_uuid": "uuid-123", "instance_domain": "example.org"},
        max_likes=100,
    )
    fake_engine = start_json_engine({})
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.post("/api/user-profile/reset", json={"user_id": "local-user"})
    status, body = response.status_code, response.json()

    count = client_db.execute(
        "SELECT COUNT(*) FROM likes WHERE user_id = ?", ("local-user",)
    ).fetchone()[0]
    assert status == 200
    assert body["user_id"] == "local-user"
    assert body["likes"] == []
    assert isinstance(body["updatedAt"], int)
    assert count == 0
