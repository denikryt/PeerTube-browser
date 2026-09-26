"""FastAPI-native response and body helpers for Engine API routes."""
from __future__ import annotations

import json
from typing import Any

from fastapi import Request, Response

CORS_HEADERS = {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, POST, OPTIONS",
    "access-control-allow-headers": "content-type",
}
OPTIONS_HEADERS = {**CORS_HEADERS, "access-control-max-age": "600"}


def cors_json(status: int, payload: dict[str, Any]) -> Response:
    """Return a JSON response matching the Engine legacy response format."""
    return Response(
        content=json.dumps(payload, indent=2).encode("utf-8"),
        status_code=status,
        media_type="application/json; charset=utf-8",
        headers=CORS_HEADERS,
    )


def cors_options() -> Response:
    """Return the current Engine CORS preflight response."""
    return Response(status_code=204, headers=OPTIONS_HEADERS)


async def read_request_body(request: Request) -> bytes:
    """Read request bytes at the FastAPI adapter boundary."""
    return await request.body()


def read_json_body_bytes(raw: bytes, max_body_bytes: int = 1_000_000) -> dict[str, Any]:
    """Parse JSON request bytes while preserving the current Engine error contract."""
    if not raw:
        return {}
    if len(raw) > max_body_bytes:
        raise ValueError("Invalid JSON body")
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid JSON body") from exc
    if isinstance(parsed, dict):
        return parsed
    raise ValueError("Invalid JSON body")
