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
    metadata_row = {
        "video_id": "123",
        "title": "Example",
        "instance_domain": "example.org",
        "thumbnail_url": "/static/thumbnails/large.jpg",
        "thumbnail_urls": [
            "/static/thumbnails/large.jpg",
            "https://cdn.example/small.jpg",
            "/static/thumbnails/large.jpg",
        ],
        "preview_path": "/lazy-static/previews/preview.jpg",
    }
    fake_engine = start_json_engine(
        {("POST", "/internal/videos/metadata"): lambda _record: (200, {"rows": [metadata_row]})}
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/user-profile/likes?user_id=local-user")
    status, body = response.status_code, response.json()

    assert status == 200
    assert body["user_id"] == "local-user"
    assert body["likes"] == [
        {
            **metadata_row,
            "thumbnail_url": "https://example.org/static/thumbnails/large.jpg",
                "thumbnail_urls": [
                    "https://example.org/static/thumbnails/large.jpg",
                    "https://cdn.example/small.jpg",
                ],
                "thumbnail_candidates": [
                    {
                        "url": "https://example.org/static/thumbnails/large.jpg",
                        "width": None,
                        "height": None,
                    },
                    {
                        "url": "https://cdn.example/small.jpg",
                        "width": None,
                        "height": None,
                    },
                ],
            }
        ]
    assert isinstance(body["updatedAt"], int)
    assert fake_engine.requests[0]["path"] == "/internal/videos/metadata"
    assert fake_engine.requests[0]["body"]["entries"][0]["video_id"] == "123"
    assert fake_engine.requests[0]["body"]["entries"][0]["video_uuid"] == "uuid-123"
    assert fake_engine.requests[0]["body"]["entries"][0]["instance_domain"] == "example.org"
    assert isinstance(fake_engine.requests[0]["body"]["entries"][0]["updated_at"], int)


def test_profile_likes_does_not_promote_preview_when_engine_has_no_thumbnail(
    client_db, start_json_engine, start_client_backend
) -> None:
    """Profile cards use the same no-preview thumbnail boundary as other Client reads."""
    record_like(
        client_db,
        "local-user",
        "like",
        {"video_id": "123", "video_uuid": "uuid-123", "instance_domain": "example.org"},
        max_likes=100,
    )
    fake_engine = start_json_engine(
        {
            ("POST", "/internal/videos/metadata"): lambda _record: (
                200,
                {
                    "rows": [
                        {
                            "video_id": "123",
                            "instance_domain": "example.org",
                            "thumbnail_url": None,
                            "preview_path": "/lazy-static/previews/preview.jpg",
                        }
                    ]
                },
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/user-profile/likes?user_id=local-user")

    assert response.status_code == 200
    assert response.json()["likes"][0]["thumbnail_urls"] == []
    assert response.json()["likes"][0]["thumbnail_url"] is None


def test_client_supplied_profile_likes_use_same_thumbnail_normalization(
    start_json_engine, start_client_backend
) -> None:
    """POSTed client likes normalize candidates and never promote preview-only rows."""
    def resolve_response(record):
        body = record["body"]
        uuid = body.get("uuid")
        return 200, {
            "video": {
                "video_id": "123" if uuid == "uuid-good" else "456",
                "video_uuid": uuid,
                "instance_domain": "example.org",
            }
        }

    def metadata_response(record):
        rows = []
        for entry in record["body"]["entries"]:
            if entry["video_id"] == "123":
                rows.append(
                    {
                        "video_id": "123",
                        "instance_domain": "example.org",
                        "thumbnail_url": "/large.jpg",
                        "thumbnail_urls": ["/large.jpg", "/small.jpg"],
                        "preview_path": "/preview.jpg",
                    }
                )
            else:
                rows.append(
                    {
                        "video_id": "456",
                        "instance_domain": "example.org",
                        "thumbnail_url": None,
                        "preview_path": "/preview-only.jpg",
                    }
                )
        return 200, {"rows": rows}

    fake_engine = start_json_engine(
        {
            ("POST", "/internal/videos/resolve"): resolve_response,
            ("POST", "/internal/videos/metadata"): metadata_response,
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.post(
        "/api/user-profile/likes",
        json={
            "likes": [
                {"uuid": "uuid-good", "host": "example.org"},
                {"uuid": "uuid-preview", "host": "example.org"},
            ]
        },
    )

    assert response.status_code == 200
    likes = response.json()["likes"]
    assert likes[0]["thumbnail_urls"] == [
        "https://example.org/large.jpg",
        "https://example.org/small.jpg",
    ]
    assert likes[0]["thumbnail_url"] == "https://example.org/large.jpg"
    assert likes[1]["thumbnail_urls"] == []
    assert likes[1]["thumbnail_url"] is None
