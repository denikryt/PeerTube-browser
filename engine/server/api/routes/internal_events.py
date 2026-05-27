"""Internal event-ingest route result builder for the Engine API."""
from __future__ import annotations

from typing import Any

from handlers.internal_events import handle_internal_events_ingest
from route_results import RouteResult


def handle_internal_events_ingest_route(server: Any, body: dict[str, Any]) -> RouteResult:
    """Preserve the ingest-mode gate before delegating to bridge ingest."""
    mode = getattr(server, "engine_ingest_mode", "bridge")
    if mode != "bridge":
        return RouteResult(
            501,
            {
                "error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE",
                "mode": mode,
            },
        )
    return handle_internal_events_ingest(server, body)
