"""HTTP and request utilities for Client backend."""
from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any

DEFAULT_USER_ID = "local-user"


def resolve_user_id(raw: str | None) -> str:
    """Normalize user id input and fall back to the default id."""
    if isinstance(raw, str):
        value = raw.strip()
        if value:
            return value
    return DEFAULT_USER_ID


def respond_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    """Send a JSON response with CORS headers."""
    body = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("access-control-allow-origin", "*")
    handler.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
    handler.send_header("access-control-allow-headers", "content-type")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def respond_options(handler: BaseHTTPRequestHandler) -> None:
    """Respond to CORS preflight requests."""
    handler.send_response(204)
    handler.send_header("access-control-allow-origin", "*")
    handler.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
    handler.send_header("access-control-allow-headers", "content-type")
    handler.send_header("access-control-max-age", "600")
    handler.end_headers()


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    """Read and parse a JSON request body with size limits."""
    length = handler.headers.get("content-length")
    size = int(length or "0")
    if size <= 0:
        return {}
    if size > 1_000_000:
        raise ValueError("Invalid JSON body")
    raw = handler.rfile.read(size).decode("utf-8")
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON body") from exc
    if isinstance(parsed, dict):
        return parsed
    raise ValueError("Invalid JSON body")


class RateLimiter:
    """Simple in-memory rate limiter by key and time window."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        """Initialize the instance."""
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.lock = threading.Lock()
        self.requests: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Handle allow."""
        if self.max_requests <= 0 or self.window_seconds <= 0:
            return True
        now = datetime.now(timezone.utc).timestamp()
        with self.lock:
            bucket = self.requests.get(key)
            if bucket is None:
                bucket = deque()
                self.requests[key] = bucket
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True
