"""Characterize Client read proxy behavior through fake Engine HTTP routes."""
from __future__ import annotations


def test_video_availability_recovery_forwards_404_then_200(
    start_json_engine, start_client_backend
) -> None:
    """One Client and URL preserve Engine status/body before and after recovery.

    The fake replaces only the Engine HTTP boundary: publisher and canonical
    transitions are covered by Engine lifecycle tests, not owned by Client.
    """
    missing = {"error": "Video not found"}
    recovered = {
        "video_id": "123", "video_uuid": "uuid-123",
        "instance_domain": "example.org", "videoUuid": "uuid-123",
        "title": "Recovered video", "description": "",
        "thumbnail_url": None, "thumbnail_urls": [], "preview_path": None,
        "views": 0, "likes": 0, "publishedAt": None,
    }
    upstream = {"status": 404, "payload": missing}

    def engine_video(_request):
        """Expose the current availability through the same upstream HTTP route."""
        return upstream["status"], upstream["payload"]

    engine = start_json_engine({("GET", "/api/video"): engine_video})
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    url = "/api/video?id=123&host=example.org"
    absent = client.get(url)
    assert absent.status_code == 404
    assert absent.json() == missing
    # Recovery keeps the Client and identity, detecting cached or reshaped responses.
    upstream.update(status=200, payload=recovered)
    available = client.get(url)
    assert available.status_code == 200
    assert available.json() == recovered
    assert [request["full_path"] for request in engine.requests] == [url, url]


def test_get_api_video_rejects_unknown_query_parameter(
    start_json_engine, start_client_backend
) -> None:
    """Unknown read query parameters must not become accidental public API surface."""
    fake_engine = start_json_engine(
        {
            ("GET", "/api/video"): lambda _record: (
                200,
                {"video": {"video_id": "123", "title": "Example"}},
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/video?id=123&host=example.org&unknown=x")
    status, body = response.status_code, response.json()

    assert status == 400
    assert body == {"error": "Unknown query parameter: unknown"}
    assert fake_engine.requests == []


def test_get_api_video_forwards_allowlisted_query_parameters(
    start_json_engine, start_client_backend
) -> None:
    """Allowlisted read query parameters must be forwarded to Engine unchanged."""
    fake_engine = start_json_engine(
        {
            ("GET", "/api/video"): lambda _record: (
                200,
                {"video": {"video_id": "123", "title": "Example"}},
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.get("/api/video?id=123&host=example.org")
    status, body = response.status_code, response.json()

    assert status == 200
    assert body == {"video": {"video_id": "123", "title": "Example"}}
    assert fake_engine.requests[0]["full_path"] == "/api/video?id=123&host=example.org"


def test_post_recommendations_forwards_sanitized_body(
    start_json_engine, start_client_backend
) -> None:
    """Recommendations proxy must forward only current allowed keys and sanitized likes."""
    fake_engine = start_json_engine(
        {
            ("POST", "/recommendations"): lambda _record: (
                200,
                {"generatedAt": 1, "total": 0, "count": 0, "seed": None, "rows": []},
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.post(
        "/recommendations",
        json={
            "likes": [{"uuid": "uuid-1", "host": "example.org"}],
            "user_id": "local-user",
            "mode": "home",
        },
    )
    status, body = response.status_code, response.json()

    assert status == 200
    assert body == {"generatedAt": 1, "total": 0, "count": 0, "seed": None, "rows": []}
    assert fake_engine.requests[0]["path"] == "/recommendations"
    assert fake_engine.requests[0]["body"] == {
        "likes": [{"uuid": "uuid-1", "host": "example.org"}],
        "user_id": "local-user",
        "mode": "home",
    }


def test_post_recommendations_trims_likes_to_engine_limit(start_json_engine, start_client_backend) -> None:
    """Legacy recommendations proxy must not exceed the Engine recommendations likes contract."""
    fake_engine = start_json_engine(
        {
            ("POST", "/recommendations"): lambda _record: (
                200,
                {"generatedAt": 1, "total": 0, "count": 0, "seed": None, "rows": []},
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")
    likes = [{"uuid": f"uuid-{index}", "host": "example.org"} for index in range(15)]

    response = client.post(
        "/recommendations",
        json={"likes": likes, "user_id": "local-user", "mode": "home"},
    )

    assert response.status_code == 200
    assert len(fake_engine.requests[0]["body"]["likes"]) == 5
    assert fake_engine.requests[0]["body"]["likes"] == likes[:5]


def test_post_recommendations_rejects_unknown_body_field(
    start_json_engine, start_client_backend
) -> None:
    """Unknown body fields should fail before the request reaches Engine."""
    fake_engine = start_json_engine({("POST", "/recommendations"): lambda _record: (200, {})})
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    response = client.post("/recommendations", json={"likes": [], "unexpected": True})
    status, body = response.status_code, response.json()

    assert status == 400
    assert body == {"error": "Unknown body field: unexpected"}
    assert fake_engine.requests == []
