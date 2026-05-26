"""FastAPI compatibility helpers for Client backend HTTP behavior.

The helpers in this module mirror the small pieces of behavior that used to be
owned by ``BaseHTTPRequestHandler``: CORS headers, client IP resolution,
manual JSON-body parsing, and response-byte preservation. They deliberately do
not introduce Pydantic validation so existing error bodies and status codes stay
stable during framework migration.
"""
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


def resolve_client_ip(request: Request) -> str:
    """Resolve client IP using the current forwarded-header order."""
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for:
        first = forwarded_for.split(",", 1)[0].strip()
        if first:
            return first
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    if request.client:
        return request.client.host
    return "unknown"


def rate_limit_key(request: Request, path: str) -> str:
    """Build the existing per-IP plus path rate-limit key."""
    return f"{resolve_client_ip(request)}:{path}"


def cors_json(status: int, payload: dict[str, Any]) -> Response:
    """Return a JSON response with the legacy pretty-printed body and CORS headers."""
    body = json.dumps(payload, indent=2).encode("utf-8")
    return Response(
        content=body,
        status_code=status,
        media_type="application/json; charset=utf-8",
        headers=CORS_HEADERS,
    )


def cors_bytes(status: int, payload: bytes, content_type: str) -> Response:
    """Return upstream bytes without changing content type or status."""
    return Response(
        content=payload,
        status_code=status,
        media_type=content_type,
        headers=CORS_HEADERS,
    )


def cors_options() -> Response:
    """Return the current CORS preflight response."""
    return Response(status_code=204, headers=OPTIONS_HEADERS)


async def read_json_body(request: Request, max_body_bytes: int = 1_000_000) -> dict[str, Any]:
    """Read and parse request JSON with the current Client error contract."""
    raw = await request.body()
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
