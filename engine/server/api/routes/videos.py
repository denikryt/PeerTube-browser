"""Video metadata route result builder for the Engine API."""
from __future__ import annotations

from typing import Any

try:
    from engine.server.api.services.video_service import handle_video
except ModuleNotFoundError:  # pragma: no cover - direct server.py execution path
    from services.video_service import handle_video
from route_results import RouteResult


def handle_video_route(server: Any, params: dict[str, list[str]]) -> RouteResult:
    """Delegate ``/api/video`` to the compatibility-preserving video service."""
    return handle_video(server, params)
