"""Characterize Client read proxy behavior through fake Engine HTTP routes."""
from __future__ import annotations


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
