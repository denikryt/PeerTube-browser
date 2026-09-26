"""Client public global video-facet proxy contract tests."""
from __future__ import annotations


def test_public_video_facets_forwards_engine_payload(start_json_engine, start_client_backend) -> None:
    """Facet payload remains a separate resource from feed/search pagination."""
    payload = {"languages": [{"value":"uk","label":"Ukrainian","count":2}], "categories": [], "tags": [], "instances": [], "coverage": {"language": {"known":2,"unknown":0,"total":2,"ratio":1.0}}, "meta": {"dynamic":False,"tag_limit":100,"instance_limit":100}}
    engine = start_json_engine({("GET", "/internal/video-facets"): lambda _record: (200, payload)})
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    response = client.get("/api/v1/video-facets")
    assert response.status_code == 200
    assert response.json() == payload


def test_public_video_facets_failure_is_controlled(start_json_engine, start_client_backend) -> None:
    """Facet failure is isolated and exposed as its own gateway error."""
    engine = start_json_engine({("GET", "/internal/video-facets"): lambda _record: (503, {"error":"db busy"})})
    client = start_client_backend(f"http://127.0.0.1:{engine.server_port}")
    response = client.get("/api/v1/video-facets")
    assert response.status_code == 502
    assert response.json()["code"] == "V1_VIDEO_FACETS_ENGINE_UNAVAILABLE"
