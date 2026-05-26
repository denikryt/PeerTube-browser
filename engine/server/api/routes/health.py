"""Health route adapter for the Engine API."""
from __future__ import annotations

from typing import Any

from http_utils import respond_json


def handle_health(handler: Any, server: Any) -> bool:
    """Write the current ``/api/health`` response from existing server state."""
    respond_json(
        handler,
        200,
        {
            "ok": True,
            "total": server.embeddings_count,
            "embeddingDim": server.embeddings_dim,
        },
    )
    return True
