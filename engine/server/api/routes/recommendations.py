"""Recommendation and similar-route adapters for the Engine API."""
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

def extract_video_id_from_similar_path(path: str) -> str | None:
    """Expose the legacy path-id extraction rule for route dispatch and tests."""
    return _extract_video_id_from_similar_path(path)


def handle_similar_post(
    handler: Any,
    server: Any,
    path: str,
    params: dict[str, list[str]],
) -> bool:
    """Handle ``/recommendations`` and ``/videos/similar`` POST requests."""
    handle_similar_request(handler, server, path, "POST", params)
    return True


def handle_similar_get(
    handler: Any,
    server: Any,
    path: str,
    params: dict[str, list[str]],
) -> bool:
    """Handle ``/videos/{id}/similar`` while preserving path-id injection."""
    video_path_id = extract_video_id_from_similar_path(path)
    if video_path_id is None:
        return False
    params.setdefault("id", [video_path_id])
    handle_similar(handler, server, params)
    return True
