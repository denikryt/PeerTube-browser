"""Internal Client video-read route result builders for the Engine API."""
from __future__ import annotations

from typing import Any

from handlers.internal_client_reads import (
    handle_internal_video_resolve,
    handle_internal_videos_metadata,
)
from route_results import RouteResult


def handle_internal_video_resolve_route(server: Any, body: dict[str, Any]) -> RouteResult:
    """Resolve internal video identity through the current data helper."""
    return handle_internal_video_resolve(server, body)


def handle_internal_videos_metadata_route(server: Any, body: dict[str, Any]) -> RouteResult:
    """Return internal batch metadata through the current data helper."""
    return handle_internal_videos_metadata(server, body)
