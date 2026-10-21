"""Thin Engine video-route service wrapper.

FastAPI response-helper cleanup keeps DB lookup and dynamic PeerTube metadata overlay in
``handlers.video`` while making the route boundary framework-neutral.
"""
from __future__ import annotations

from typing import Any

from handlers.video import handle_video_request
from route_results import RouteResult


def handle_video(server: Any, params: dict[str, list[str]]) -> RouteResult:
    """Delegate video metadata route handling to the existing video helper."""
    return handle_video_request(server, params)
