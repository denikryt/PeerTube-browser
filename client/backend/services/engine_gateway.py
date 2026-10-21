"""Client read gateway service for allowlisted Engine HTTP proxy calls."""
from __future__ import annotations

import json
import logging
import time
import traceback
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from schemas import ProxyBytesResult, ServiceResult

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

LogCallback = Callable[[int, str, str, dict[str, Any] | None], None]


def sanitize_get_query(path: str, params: dict[str, list[str]]) -> ServiceResult | dict[str, str]:
    """Validate and sanitize allowlisted GET proxy query parameters."""
    allowed = PROXY_ALLOWED_QUERY_PARAMS.get(path, set())
    sanitized: dict[str, str] = {}
    for key, values in params.items():
        if key not in allowed:
            return ServiceResult(400, {"error": f"Unknown query parameter: {key}"})
        if not values:
            continue
        if len(values) != 1:
            return ServiceResult(
                400,
                {"error": f"Multiple values are not allowed for query parameter: {key}"},
            )
        value = values[0].strip()
        if value:
            sanitized[key] = value
    return sanitized


def sanitize_post_request(
    path: str,
    query_params: dict[str, list[str]],
    body: dict[str, Any],
    max_client_likes: int,
) -> ServiceResult | tuple[dict[str, str], dict[str, Any]]:
    """Validate and sanitize a Client read-proxy POST request."""
    query_result = sanitize_get_query(path, query_params)
    if isinstance(query_result, ServiceResult):
        return query_result

    allowed_body_keys = PROXY_ALLOWED_BODY_KEYS.get(path, set())
    sanitized_body: dict[str, Any] = {}
    for key, value in body.items():
        if key not in allowed_body_keys:
            return ServiceResult(400, {"error": f"Unknown body field: {key}"})
        sanitized_body[key] = value

    likes = sanitized_body.get("likes")
    if likes is not None:
        if not isinstance(likes, list):
            return ServiceResult(400, {"error": "Invalid likes payload"})
        sanitized_likes: list[dict[str, str]] = []
        for entry in likes[:max_client_likes]:
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
    return query_result, sanitized_body


def summarize_proxy_likes(raw_likes: Any, max_items: int = 6) -> tuple[int, list[str], int]:
    """Return compact like diagnostics for Client recommendation logs."""
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


def proxy_engine_request(
    engine_base_url: str,
    method: str,
    path: str,
    sanitized_query: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout_seconds: int = 10,
    max_body_bytes: int = 1_000_000,
    retry_count: int = 1,
    retry_delay_seconds: float = 0.25,
    log: LogCallback | None = None,
) -> ProxyBytesResult | ServiceResult:
    """Forward one allowlisted Client read request to Engine over HTTP."""
    sanitized_query = sanitized_query or {}
    upstream = f"{engine_base_url.rstrip('/')}{path}"
    if sanitized_query:
        upstream = f"{upstream}?{urlencode(sanitized_query)}"
    started_at = time.perf_counter()
    request_data: bytes | None = None
    headers = {"accept": "application/json"}
    if method == "POST":
        request_data = json.dumps(body or {}).encode("utf-8")
        if len(request_data) > max_body_bytes:
            return ServiceResult(400, {"error": "Invalid JSON body"})
        headers["content-type"] = "application/json"
    request = Request(upstream, data=request_data, method=method, headers=headers)
    last_transport_error: Exception | None = None

    for attempt in range(retry_count + 1):
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read()
                status = int(response.status)
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                content_type = response.headers.get(
                    "content-type", "application/json; charset=utf-8"
                )
                _log_proxy(
                    log,
                    logging.INFO,
                    "proxy request completed",
                    method,
                    path,
                    status,
                    attempt,
                    duration_ms,
                )
                return ProxyBytesResult(status, payload, content_type)
        except HTTPError as exc:
            payload = exc.read() if exc.fp else b""
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            if payload:
                content_type = exc.headers.get("content-type", "application/json; charset=utf-8")
                _log_proxy(
                    log,
                    logging.INFO,
                    "proxy request completed",
                    method,
                    path,
                    int(exc.code),
                    attempt,
                    duration_ms,
                )
                return ProxyBytesResult(int(exc.code), payload, content_type)
            _log_proxy(
                log,
                logging.WARNING,
                "proxy request failed",
                method,
                path,
                int(exc.code),
                attempt,
                duration_ms,
                {"error": "no-payload"},
            )
            return ServiceResult(
                int(exc.code), {"error": f"Engine read proxy HTTP {int(exc.code)}"}
            )
        except (URLError, TimeoutError) as exc:
            last_transport_error = exc
            if attempt < retry_count:
                time.sleep(retry_delay_seconds)
                continue
            break
        except Exception as exc:  # pragma: no cover
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            _log_proxy(
                log,
                logging.ERROR,
                "proxy request exception",
                method,
                path,
                502,
                attempt,
                duration_ms,
                {"error": str(exc), "traceback": traceback.format_exc()},
            )
            return ServiceResult(
                502,
                {
                    "error": "Engine read proxy failed",
                    "code": "ENGINE_PROXY_FAILURE",
                    "detail": str(exc),
                },
            )

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    detail = (
        str(last_transport_error)
        if last_transport_error is not None
        else "Unknown transport error"
    )
    _log_proxy(
        log,
        logging.WARNING,
        "proxy request unavailable",
        method,
        path,
        502,
        retry_count,
        duration_ms,
        {"attempts": retry_count + 1, "error": detail},
    )
    return ServiceResult(
        502,
        {"error": "Engine read proxy failed", "code": "ENGINE_PROXY_UNAVAILABLE", "detail": detail},
    )


def _log_proxy(
    log: LogCallback | None,
    level: int,
    message: str,
    method: str,
    path: str,
    status: int,
    attempt: int,
    duration_ms: int,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit the current proxy diagnostic fields through the server logger callback."""
    if log is None:
        return
    context = {
        "method": method,
        "path": path,
        "status": status,
        "attempt": attempt + 1,
        "duration_ms": duration_ms,
    }
    if extra:
        context.update(extra)
    log(level, "engine.proxy", message, context)
