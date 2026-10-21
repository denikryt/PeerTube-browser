"""Discovery API v1 Client backend contract tests."""
from __future__ import annotations

import urllib.parse

from repositories.users import UsersRepository


def _row(video_id: str = "v1") -> dict[str, object]:
    return {
        "video_id": video_id,
        "video_uuid": f"uuid-{video_id}",
        "instance_domain": "example.org",
        "title": f"Video {video_id}",
    }


def test_v1_recommendations_get_uses_local_likes(client_db, start_json_engine, start_client_backend) -> None:
    repo = UsersRepository(client_db)
    repo.record_like(
        "u1",
        {"video_id": "liked", "video_uuid": "uuid-liked", "instance_domain": "example.org"},
        100,
    )
    fake_engine = start_json_engine(
        {
            ("POST", "/recommendations"): lambda record: (
                200,
                {"rows": [_row("rec1"), _row("rec2"), _row("rec3")]},
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/discovery/recommendations?limit=2&user_id=u1")

    assert response.status_code == 200
    body = response.json()
    assert [row["video_id"] for row in body["items"]] == ["rec1", "rec2"]
    assert body["pagination"]["limit"] == 2
    assert body["pagination"]["has_more"] is True
    assert body["meta"] == {"source": "recommendations", "fallback": False}
    assert fake_engine.requests[0]["method"] == "POST"
    assert fake_engine.requests[0]["body"]["likes"] == [
        {"uuid": "uuid-liked", "host": "example.org"}
    ]


def test_v1_recommendations_limits_local_likes_to_engine_contract(client_db, start_json_engine, start_client_backend) -> None:
    repo = UsersRepository(client_db)
    for index in range(12):
        repo.record_like(
            "u1",
            {
                "video_id": f"liked-{index}",
                "video_uuid": f"uuid-liked-{index}",
                "instance_domain": "example.org",
            },
            100,
        )
    fake_engine = start_json_engine(
        {
            ("POST", "/recommendations"): lambda _record: (
                200,
                {"rows": [_row("rec1")]},
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/discovery/recommendations?limit=1&user_id=u1")

    assert response.status_code == 200
    assert len(fake_engine.requests[0]["body"]["likes"]) == 5


def test_v1_recommendations_without_likes_returns_guest_envelope(start_json_engine, start_client_backend) -> None:
    fake_engine = start_json_engine(
        {("POST", "/recommendations"): lambda _record: (200, {"rows": [_row("guest")]})}
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/discovery/recommendations?limit=1&user_id=new")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["video_id"] == "guest"
    assert body["meta"] == {
        "source": "recommendations",
        "fallback": True,
        "fallback_reason": "guest_profile",
    }


def test_v1_video_requires_host(start_json_engine, start_client_backend) -> None:
    fake_engine = start_json_engine({("GET", "/api/video"): lambda _record: (200, {})})
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/videos/v1")

    assert response.status_code == 400
    assert response.json() == {"error": "Missing host", "code": "V1_DISCOVERY_MISSING_HOST"}
    assert fake_engine.requests == []


def test_v1_video_fetches_engine_metadata(start_json_engine, start_client_backend) -> None:
    fake_engine = start_json_engine(
        {
            ("GET", "/api/video"): lambda record: (
                200,
                {
                    "video_id": "v1",
                    "video_uuid": "uuid-v1",
                    "instance_domain": "example.org",
                    "title": "Video",
                },
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/videos/v1?host=example.org")

    assert response.status_code == 200
    body = response.json()
    assert body["video_id"] == "v1"
    assert body["video_uuid"] == "uuid-v1"
    assert body["instance_domain"] == "example.org"
    assert fake_engine.requests[0]["full_path"] == "/api/video?id=v1&host=example.org"


def test_v1_similar_uses_envelope_and_route_bound_cursor(start_json_engine, start_client_backend) -> None:
    fake_engine = start_json_engine(
        {
            ("GET", "/videos/v1/similar"): lambda _record: (
                200,
                {"rows": [_row("s1"), _row("s2"), _row("s3")]},
            ),
            ("GET", "/internal/discovery/fresh"): lambda _record: (200, {"rows": [_row("f1")]}),
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    first = client.get("/api/v1/videos/v1/similar?host=example.org&limit=2")
    assert first.status_code == 200
    body = first.json()
    assert [row["video_id"] for row in body["items"]] == ["s1", "s2"]
    cursor = body["pagination"]["next_cursor"]
    assert isinstance(cursor, str)

    bad = client.get(f"/api/v1/discovery/fresh?cursor={urllib.parse.quote(cursor)}")
    assert bad.status_code == 400
    assert bad.json()["code"] == "V1_DISCOVERY_BAD_REQUEST"


def test_v1_unknown_query_does_not_reach_engine(start_json_engine, start_client_backend) -> None:
    fake_engine = start_json_engine({("GET", "/internal/discovery/fresh"): lambda _record: (200, {})})
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/discovery/fresh?unknown=1")

    assert response.status_code == 400
    assert response.json()["code"] == "V1_DISCOVERY_BAD_REQUEST"
    assert fake_engine.requests == []


def test_v1_recommendations_normalizes_thumbnail_from_relative_preview_path(start_json_engine, start_client_backend) -> None:
    """Recommendation rows expose a browser-ready thumbnail_url fallback."""
    fake_engine = start_json_engine(
        {
            ("POST", "/recommendations"): lambda _record: (
                200,
                {
                    "rows": [
                        {
                            "video_id": "rec-preview",
                            "video_uuid": "uuid-rec-preview",
                            "instance_domain": "video.blast-info.fr",
                            "thumbnail_url": None,
                            "preview_path": "/lazy-static/previews/rec-preview.jpg",
                        },
                        _row("extra"),
                    ]
                },
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/discovery/recommendations?limit=1&user_id=image-test")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["thumbnail_url"] == "https://video.blast-info.fr/lazy-static/previews/rec-preview.jpg"
    assert body["items"][0]["preview_path"] == "/lazy-static/previews/rec-preview.jpg"
    assert body["pagination"]["has_more"] is True


def test_v1_video_detail_normalizes_thumbnail_from_relative_preview_path(start_json_engine, start_client_backend) -> None:
    """Single video metadata responses use the same public thumbnail contract."""
    fake_engine = start_json_engine(
        {
            ("GET", "/api/video"): lambda _record: (
                200,
                {
                    "video_id": "v1",
                    "video_uuid": "uuid-v1",
                    "instance_domain": "video.blast-info.fr",
                    "thumbnail_url": None,
                    "preview_path": "/lazy-static/previews/v1.jpg",
                },
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/videos/v1?host=video.blast-info.fr")

    assert response.status_code == 200
    body = response.json()
    assert body["thumbnail_url"] == "https://video.blast-info.fr/lazy-static/previews/v1.jpg"
    assert body["preview_path"] == "/lazy-static/previews/v1.jpg"


def test_v1_similar_normalizes_thumbnail_without_changing_pagination(start_json_engine, start_client_backend) -> None:
    """Similar list normalization must not filter rows or alter cursor behavior."""
    fake_engine = start_json_engine(
        {
            ("GET", "/videos/v1/similar"): lambda _record: (
                200,
                {
                    "rows": [
                        {
                            "video_id": "s1",
                            "video_uuid": "uuid-s1",
                            "instance_domain": "video.blast-info.fr",
                            "thumbnail_url": None,
                            "preview_path": "/lazy-static/previews/s1.jpg",
                        },
                        _row("s2"),
                    ]
                },
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/v1/videos/v1/similar?host=video.blast-info.fr&limit=1")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["thumbnail_url"] == "https://video.blast-info.fr/lazy-static/previews/s1.jpg"
    assert body["pagination"]["has_more"] is True
    assert isinstance(body["pagination"]["next_cursor"], str)
