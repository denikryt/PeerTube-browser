"""Health route result builder for the Engine API."""
from __future__ import annotations

from typing import Any

from route_results import RouteResult


def handle_health(server: Any) -> RouteResult:
    """Return the current ``/api/health`` status and payload from server state."""
    return RouteResult(
        200,
        {
            "ok": True,
            "total": server.embeddings_count,
            "embeddingDim": server.embeddings_dim,
        },
    )
