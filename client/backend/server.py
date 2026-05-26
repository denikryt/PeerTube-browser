#!/usr/bin/env python3
"""Client backend HTTP entrypoint and route adapter."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import uvicorn
from app import create_app
from lib.http_utils import (
    RateLimiter,
    read_json_body,
    resolve_user_id,
    respond_bytes,
    respond_json,
    respond_options,
)
from lib.time_utils import now_ms
from repositories.users import UsersRepository
from runtime import ClientRuntimeState
from schemas import ProxyBytesResult, ServiceResult
from services.bridge_publisher import publish_event, resolve_publish_mode
from services.engine_gateway import (
    PROXY_READ_GET_ROUTES,
    PROXY_READ_POST_ROUTES,
    proxy_engine_request,
    sanitize_get_query,
    sanitize_post_request,
    summarize_proxy_likes,
)
from services.profile import (
    get_client_likes_metadata,
    get_profile_likes_metadata,
    get_user_profile,
    parse_positive_int,
    reset_user_profile,
)
from services.user_actions import handle_user_action

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent.parent

DEFAULT_CLIENT_HOST = "127.0.0.1"
DEFAULT_CLIENT_PORT = 7172
DEFAULT_ENGINE_INGEST_BASE = "http://127.0.0.1:7070"
DEFAULT_USERS_DB_PATH = "client/backend/db/users.db"
DEFAULT_CLIENT_PUBLISH_MODE = os.environ.get("CLIENT_PUBLISH_MODE", "bridge").strip().lower()
MAX_LIKES = 100
MAX_CLIENT_LIKES = 200
RATE_LIMIT_MAX_REQUESTS = 90
RATE_LIMIT_WINDOW_SECONDS = 60
ENGINE_PROXY_TIMEOUT_SECONDS = 10
ENGINE_PROXY_MAX_BODY_BYTES = 1_000_000
ENGINE_PROXY_RETRY_COUNT = 1
ENGINE_PROXY_RETRY_DELAY_SECONDS = 0.25


def _emit_client_log(
    level: int,
    event: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Emit one structured JSON log line for Client backend service."""
    payload: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "level": logging.getLevelName(level),
        "service": "client-backend",
        "event": event,
        "message": message,
    }
    if context:
        payload["context"] = context
    logging.log(level, json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


def parse_args() -> argparse.Namespace:
    """Parse Client backend command-line options."""
    parser = argparse.ArgumentParser(description="Run PeerTube Client backend service.")
    parser.add_argument("--host", default=DEFAULT_CLIENT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_CLIENT_PORT)
    parser.add_argument(
        "--engine-url", dest="engine_ingest_base", default=DEFAULT_ENGINE_INGEST_BASE
    )
    parser.add_argument("--publish-mode", default=resolve_publish_mode(DEFAULT_CLIENT_PUBLISH_MODE))
    return parser.parse_args()


def connect_db(path: Path) -> sqlite3.Connection:
    """Open the Client users SQLite database with current row semantics."""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class ClientBackendServer(ThreadingHTTPServer):
    """Threaded server carrying Client backend runtime dependencies."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        user_db: sqlite3.Connection,
        engine_ingest_base: str,
        publish_mode: str,
        rate_limiter: RateLimiter,
    ) -> None:
        """Initialize runtime state shared by request handlers."""
        super().__init__(server_address, handler_class)
        self.user_db = user_db
        self.users = UsersRepository(user_db)
        self.engine_ingest_base = engine_ingest_base.rstrip("/")
        self.publish_mode = resolve_publish_mode(publish_mode)
        self.rate_limiter = rate_limiter


class ClientBackendHandler(BaseHTTPRequestHandler):
    """HTTP adapter for Client backend profile, write, and gateway routes."""

    def _get_client_ip(self) -> str:
        """Resolve the best available client IP for access logs."""
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
        """Reconstruct the request URL used in access logs."""
        host = self.headers.get("Host", "").strip()
        if not host:
            return self.path
        proto = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip() or "http"
        return f"{proto}://{host}{self.path}"

    def log_message(self, format: str, *args: Any) -> None:
        """Emit readable access logs instead of BaseHTTPRequestHandler defaults."""
        status = args[1] if len(args) > 1 else "-"
        size = args[2] if len(args) > 2 else "-"
        _emit_client_log(
            logging.INFO,
            "client.access",
            "request finished",
            {
                "ip": self._get_client_ip(),
                "method": self.command or "-",
                "url": self._get_full_url(),
                "status": str(status),
                "bytes": str(size),
            },
        )

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Respond to CORS preflight requests."""
        respond_options(self)

    def do_GET(self) -> None:  # noqa: N802
        """Dispatch GET routes while keeping behavior in services."""
        url = urlparse(self.path)
        params = parse_qs(url.query)
        if url.path in PROXY_READ_GET_ROUTES:
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_engine_read_proxy_get(url.path, params)
            return
        if url.path == "/api/health":
            respond_json(
                self,
                200,
                {
                    "ok": True,
                    "service": "client-backend",
                    "engine_ingest_base": self.server.engine_ingest_base,
                    "publish_mode": self.server.publish_mode,
                },
            )
            return
        if url.path == "/api/user-profile":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            user_id = resolve_user_id(params.get("user_id", params.get("userId", [None]))[0])
            self._write_service_result(get_user_profile(self.server.users, user_id, MAX_LIKES))
            return
        if url.path == "/api/user-profile/likes":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_profile_likes_get(params)
            return
        respond_json(self, 404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        """Dispatch POST routes while preserving current HTTP adaptation behavior."""
        url = urlparse(self.path)
        if url.path in PROXY_READ_POST_ROUTES:
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_engine_read_proxy_post(url.path, url)
            return
        if url.path == "/api/user-action":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_action()
            return
        if url.path == "/api/user-profile/reset":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_profile_reset()
            return
        if url.path == "/api/user-profile/likes":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_profile_likes_from_client()
            return
        if url.path == "/client/events/publish":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_client_publish_event()
            return
        respond_json(self, 404, {"error": "Not found"})

    def _rate_limit_check(self, path: str) -> bool:
        """Apply the current per-IP route rate-limit key."""
        ip = self.client_address[0] if self.client_address else "unknown"
        key = f"{ip}:{path}"
        return self.server.rate_limiter.allow(key)

    def _write_service_result(self, result: ServiceResult) -> None:
        """Write an HTTP-neutral service result as JSON."""
        respond_json(self, result.status, result.body)

    def _write_proxy_result(self, result: ProxyBytesResult | ServiceResult) -> None:
        """Write a proxy result while preserving upstream bytes where available."""
        if isinstance(result, ProxyBytesResult):
            if not respond_bytes(self, result.status, result.payload, result.content_type):
                _emit_client_log(
                    logging.INFO,
                    "engine.proxy",
                    "client disconnected before proxy response write",
                    {"status": result.status},
                )
            return
        respond_json(self, result.status, result.body)

    def _handle_engine_read_proxy_get(self, path: str, params: dict[str, list[str]]) -> None:
        """Proxy one allowlisted GET read route to Engine."""
        query_result = sanitize_get_query(path, params)
        if isinstance(query_result, ServiceResult):
            self._write_service_result(query_result)
            return
        result = proxy_engine_request(
            self.server.engine_ingest_base,
            "GET",
            path,
            sanitized_query=query_result,
            timeout_seconds=ENGINE_PROXY_TIMEOUT_SECONDS,
            max_body_bytes=ENGINE_PROXY_MAX_BODY_BYTES,
            retry_count=ENGINE_PROXY_RETRY_COUNT,
            retry_delay_seconds=ENGINE_PROXY_RETRY_DELAY_SECONDS,
            log=_emit_client_log,
        )
        self._write_proxy_result(result)

    def _handle_engine_read_proxy_post(self, path: str, url: Any) -> None:
        """Proxy one allowlisted POST read route to Engine."""
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        if not isinstance(body, dict):
            respond_json(self, 400, {"error": "Invalid JSON body"})
            return
        sanitized = sanitize_post_request(path, parse_qs(url.query), body, MAX_CLIENT_LIKES)
        if isinstance(sanitized, ServiceResult):
            self._write_service_result(sanitized)
            return
        sanitized_query, sanitized_body = sanitized
        if path == "/recommendations":
            likes_count, likes_list, likes_omitted = summarize_proxy_likes(
                sanitized_body.get("likes")
            )
            _emit_client_log(
                logging.INFO,
                "recommendations.incoming_likes",
                "incoming likes payload",
                {
                    "likes_count": likes_count,
                    "likes": likes_list,
                    "likes_omitted": likes_omitted,
                    "user_id": sanitized_body.get("user_id"),
                    "mode": sanitized_body.get("mode"),
                },
            )
        result = proxy_engine_request(
            self.server.engine_ingest_base,
            "POST",
            path,
            sanitized_query=sanitized_query,
            body=sanitized_body,
            timeout_seconds=ENGINE_PROXY_TIMEOUT_SECONDS,
            max_body_bytes=ENGINE_PROXY_MAX_BODY_BYTES,
            retry_count=ENGINE_PROXY_RETRY_COUNT,
            retry_delay_seconds=ENGINE_PROXY_RETRY_DELAY_SECONDS,
            log=_emit_client_log,
        )
        self._write_proxy_result(result)

    def _handle_user_action(self) -> None:
        """Apply one Client user action through the user action service."""
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        self._write_service_result(
            handle_user_action(
                self.server.users,
                self.server.engine_ingest_base,
                self.server.publish_mode,
                body,
                MAX_LIKES,
            )
        )

    def _handle_user_profile_reset(self) -> None:
        """Reset the local Client profile likes for one user."""
        body = read_json_body(self)
        raw_user_id = body.get("user_id") if isinstance(body, dict) else None
        self._write_service_result(reset_user_profile(self.server.users, raw_user_id))

    def _handle_user_profile_likes_get(self, params: dict[str, list[str]]) -> None:
        """Return Engine-enriched metadata for stored Client likes."""
        user_id = resolve_user_id(params.get("user_id", params.get("userId", [None]))[0])
        limit = parse_positive_int(params.get("limit", [None])[0])
        self._write_service_result(
            get_profile_likes_metadata(
                self.server.users,
                self.server.engine_ingest_base,
                user_id,
                limit,
                MAX_LIKES,
            )
        )

    def _handle_user_profile_likes_from_client(self) -> None:
        """Return metadata for frontend-provided uuid/host like entries."""
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        self._write_service_result(
            get_client_likes_metadata(self.server.engine_ingest_base, body, MAX_CLIENT_LIKES)
        )

    def _handle_client_publish_event(self) -> None:
        """Publish one already-normalized Client event to the configured bridge mode."""
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        if not isinstance(body, dict):
            respond_json(self, 400, {"error": "Invalid JSON body"})
            return
        if not body.get("event_id"):
            body["event_id"] = f"client-{uuid4()}"
        if not body.get("published_at"):
            body["published_at"] = now_ms()
        result = publish_event(self.server.publish_mode, self.server.engine_ingest_base, body)
        respond_json(self, 200 if result.get("ok") else 502, result)


def main() -> None:
    """Run the Client backend FastAPI service through the compatibility entrypoint."""
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_id = str(uuid4())

    users_db_path = (ROOT_DIR / DEFAULT_USERS_DB_PATH).resolve()
    users_db_path.parent.mkdir(parents=True, exist_ok=True)
    user_db = connect_db(users_db_path)
    users = UsersRepository(user_db)
    users.ensure_schema()
    state = ClientRuntimeState.create(
        user_db,
        args.engine_ingest_base,
        args.publish_mode,
        RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS),
    )
    app = create_app(state)
    _emit_client_log(
        logging.INFO,
        "service.start",
        "client backend listening",
        {
            "host": args.host,
            "port": int(args.port),
            "engine_ingest_base": args.engine_ingest_base,
            "publish_mode": resolve_publish_mode(args.publish_mode),
            "run_id": run_id,
            "pid": os.getpid(),
            "framework": "fastapi",
        },
    )
    try:
        uvicorn.run(app, host=args.host, port=int(args.port), log_level="info", access_log=False)
    finally:
        _emit_client_log(
            logging.INFO,
            "service.stop",
            "client backend shutting down",
            {"reason": "uvicorn_exit", "run_id": run_id, "pid": os.getpid()},
        )
        user_db.close()


if __name__ == "__main__":
    main()
