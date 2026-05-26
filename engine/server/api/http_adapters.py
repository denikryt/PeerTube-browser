"""FastAPI compatibility helpers for Engine API routes.

These helpers emulate the small subset of the transitional stdlib handler used by
existing Engine route modules. Stage 10 keeps route/service code behavior stable
while replacing the active HTTP framework.
"""
from __future__ import annotations

import io
import json
from email.message import Message
from typing import Any

from fastapi import Request, Response

CORS_HEADERS = {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, POST, OPTIONS",
    "access-control-allow-headers": "content-type",
}
OPTIONS_HEADERS = {**CORS_HEADERS, "access-control-max-age": "600"}


class FastAPIHandlerAdapter:
    """Capture legacy handler responses for FastAPI route wrappers."""

    def __init__(self, request: Request, server: Any, body: bytes = b"") -> None:
        """Create a handler-like object with request metadata and body streams."""
        self.request = request
        self.server = server
        self.path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        self.command = request.method
        self.client_address = ((request.client.host if request.client else "unknown"), 0)
        self.headers = Message()
        for key, value in request.headers.items():
            self.headers[key] = value
        self.headers["content-length"] = str(len(body))
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status = 200
        self.response_headers: list[tuple[str, str]] = []

    def send_response(self, status: int) -> None:
        """Capture the status written by legacy response helpers."""
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        """Capture response headers written by legacy response helpers."""
        self.response_headers.append((key.lower(), value))

    def end_headers(self) -> None:
        """Preserve the legacy handler interface."""
        return

    def _get_client_ip(self) -> str:
        """Resolve client IP using the current Engine forwarded-header order."""
        forwarded_for = self.headers.get("X-Forwarded-For", "").strip()
        if forwarded_for:
            first = forwarded_for.split(",", 1)[0].strip()
            if first:
                return first
        real_ip = self.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
        return self.client_address[0] if self.client_address else "unknown"

    def _get_full_url(self) -> str:
        """Return a stable full URL for compatibility logging helpers."""
        host = self.headers.get("Host", "").strip()
        if not host:
            return self.path
        proto = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip() or "http"
        return f"{proto}://{host}{self.path}"

    def _log_access_start(self) -> None:
        """No-op hook kept for compatibility with route-service tests."""
        return

    def _rate_limit_check(self, path: str) -> bool:
        """Use the current Engine per-IP plus path rate-limit key."""
        limiter = getattr(self.server, "rate_limiter", None)
        if limiter is None:
            return True
        return limiter.allow(f"{self._get_client_ip()}:{path}")


def adapter_response(handler: FastAPIHandlerAdapter) -> Response:
    """Convert a captured legacy handler response to a FastAPI response."""
    headers = {key: value for key, value in handler.response_headers if key != "content-length"}
    content_type = headers.pop("content-type", "application/json; charset=utf-8")
    handler.wfile.seek(0)
    return Response(
        content=handler.wfile.read(),
        status_code=handler.status,
        media_type=content_type,
        headers=headers,
    )


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
