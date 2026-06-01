"""Internal Engine discovery provider route adapters."""
from __future__ import annotations

from typing import Any

try:
    from engine.server.api.services.discovery_service import handle_internal_discovery
except ModuleNotFoundError:  # pragma: no cover - direct server.py execution path
    from services.discovery_service import handle_internal_discovery
from route_results import RouteResult


def handle_internal_discovery_route(
    server: Any,
    source: str,
    params: dict[str, list[str]],
) -> RouteResult:
    """Delegate internal discovery provider route handling."""
    return handle_internal_discovery(server, source, params)
