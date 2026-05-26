"""Internal event-ingest route adapter for the Engine API."""
from __future__ import annotations

from typing import Any

from handlers.internal_events import handle_internal_events_ingest
from http_utils import respond_json


def handle_internal_events_ingest_route(handler: Any, server: Any) -> bool:
    """Preserve the ingest-mode gate before delegating to bridge ingest."""
    mode = getattr(server, "engine_ingest_mode", "bridge")
    if mode != "bridge":
        respond_json(
            handler,
            501,
            {
                "error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE",
                "mode": mode,
            },
        )
        return True
    return handle_internal_events_ingest(handler, server)
