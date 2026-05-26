"""Characterize Client /api/user-profile local profile reads."""
from __future__ import annotations

from lib.users_store import record_like


def test_user_profile_get_returns_local_like_identities_without_engine_metadata(
    client_db, start_json_engine, start_client_backend, http_json
) -> None:
    """The profile route exposes local stored identities and does not enrich via Engine."""
    record_like(
        client_db,
        "local-user",
        "like",
        {"video_id": "123", "video_uuid": "uuid-123", "instance_domain": "example.org"},
        max_likes=100,
    )
    fake_engine = start_json_engine({})
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    status, body = http_json(
        "GET",
        f"http://127.0.0.1:{client.server_port}/api/user-profile?user_id=local-user",
    )

    assert status == 200
    assert body["user_id"] == "local-user"
    assert body["likes"] == [
        {
            "video_id": "123",
            "video_uuid": "uuid-123",
            "instance_domain": "example.org",
            "updated_at": body["likes"][0]["updated_at"],
        }
    ]
    assert isinstance(body["likes"][0]["updated_at"], int)
    assert isinstance(body["updatedAt"], int)
    assert fake_engine.requests == []
