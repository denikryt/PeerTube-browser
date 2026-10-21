"""Client backend Search API v1 route behavior tests."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def _query(record):
    """Parse the fake Engine request query string."""
    return parse_qs(urlparse(record["full_path"]).query)


def test_video_search_returns_v1_envelope_and_forwards_to_engine(start_json_engine, start_client_backend) -> None:
    """Public video search wraps Engine internal rows in the v1 envelope."""
    engine = start_json_engine({
        ("GET", "/internal/search/videos"): lambda record: (200, {"rows": [{"video_id": "v1", "instance_domain": "ex", "title": "Linux"}], "has_more": False, "next_cursor": None}),
    })
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    response = client.get("/api/v1/search/videos?q=linux&limit=5")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == [{"video_id": "v1", "instance_domain": "ex", "title": "Linux", "thumbnail_url": None}]
    assert payload["pagination"] == {"limit": 5, "next_cursor": None, "has_more": False}
    assert payload["meta"] == {"source": "search_videos", "query": "linux", "index": "sqlite_fts5_light"}
    assert engine.requests[0]["path"] == "/internal/search/videos"
    assert _query(engine.requests[0])["q"] == ["linux"]


def test_channel_search_wraps_existing_engine_channels_route(start_json_engine, start_client_backend) -> None:
    """Public channel search adapts Engine /api/channels rows without changing legacy route."""
    engine = start_json_engine({
        ("GET", "/api/channels"): lambda record: (200, {"rows": [{"channel_id": "c1", "channel_name": "linux", "instance_domain": "ex"}], "total": 1}),
    })
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    response = client.get("/api/v1/search/channels?q=linux")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["channel_id"] == "c1"
    assert payload["meta"] == {"source": "search_channels", "query": "linux"}
    assert engine.requests[0]["path"] == "/api/channels"


def test_search_validation_and_engine_errors_are_controlled(start_json_engine, start_client_backend) -> None:
    """Empty q and upstream failures become v1 error payloads."""
    engine = start_json_engine({
        ("GET", "/internal/search/videos"): lambda record: (503, {"error": "index missing"}),
    })
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    bad = client.get("/api/v1/search/videos?q=%20%20")
    assert bad.status_code == 400
    assert bad.json()["code"] == "V1_SEARCH_BAD_REQUEST"
    unavailable = client.get("/api/v1/search/videos?q=linux")
    assert unavailable.status_code == 502
    assert unavailable.json()["code"] == "V1_SEARCH_ENGINE_UNAVAILABLE"


def test_search_cursors_are_endpoint_scoped(start_json_engine, start_client_backend) -> None:
    """A channel cursor cannot be reused for video search."""
    engine = start_json_engine({
        ("GET", "/api/channels"): lambda record: (200, {"rows": [{"channel_id": str(i), "instance_domain": "ex"} for i in range(22)], "total": 22}),
    })
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    channel_page = client.get("/api/v1/search/channels?q=linux&limit=20").json()
    cursor = channel_page["pagination"]["next_cursor"]
    assert cursor
    bad = client.get(f"/api/v1/search/videos?q=linux&cursor={cursor}")
    assert bad.status_code == 400


def test_video_search_normalizes_thumbnail_from_relative_preview_path(start_json_engine, start_client_backend) -> None:
    """Video search rows expose canonical browser image URLs through thumbnail_url."""
    engine = start_json_engine(
        {
            ("GET", "/internal/search/videos"): lambda _record: (
                200,
                {
                    "rows": [
                        {
                            "video_id": "v1",
                            "video_uuid": "uuid-v1",
                            "instance_domain": "video.blast-info.fr",
                            "thumbnail_url": None,
                            "preview_path": "/lazy-static/previews/v1.jpg",
                        }
                    ]
                },
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")

    response = client.get("/api/v1/search/videos?q=linux")

    assert response.status_code == 200
    row = response.json()["items"][0]
    assert row["thumbnail_url"] == "https://video.blast-info.fr/lazy-static/previews/v1.jpg"
    assert row["preview_path"] == "/lazy-static/previews/v1.jpg"


def test_channel_search_does_not_add_video_thumbnail_fields(start_json_engine, start_client_backend) -> None:
    """Channel search rows must not be passed through video row shaping."""
    engine = start_json_engine(
        {
            ("GET", "/api/channels"): lambda _record: (
                200,
                {"rows": [{"channel_id": "c1", "channel_name": "linux", "instance_domain": "ex"}], "total": 1},
            )
        }
    )
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")

    response = client.get("/api/v1/search/channels?q=linux")

    assert response.status_code == 200
    row = response.json()["items"][0]
    assert "thumbnail_url" not in row
    assert row["channel_id"] == "c1"
