"""Internal Engine search route adapters."""
from __future__ import annotations

from typing import Any

from route_results import RouteResult

try:
    from engine.server.api.services.search_service import handle_internal_video_search
except ModuleNotFoundError:  # pragma: no cover - direct server.py execution path.
    from services.search_service import handle_internal_video_search


def handle_internal_search_videos_route(server: Any, params: dict[str, list[str]]) -> RouteResult:
    """Route internal video search requests through the search service."""
    return handle_internal_video_search(server, params)
