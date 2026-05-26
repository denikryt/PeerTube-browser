"""Channel listing route adapter for the Engine API."""
from __future__ import annotations

from typing import Any

from data.time import now_ms
from http_utils import respond_json

try:
    from engine.server.api.services.channel_service import fetch_channel_rows, parse_channel_query
except ModuleNotFoundError:  # pragma: no cover - direct server.py execution path
    from services.channel_service import fetch_channel_rows, parse_channel_query


def handle_channels(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    """Parse channel query params and return the current channel-list response."""
    query = parse_channel_query(params)
    rows, total = fetch_channel_rows(server, query)
    respond_json(
        handler,
        200,
        {
            "generatedAt": now_ms(),
            "total": total,
            "rows": rows,
        },
    )
    return True
