"""Internal Engine video-facet route adapter."""
from __future__ import annotations

from typing import Any

try:
    from engine.server.api.services.video_filter_service import handle_internal_video_facets
except ModuleNotFoundError:  # pragma: no cover - direct server.py execution path
    from services.video_filter_service import handle_internal_video_facets

from route_results import RouteResult


def handle_internal_video_facets_route(server: Any) -> RouteResult:
    """Delegate the global service-visible facet resource to its service owner."""
    return handle_internal_video_facets(server)
