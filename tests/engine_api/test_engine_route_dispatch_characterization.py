"""Characterize Engine route dispatch owned by SimilarHandler."""
from __future__ import annotations

from types import SimpleNamespace

from conftest import RejectingRateLimiter, RouteCapturingHandler, import_similar_handler_module


def test_get_unknown_route_returns_current_404(monkeypatch) -> None:
    """Unknown GET routes must keep the current JSON 404 contract."""
    similar = import_similar_handler_module(monkeypatch)
    handler = RouteCapturingHandler("/missing")

    similar.SimilarHandler.do_GET(handler)

    assert handler.status == 404
    assert handler.parsed_body() == {"error": "Not found"}


def test_post_unknown_route_returns_current_404(monkeypatch) -> None:
    """Unknown POST routes must keep the current JSON 404 contract."""
    similar = import_similar_handler_module(monkeypatch)
    handler = RouteCapturingHandler("/missing", method="POST")

    similar.SimilarHandler.do_POST(handler)

    assert handler.status == 404
    assert handler.parsed_body() == {"error": "Not found"}


def test_options_preserves_current_cors_preflight(monkeypatch) -> None:
    """OPTIONS dispatch must continue to use the existing CORS preflight helper."""
    similar = import_similar_handler_module(monkeypatch)
    handler = RouteCapturingHandler("/any", method="OPTIONS")

    similar.SimilarHandler.do_OPTIONS(handler)

    assert handler.status == 204
    assert ("access-control-allow-origin", "*") in handler.response_headers
    assert ("access-control-allow-methods", "GET, POST, OPTIONS") in handler.response_headers
    assert ("access-control-max-age", "600") in handler.response_headers


def test_rate_limit_rejection_preserves_status_body_and_key(monkeypatch) -> None:
    """Route dispatch must keep the current per-IP plus path rate-limit key."""
    similar = import_similar_handler_module(monkeypatch)
    limiter = RejectingRateLimiter()
    server = SimpleNamespace(rate_limiter=limiter)
    handler = RouteCapturingHandler("/api/health", server=server)

    similar.SimilarHandler.do_GET(handler)

    assert limiter.key == "127.0.0.1:/api/health"
    assert handler.status == 429
    assert handler.parsed_body() == {"error": "Rate limit exceeded"}
