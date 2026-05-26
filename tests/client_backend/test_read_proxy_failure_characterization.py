"""Characterize Client read-proxy failure handling."""
from __future__ import annotations

import socket


def _unused_local_port() -> int:
    """Reserve and release a local port so the next connection is refused quickly."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_proxy_preserves_engine_http_error_payload(start_json_engine, start_client_backend, http_json) -> None:
    """Engine HTTP errors with payloads must pass through status and body."""
    fake_engine = start_json_engine(
        {("GET", "/api/video"): lambda _record: (503, {"error": "engine unavailable"})}
    )
    client = start_client_backend(f"http://127.0.0.1:{fake_engine.server_port}")

    status, body = http_json(
        "GET",
        f"http://127.0.0.1:{client.server_port}/api/video?id=123&host=example.org",
    )

    assert status == 503
    assert body == {"error": "engine unavailable"}


def test_proxy_transport_failure_returns_current_unavailable_shape(start_client_backend, http_json) -> None:
    """A refused Engine connection must remain a controlled proxy-unavailable error."""
    port = _unused_local_port()
    client = start_client_backend(f"http://127.0.0.1:{port}")

    status, body = http_json(
        "GET",
        f"http://127.0.0.1:{client.server_port}/api/video?id=123&host=example.org",
    )

    assert status == 502
    assert body["error"] == "Engine read proxy failed"
    assert body["code"] == "ENGINE_PROXY_UNAVAILABLE"
    assert body["detail"]
