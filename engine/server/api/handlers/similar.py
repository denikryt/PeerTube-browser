"""Stdlib HTTP adapter and router for the Engine read surface.

Stage 4 keeps ``BaseHTTPRequestHandler`` ownership here while route-specific
request parsing and recommendation execution live in ``routes`` and
``services`` modules. This module intentionally preserves request logging,
CORS, rate-limit keys, and route dispatch semantics for the existing Engine API.
"""
from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

from http_utils import respond_json, respond_options
from routes.channels import handle_channels
from routes.health import handle_health
from routes.internal_events import handle_internal_events_ingest_route
from routes.internal_videos import (
    handle_internal_video_resolve_route,
    handle_internal_videos_metadata_route,
)
from routes.recommendations import (
    extract_video_id_from_similar_path,
    handle_similar_get,
    handle_similar_post,
)
from routes.videos import handle_video_route

try:
    from engine.server.api.services.recommendation_service import (
        _extract_video_id_from_similar_path,
        _parse_bool,
        _parse_client_likes,
        _parse_int,
        _parse_non_negative_int,
        _recommendations_likes_payload_error,
        _resolve_client_likes,
        maybe_attach_debug,
        stable_video_row,
        stable_video_rows,
    )
except ModuleNotFoundError:  # pragma: no cover - direct server.py execution path
    from services.recommendation_service import (
        _extract_video_id_from_similar_path,
        _parse_bool,
        _parse_client_likes,
        _parse_int,
        _parse_non_negative_int,
        _recommendations_likes_payload_error,
        _resolve_client_likes,
        maybe_attach_debug,
        stable_video_row,
        stable_video_rows,
    )


SIMILAR_POST_ROUTES = {"/recommendations", "/videos/similar"}

__all__ = [
    "SIMILAR_POST_ROUTES",
    "SimilarHandler",
    "_extract_video_id_from_similar_path",
    "_parse_bool",
    "_parse_client_likes",
    "_parse_int",
    "_parse_non_negative_int",
    "_recommendations_likes_payload_error",
    "_resolve_client_likes",
    "maybe_attach_debug",
    "stable_video_row",
    "stable_video_rows",
]



class SimilarHandler(BaseHTTPRequestHandler):
    """HTTP handler for Engine read endpoints and bridge ingest dispatch."""

    def _get_client_ip(self) -> str:
        """Resolve client IP behind reverse proxy headers when available."""
        forwarded_for = self.headers.get("X-Forwarded-For", "").strip()
        if forwarded_for:
            first = forwarded_for.split(",", 1)[0].strip()
            if first:
                return first
        real_ip = self.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
        if self.client_address:
            return self.client_address[0]
        return "unknown"

    def _get_full_url(self) -> str:
        """Build absolute URL from forwarded headers and request path."""
        host = self.headers.get("Host", "").strip()
        if not host:
            return self.path
        proto = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip() or "http"
        return f"{proto}://{host}{self.path}"

    def _log_access_start(self) -> None:
        """Emit request-start access line before request processing begins."""
        logging.info(
            "[access.start] ip=%s method=%s url=%s",
            self._get_client_ip(),
            self.command or "-",
            self._get_full_url(),
        )

    def log_message(self, format: str, *args: Any) -> None:
        """Emit structured access logs with real client IP and full URL."""
        status = args[1] if len(args) > 1 else "-"
        size = args[2] if len(args) > 2 else "-"
        logging.info(
            "[access] ip=%s method=%s url=%s status=%s bytes=%s",
            self._get_client_ip(),
            self.command or "-",
            self._get_full_url(),
            status,
            size,
        )

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight through the existing response helper."""
        self._log_access_start()
        respond_options(self)

    def do_POST(self) -> None:  # noqa: N802
        """Route Engine POST endpoints while preserving current rate-limit behavior."""
        self._log_access_start()
        url = urlparse(self.path)
        params = parse_qs(url.query)
        if url.path in SIMILAR_POST_ROUTES:
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            handle_similar_post(self, self.server, url.path, params)
            return
        if url.path == "/internal/videos/resolve":
            handle_internal_video_resolve_route(self, self.server)
            return
        if url.path == "/internal/videos/metadata":
            handle_internal_videos_metadata_route(self, self.server)
            return
        if url.path == "/internal/events/ingest":
            handle_internal_events_ingest_route(self, self.server)
            return
        respond_json(self, 404, {"error": "Not found"})

    def do_GET(self) -> None:  # noqa: N802
        """Route Engine GET endpoints while preserving current adapter responsibilities."""
        self._log_access_start()
        url = urlparse(self.path)
        if url.path.startswith("/api/") and not self._rate_limit_check(url.path):
            respond_json(self, 429, {"error": "Rate limit exceeded"})
            return
        if url.path == "/api/health":
            handle_health(self, self.server)
            return

        params = parse_qs(url.query)
        if url.path == "/api/channels":
            handle_channels(self, self.server, params)
            return

        if url.path == "/api/video":
            handle_video_route(self, self.server, params)
            return

        if extract_video_id_from_similar_path(url.path) is not None:
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            handle_similar_get(self, self.server, url.path, params)
            return

        respond_json(self, 404, {"error": "Not found"})

    def _rate_limit_check(self, path: str) -> bool:
        """Check the existing per-IP rate-limit key for a route path."""
        limiter = getattr(self.server, "rate_limiter", None)
        if limiter is None:
            return True
        ip = self._get_client_ip()
        key = f"{ip}:{path}"
        return limiter.allow(key)
