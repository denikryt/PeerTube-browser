"""Internal Client video-read route adapters for the Engine API."""
from __future__ import annotations

from typing import Any

from handlers.internal_client_reads import (
    handle_internal_video_resolve,
    handle_internal_videos_metadata,
)


def handle_internal_video_resolve_route(handler: Any, server: Any) -> bool:
    """Delegate internal identity resolution to the existing handler."""
    return handle_internal_video_resolve(handler, server)


def handle_internal_videos_metadata_route(handler: Any, server: Any) -> bool:
    """Delegate internal metadata reads to the existing handler."""
    return handle_internal_videos_metadata(handler, server)
