"""Recommendation and similar-route result builders for the Engine API."""
from __future__ import annotations

from typing import Any

try:
    from engine.server.api.services.recommendation_service import (
        _extract_video_id_from_similar_path,
        handle_similar,
        handle_similar_request,
    )
except ModuleNotFoundError:  # pragma: no cover - direct server.py execution path
    from services.recommendation_service import (
        _extract_video_id_from_similar_path,
        handle_similar,
        handle_similar_request,
    )
from route_results import RouteResult


def extract_video_id_from_similar_path(path: str) -> str | None:
    """Expose the legacy path-id extraction rule for route dispatch and tests."""
    return _extract_video_id_from_similar_path(path)


def handle_similar_post(
    server: Any,
    path: str,
    params: dict[str, list[str]],
    body: dict[str, Any],
) -> RouteResult:
    """Handle ``/recommendations`` and ``/videos/similar`` POST requests."""
    return handle_similar_request(server, path, "POST", params, body)


def handle_similar_get(
    server: Any,
    path: str,
    params: dict[str, list[str]],
) -> RouteResult:
    """Handle ``/videos/{id}/similar`` while preserving path-id injection."""
    video_path_id = extract_video_id_from_similar_path(path)
    if video_path_id is None:
        return RouteResult(404, {"error": "Not found"})
    params.setdefault("id", [video_path_id])
    return handle_similar(server, params)
