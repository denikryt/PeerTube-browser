"""Characterize Client profile likes metadata enrichment through Engine."""
from __future__ import annotations

from lib.users_store import record_like


def test_profile_likes_get_returns_engine_metadata_rows(
    client_db, start_json_engine, start_client_backend
) -> None:
    """Client stores lightweight likes and asks Engine for display metadata."""
    record_like(
        client_db,
        "local-user",
        "like",
        {"video_id": "123", "video_uuid": "uuid-123", "instance_domain": "example.org"},
        max_likes=100,
    )
    metadata_row = {"video_id": "123", "title": "Example", "instance_domain": "example.org"}
    fake_engine = start_json_engine(
        {("POST", "/internal/videos/metadata"): lambda _record: (200, {"rows": [metadata_row]})}
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/user-profile/likes?user_id=local-user")
    status, body = response.status_code, response.json()

    assert status == 200
    assert body["user_id"] == "local-user"
    assert body["likes"] == [metadata_row]
    assert isinstance(body["updatedAt"], int)
    assert fake_engine.requests[0]["path"] == "/internal/videos/metadata"
    assert fake_engine.requests[0]["body"]["entries"][0]["video_id"] == "123"
    assert fake_engine.requests[0]["body"]["entries"][0]["video_uuid"] == "uuid-123"
    assert fake_engine.requests[0]["body"]["entries"][0]["instance_domain"] == "example.org"
    assert isinstance(fake_engine.requests[0]["body"]["entries"][0]["updated_at"], int)
