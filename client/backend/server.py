#!/usr/bin/env python3
"""Client backend service for write/profile endpoints and bridge publishing."""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sqlite3
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4
from datetime import datetime

from lib.engine_api_client import (EngineApiError, fetch_metadata_for_entries,
                                   resolve_video_seed, resolve_videos_by_uuid_host)
from lib.http_utils import (RateLimiter, read_json_body, resolve_user_id,
                            respond_bytes, respond_json, respond_options)
from lib.time_utils import now_ms
from lib.users_store import (clear_likes, ensure_user_schema, fetch_recent_likes,
                             get_or_create_user, record_like, remove_like)

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
PROXY_READ_GET_ROUTES = frozenset(("/api/video", "/api/channels"))
PROXY_READ_POST_ROUTES = frozenset(("/recommendations", "/videos/similar"))
PROXY_ALLOWED_QUERY_PARAMS: dict[str, set[str]] = {
    "/recommendations": {"id", "host", "limit", "random", "debug", "mode", "user_id"},
    "/videos/similar": {"id", "host", "limit", "random", "debug", "mode", "user_id"},
    "/api/video": {"id", "host", "refresh_cache", "user_id"},
    "/api/channels": {
        "limit",
        "offset",
        "q",
        "instance",
        "minFollowers",
        "minVideos",
        "maxVideos",
        "sort",
        "dir",
    },
}
PROXY_ALLOWED_BODY_KEYS: dict[str, set[str]] = {
    "/recommendations": {"likes", "user_id", "mode"},
    "/videos/similar": {"likes", "user_id", "mode"},
}


def _resolve_mode(value: str, default: str = "bridge") -> str:
    """Handle resolve mode."""
    normalized = value.strip().lower()
    return normalized if normalized in {"bridge", "activitypub"} else default


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
    """Handle parse args."""
    parser = argparse.ArgumentParser(description="Run PeerTube Client backend service.")
    parser.add_argument("--host", default=DEFAULT_CLIENT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_CLIENT_PORT)
    parser.add_argument("--engine-url", dest="engine_ingest_base", default=DEFAULT_ENGINE_INGEST_BASE)
    parser.add_argument("--publish-mode", default=_resolve_mode(DEFAULT_CLIENT_PUBLISH_MODE))
    return parser.parse_args()


def connect_db(path: Path) -> sqlite3.Connection:
    """Handle connect db."""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class ClientBackendServer(ThreadingHTTPServer):
    """Threaded server with shared DB handles and config."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        user_db: sqlite3.Connection,
        engine_ingest_base: str,
        publish_mode: str,
        rate_limiter: RateLimiter,
    ) -> None:
        """Initialize the instance."""
        super().__init__(server_address, handler_class)
        self.user_db = user_db
        self.engine_ingest_base = engine_ingest_base.rstrip("/")
        self.publish_mode = _resolve_mode(publish_mode)
        self.rate_limiter = rate_limiter


class ClientBackendHandler(BaseHTTPRequestHandler):
    """HTTP handler for Client backend write/profile endpoints."""

    def _get_client_ip(self) -> str:
        """Handle get client ip."""
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
        """Handle get full url."""
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
        """Handle do options."""
        respond_options(self)

    def do_GET(self) -> None:  # noqa: N802
        """Handle do get."""
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
            with self.server.user_db:
                get_or_create_user(self.server.user_db, user_id)
                likes = fetch_recent_likes(self.server.user_db, user_id, MAX_LIKES)
            respond_json(self, 200, {"user_id": user_id, "likes": likes, "updatedAt": now_ms()})
            return
        if url.path == "/api/user-profile/likes":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_profile_likes_get(params)
            return
        respond_json(self, 404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        """Handle do post."""
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
        """Handle rate limit check."""
        ip = self.client_address[0] if self.client_address else "unknown"
        key = f"{ip}:{path}"
        return self.server.rate_limiter.allow(key)

    def _handle_engine_read_proxy_get(self, path: str, params: dict[str, list[str]]) -> None:
        """Handle handle engine read proxy get."""
        allowed = PROXY_ALLOWED_QUERY_PARAMS.get(path, set())
        sanitized: dict[str, str] = {}
        for key, values in params.items():
            if key not in allowed:
                respond_json(self, 400, {"error": f"Unknown query parameter: {key}"})
                return
            if not values:
                continue
            if len(values) != 1:
                respond_json(self, 400, {"error": f"Multiple values are not allowed for query parameter: {key}"})
                return
            value = values[0].strip()
            if value:
                sanitized[key] = value
        self._proxy_engine_request("GET", path, sanitized_query=sanitized)

    def _handle_engine_read_proxy_post(self, path: str, url: Any) -> None:
        """Handle handle engine read proxy post."""
        query_params = parse_qs(url.query)
        allowed_query = PROXY_ALLOWED_QUERY_PARAMS.get(path, set())
        sanitized_query: dict[str, str] = {}
        for key, values in query_params.items():
            if key not in allowed_query:
                respond_json(self, 400, {"error": f"Unknown query parameter: {key}"})
                return
            if not values:
                continue
            if len(values) != 1:
                respond_json(self, 400, {"error": f"Multiple values are not allowed for query parameter: {key}"})
                return
            value = values[0].strip()
            if value:
                sanitized_query[key] = value
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        if not isinstance(body, dict):
            respond_json(self, 400, {"error": "Invalid JSON body"})
            return
        allowed_body_keys = PROXY_ALLOWED_BODY_KEYS.get(path, set())
        sanitized_body: dict[str, Any] = {}
        for key, value in body.items():
            if key not in allowed_body_keys:
                respond_json(self, 400, {"error": f"Unknown body field: {key}"})
                return
            sanitized_body[key] = value
        likes = sanitized_body.get("likes")
        if likes is not None:
            if not isinstance(likes, list):
                respond_json(self, 400, {"error": "Invalid likes payload"})
                return
            sanitized_likes: list[dict[str, str]] = []
            for entry in likes[:MAX_CLIENT_LIKES]:
                if not isinstance(entry, dict):
                    continue
                uuid = entry.get("uuid")
                host = entry.get("host")
                if not isinstance(uuid, str) or not uuid.strip():
                    continue
                if not isinstance(host, str) or not host.strip():
                    continue
                sanitized_likes.append({"uuid": uuid.strip(), "host": host.strip()})
            sanitized_body["likes"] = sanitized_likes
        if path == "/recommendations":
            likes_count, likes_list, likes_omitted = _summarize_proxy_likes(
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
        self._proxy_engine_request(
            "POST",
            path,
            sanitized_query=sanitized_query,
            body=sanitized_body,
        )

    def _proxy_engine_request(
        self,
        method: str,
        path: str,
        sanitized_query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> None:
        """Handle proxy engine request."""
        sanitized_query = sanitized_query or {}
        upstream = f"{self.server.engine_ingest_base}{path}"
        if sanitized_query:
            upstream = f"{upstream}?{urlencode(sanitized_query)}"
        started_at = time.perf_counter()
        request_data: bytes | None = None
        headers = {"accept": "application/json"}
        if method == "POST":
            request_data = json.dumps(body or {}).encode("utf-8")
            if len(request_data) > ENGINE_PROXY_MAX_BODY_BYTES:
                respond_json(self, 400, {"error": "Invalid JSON body"})
                return
            headers["content-type"] = "application/json"
        request = Request(
            upstream,
            data=request_data,
            method=method,
            headers=headers,
        )
        last_transport_error: Exception | None = None
        for attempt in range(ENGINE_PROXY_RETRY_COUNT + 1):
            try:
                with urlopen(request, timeout=ENGINE_PROXY_TIMEOUT_SECONDS) as response:
                    payload = response.read()
                    status = int(response.status)
                    duration_ms = int((time.perf_counter() - started_at) * 1000)
                    content_type = response.headers.get("content-type", "application/json; charset=utf-8")
                    if not respond_bytes(self, status, payload, content_type):
                        _emit_client_log(
                            logging.INFO,
                            "engine.proxy",
                            "client disconnected before proxy response write",
                            {
                                "method": method,
                                "path": path,
                                "status": status,
                                "attempt": attempt + 1,
                                "duration_ms": duration_ms,
                            },
                        )
                        return
                    _emit_client_log(
                        logging.INFO,
                        "engine.proxy",
                        "proxy request completed",
                        {
                            "method": method,
                            "path": path,
                            "status": status,
                            "attempt": attempt + 1,
                            "duration_ms": duration_ms,
                        },
                    )
                    return
            except HTTPError as exc:
                payload = exc.read() if exc.fp else b""
                if payload:
                    content_type = exc.headers.get("content-type", "application/json; charset=utf-8")
                    duration_ms = int((time.perf_counter() - started_at) * 1000)
                    if not respond_bytes(self, int(exc.code), payload, content_type):
                        _emit_client_log(
                            logging.INFO,
                            "engine.proxy",
                            "client disconnected before proxy response write",
                            {
                                "method": method,
                                "path": path,
                                "status": int(exc.code),
                                "attempt": attempt + 1,
                                "duration_ms": duration_ms,
                            },
                        )
                        return
                    _emit_client_log(
                        logging.INFO,
                        "engine.proxy",
                        "proxy request completed",
                        {
                            "method": method,
                            "path": path,
                            "status": int(exc.code),
                            "attempt": attempt + 1,
                            "duration_ms": duration_ms,
                        },
                    )
                    return
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                _emit_client_log(
                    logging.WARNING,
                    "engine.proxy",
                    "proxy request failed",
                    {
                        "method": method,
                        "path": path,
                        "status": int(exc.code),
                        "attempt": attempt + 1,
                        "duration_ms": duration_ms,
                        "error": "no-payload",
                    },
                )
                respond_json(self, int(exc.code), {"error": f"Engine read proxy HTTP {int(exc.code)}"})
                return
            except (URLError, TimeoutError) as exc:
                last_transport_error = exc
                if attempt < ENGINE_PROXY_RETRY_COUNT:
                    time.sleep(ENGINE_PROXY_RETRY_DELAY_SECONDS)
                    continue
                break
            except Exception as exc:  # pragma: no cover
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                _emit_client_log(
                    logging.ERROR,
                    "engine.proxy",
                    "proxy request exception",
                    {
                        "method": method,
                        "path": path,
                        "status": 502,
                        "attempt": attempt + 1,
                        "duration_ms": duration_ms,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )
                respond_json(
                    self,
                    502,
                    {"error": "Engine read proxy failed", "code": "ENGINE_PROXY_FAILURE", "detail": str(exc)},
                )
                return
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _emit_client_log(
            logging.WARNING,
            "engine.proxy",
            "proxy request unavailable",
            {
                "method": method,
                "path": path,
                "status": 502,
                "attempts": ENGINE_PROXY_RETRY_COUNT + 1,
                "duration_ms": duration_ms,
                "error": str(last_transport_error) if last_transport_error is not None else "unknown transport error",
            },
        )
        respond_json(
            self,
            502,
            {
                "error": "Engine read proxy failed",
                "code": "ENGINE_PROXY_UNAVAILABLE",
                "detail": str(last_transport_error) if last_transport_error is not None else "Unknown transport error",
            },
        )
        return

    def _handle_user_action(self) -> None:
        """Handle handle user action."""
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        action = str(body.get("action") or "").strip().lower()
        if action not in {"like", "dislike", "undo_like"}:
            respond_json(self, 400, {"error": "Unsupported action"})
            return
        video_id = body.get("video_id")
        host = body.get("host")
        uuid = body.get("uuid")
        user_id_raw = body.get("user_id")
        if not video_id and not uuid:
            respond_json(self, 400, {"error": "Missing video_id or uuid"})
            return
        user_id = resolve_user_id(str(user_id_raw) if user_id_raw is not None else None)

        try:
            seed = resolve_video_seed(
                self.server.engine_ingest_base,
                str(video_id) if video_id is not None else None,
                str(host) if host is not None else None,
                str(uuid) if uuid is not None else None,
            )
        except EngineApiError as exc:
            respond_json(self, 502, {"error": f"Engine resolve failed: {exc}"})
            return

        if not seed:
            respond_json(self, 404, {"error": "Video not found in Engine"})
            return

        canonical_video_id = str(seed.get("video_id") or "")
        canonical_host = str(seed.get("instance_domain") or "")
        canonical_uuid = str(seed.get("video_uuid") or "")
        if not canonical_video_id or not canonical_host:
            respond_json(self, 502, {"error": "Engine resolve returned incomplete identity"})
            return

        if action == "like":
            with self.server.user_db:
                record_like(
                    self.server.user_db,
                    user_id,
                    "like",
                    {
                        "video_id": canonical_video_id,
                        "video_uuid": canonical_uuid,
                        "instance_domain": canonical_host,
                    },
                    MAX_LIKES,
                )
            event_type = "Like"
        else:
            with self.server.user_db:
                remove_like(self.server.user_db, user_id, canonical_video_id, canonical_host)
            event_type = "UndoLike"

        event_payload = {
            "event_id": f"client-{uuid4()}",
            "event_type": event_type,
            "actor_id": user_id,
            "object": {
                "video_uuid": canonical_uuid,
                "instance_domain": canonical_host,
                "canonical_url": seed.get("video_url"),
            },
            "published_at": now_ms(),
            "source_instance": canonical_host,
            "raw_payload": body,
        }
        bridge_result = _publish_event(
            self.server.publish_mode,
            self.server.engine_ingest_base,
            event_payload,
        )
        status = 200 if bridge_result.get("ok") else 502
        respond_json(
            self,
            status,
            {
                "ok": bridge_result.get("ok", False),
                "bridge_ok": bridge_result.get("ok", False),
                "bridge_error": bridge_result.get("error"),
                "user_id": user_id,
                "updatedAt": now_ms(),
            },
        )

    def _handle_user_profile_reset(self) -> None:
        """Handle handle user profile reset."""
        body = read_json_body(self)
        user_id_raw = body.get("user_id") if isinstance(body, dict) else None
        user_id = resolve_user_id(str(user_id_raw) if user_id_raw is not None else None)
        with self.server.user_db:
            get_or_create_user(self.server.user_db, user_id)
            clear_likes(self.server.user_db, user_id)
        respond_json(
            self,
            200,
            {"user_id": user_id, "likes": [], "updatedAt": now_ms()},
        )

    def _handle_user_profile_likes_get(self, params: dict[str, list[str]]) -> None:
        """Handle handle user profile likes get."""
        user_id = resolve_user_id(params.get("user_id", params.get("userId", [None]))[0])
        limit = _parse_int(params.get("limit", [None])[0])
        limit = min(limit, MAX_LIKES) if limit > 0 else MAX_LIKES
        with self.server.user_db:
            get_or_create_user(self.server.user_db, user_id)
            likes = fetch_recent_likes(self.server.user_db, user_id, limit)
        try:
            rows = fetch_metadata_for_entries(self.server.engine_ingest_base, likes)
        except EngineApiError as exc:
            respond_json(self, 502, {"error": f"Engine metadata failed: {exc}"})
            return
        respond_json(self, 200, {"user_id": user_id, "likes": rows, "updatedAt": now_ms()})

    def _handle_user_profile_likes_from_client(self) -> None:
        """Handle handle user profile likes from client."""
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        likes = _parse_client_likes(body, MAX_CLIENT_LIKES)
        if not likes:
            respond_json(self, 200, {"likes": [], "updatedAt": now_ms()})
            return
        try:
            resolved = resolve_videos_by_uuid_host(self.server.engine_ingest_base, likes)
            rows = fetch_metadata_for_entries(self.server.engine_ingest_base, resolved)
        except EngineApiError as exc:
            respond_json(self, 502, {"error": f"Engine metadata failed: {exc}"})
            return
        respond_json(self, 200, {"likes": rows, "updatedAt": now_ms()})

    def _handle_client_publish_event(self) -> None:
        """Handle handle client publish event."""
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
        result = _publish_event(self.server.publish_mode, self.server.engine_ingest_base, body)
        status = 200 if result.get("ok") else 502
        respond_json(self, status, result)


def _publish_to_engine_bridge(engine_ingest_base: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Handle publish to engine bridge."""
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{engine_ingest_base}/internal/events/ingest",
        data=data,
        method="POST",
        headers={"content-type": "application/json"},
    )
    try:
        with urlopen(request, timeout=6) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            return {"ok": bool(parsed.get("ok", True)), "response": parsed}
    except HTTPError as exc:
        return {"ok": False, "error": f"engine bridge HTTP {exc.code}"}
    except (URLError, TimeoutError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


def _publish_event(
    publish_mode: str, engine_ingest_base: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Handle publish event."""
    if _resolve_mode(publish_mode) != "bridge":
        return {
            "ok": False,
            "error": "CLIENT_PUBLISH_MODE=activitypub is not implemented yet",
            "mode": _resolve_mode(publish_mode),
        }
    return _publish_to_engine_bridge(engine_ingest_base, payload)


def _parse_int(value: str | None) -> int:
    """Handle parse int."""
    try:
        parsed = int(value or "0")
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _parse_client_likes(payload: dict[str, Any], max_items: int) -> list[dict[str, str]]:
    """Handle parse client likes."""
    raw = payload.get("likes")
    if not isinstance(raw, list):
        return []
    likes: list[dict[str, str]] = []
    for entry in raw[: max_items if max_items > 0 else None]:
        if not isinstance(entry, dict):
            continue
        uuid = entry.get("uuid")
        host = entry.get("host")
        if not isinstance(uuid, str) or not uuid.strip():
            continue
        if not isinstance(host, str) or not host.strip():
            continue
        likes.append({"video_uuid": uuid.strip(), "instance_domain": host.strip()})
    return likes


def _summarize_proxy_likes(
    raw_likes: Any, max_items: int = 6
) -> tuple[int, list[str], int]:
    """Return compact like list and omitted count for client service logs."""
    if not isinstance(raw_likes, list):
        return 0, [], 0
    parts: list[str] = []
    total = 0
    for entry in raw_likes:
        if not isinstance(entry, dict):
            continue
        uuid = str(entry.get("uuid") or "").strip()
        host = str(entry.get("host") or "").strip()
        if not uuid or not host:
            continue
        total += 1
        if len(parts) < max_items:
            parts.append(f"{uuid}@{host}")
    omitted = total - len(parts)
    return total, parts, omitted


def main() -> None:
    """Handle main."""
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_id = str(uuid4())
    stop_reason = "unknown"

    def _signal_name(signum: int) -> str:
        """Return a stable signal name for lifecycle logging."""
        try:
            return signal.Signals(signum).name
        except ValueError:
            return str(signum)

    def _handle_shutdown_signal(signum: int, _frame: Any) -> None:
        """Translate SIGTERM/SIGINT into KeyboardInterrupt for graceful shutdown."""
        nonlocal stop_reason
        stop_reason = f"signal:{_signal_name(signum)}"
        raise KeyboardInterrupt

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)

    users_db_path = (ROOT_DIR / DEFAULT_USERS_DB_PATH).resolve()
    users_db_path.parent.mkdir(parents=True, exist_ok=True)
    user_db = connect_db(users_db_path)
    ensure_user_schema(user_db)
    server = ClientBackendServer(
        (args.host, int(args.port)),
        ClientBackendHandler,
        user_db,
        args.engine_ingest_base,
        args.publish_mode,
        RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS),
    )
    _emit_client_log(
        logging.INFO,
        "service.start",
        "client backend listening",
        {
            "host": args.host,
            "port": int(args.port),
            "engine_ingest_base": args.engine_ingest_base,
            "publish_mode": _resolve_mode(args.publish_mode),
            "run_id": run_id,
            "pid": os.getpid(),
        },
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if stop_reason == "unknown":
            stop_reason = "keyboard_interrupt"
        _emit_client_log(
            logging.INFO,
            "service.stop",
            "client backend shutting down",
            {
                "reason": stop_reason,
                "run_id": run_id,
                "pid": os.getpid(),
            },
        )
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
        server.server_close()
        user_db.close()


if __name__ == "__main__":
    main()
