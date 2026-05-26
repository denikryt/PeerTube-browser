"""FastAPI contract tests for the Client backend adapter."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "backend"))

import app as client_app  # noqa: E402
import services.user_actions as user_actions  # noqa: E402
from app import create_app  # noqa: E402
from lib.http_utils import RateLimiter  # noqa: E402
from lib.users_store import ensure_user_schema  # noqa: E402
from repositories.users import UsersRepository  # noqa: E402
from runtime import ClientRuntimeState  # noqa: E402


class FakeProxyResult:
    """Small stand-in for Engine proxy byte results when monkeypatching."""

    def __init__(self, status: int, payload: bytes, content_type: str) -> None:
        """Store the upstream status, bytes, and content type."""
        self.status = status
        self.payload = payload
        self.content_type = content_type


def make_client() -> tuple[TestClient, sqlite3.Connection, ClientRuntimeState]:
    """Create a Client FastAPI TestClient with temporary profile storage."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    ensure_user_schema(conn)
    state = ClientRuntimeState(
        user_db=conn,
        users=UsersRepository(conn),
        engine_ingest_base="http://engine.test",
        publish_mode="bridge",
        rate_limiter=RateLimiter(10_000, 60),
    )
    return TestClient(create_app(state)), conn, state


def test_client_fastapi_health_and_options_contract() -> None:
    """Client FastAPI health and CORS preflight keep the existing payloads."""
    client, conn, _state = make_client()
    try:
        response = client.get("/api/health")
        options = client.options("/api/health")
    finally:
        conn.close()

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "client-backend",
        "engine_ingest_base": "http://engine.test",
        "publish_mode": "bridge",
    }
    assert options.status_code == 204
    assert options.headers["access-control-allow-origin"] == "*"


def test_client_fastapi_profile_and_reset_contract() -> None:
    """Profile reads and resets keep the Client-owned DB behavior."""
    client, conn, _state = make_client()
    try:
        conn.execute(
            """
            INSERT INTO likes(user_id, video_id, video_uuid, instance_domain, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("local-user", "123", "uuid-123", "example.org", 1000),
        )
        conn.commit()
        profile = client.get("/api/user-profile")
        reset = client.post("/api/user-profile/reset", json={"user_id": "local-user"})
        count = conn.execute("SELECT COUNT(*) FROM likes").fetchone()[0]
    finally:
        conn.close()

    assert profile.status_code == 200
    assert profile.json()["likes"][0]["video_id"] == "123"
    assert reset.status_code == 200
    assert reset.json()["likes"] == []
    assert count == 0


def test_client_fastapi_user_action_like_and_bridge_failure(monkeypatch) -> None:
    """User action behavior keeps local persistence and bridge failure semantics."""
    client, conn, _state = make_client()

    def fake_resolve(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        """Return the canonical Engine identity expected by user action service."""
        return {
            "video_id": "123",
            "video_uuid": "uuid-123",
            "instance_domain": "example.org",
            "video_url": "https://example.org/w/uuid-123",
        }

    def fake_publish(_mode: str, _base: str, _payload: dict[str, Any]) -> dict[str, Any]:
        """Emulate current bridge failure while the local like is already stored."""
        return {"ok": False, "error": "boom"}

    monkeypatch.setattr(user_actions, "resolve_video_seed", fake_resolve)
    monkeypatch.setattr(user_actions, "publish_event", fake_publish)
    try:
        response = client.post(
            "/api/user-action",
            json={"action": "like", "uuid": "uuid-123", "host": "example.org"},
        )
        count = conn.execute("SELECT COUNT(*) FROM likes WHERE video_id = '123'").fetchone()[0]
    finally:
        conn.close()

    assert response.status_code == 502
    assert response.json()["bridge_ok"] is False
    assert count == 1


def test_client_fastapi_proxy_preserves_upstream_bytes(monkeypatch) -> None:
    """Client read proxy returns the Engine status, bytes, and content type."""
    client, conn, _state = make_client()

    def fake_proxy(*_args: Any, **_kwargs: Any) -> Any:
        """Return the same proxy result shape as the real gateway service."""
        from schemas import ProxyBytesResult

        return ProxyBytesResult(202, b'{"ok": true}', "application/custom-json")

    monkeypatch.setattr(client_app, "proxy_engine_request", fake_proxy)
    try:
        response = client.get("/api/video?id=123")
    finally:
        conn.close()

    assert response.status_code == 202
    assert response.content == b'{"ok": true}'
    assert response.headers["content-type"].startswith("application/custom-json")


def test_client_fastapi_rate_limit_key_and_status() -> None:
    """Client FastAPI adapter keeps the current per-IP plus path rate-limit key."""
    client, conn, state = make_client()
    state.rate_limiter = RateLimiter(0, 60)
    try:
        response = client.get("/api/user-profile")
    finally:
        conn.close()

    assert response.status_code == 200

    client, conn, state = make_client()
    state.rate_limiter = RateLimiter(1, 60)
    try:
        first = client.get("/api/user-profile")
        second = client.get("/api/user-profile")
    finally:
        conn.close()

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json() == {"error": "Rate limit exceeded"}
