"""Characterize Engine FastAPI route dispatch behavior."""
from __future__ import annotations

from app import create_app
from conftest import RejectingRateLimiter, make_engine_state
from fastapi.testclient import TestClient


def test_get_unknown_route_returns_current_404(engine_client) -> None:
    """Unknown GET routes must keep the current JSON 404 contract."""
    response = engine_client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {"error": "Not found"}


def test_post_unknown_route_returns_current_404(engine_client) -> None:
    """Unknown POST routes must keep the current JSON 404 contract."""
    response = engine_client.post("/missing", json={})

    assert response.status_code == 404
    assert response.json() == {"error": "Not found"}


def test_options_preserves_current_cors_preflight(engine_client) -> None:
    """OPTIONS dispatch must continue to use the existing CORS preflight helper."""
    response = engine_client.options("/any")

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "GET, POST, OPTIONS"
    assert response.headers["access-control-max-age"] == "600"


def test_rate_limit_rejection_preserves_status_body_and_key() -> None:
    """Route dispatch must keep the current per-IP plus path rate-limit key."""
    limiter = RejectingRateLimiter()
    state = make_engine_state(rate_limiter=limiter)
    try:
        client = TestClient(create_app(state))
        response = client.get("/api/health")
    finally:
        state.db.close()

    assert limiter.key == "testclient:/api/health"
    assert response.status_code == 429
    assert response.json() == {"error": "Rate limit exceeded"}
