"""Thin Engine video-route service wrapper.

Stage 4 keeps DB lookup and dynamic PeerTube metadata overlay in
``handlers.video``. This wrapper exists only to make the route/service boundary
explicit without changing the current video response contract.
"""
from __future__ import annotations

from typing import Any

from handlers.video import handle_video_request


def handle_video(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    """Delegate to the existing video handler to preserve response behavior."""
    return handle_video_request(handler, server, params)
