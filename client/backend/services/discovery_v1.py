"""Client-owned Discovery API v1 service helpers."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from lib.engine_api_client import (
    EngineApiError,
    fetch_engine_fresh,
    fetch_engine_popular,
    fetch_engine_random,
    fetch_engine_recommendations,
    fetch_engine_similar,
    fetch_engine_video,
)
from repositories.users import UsersRepository
from schemas import ServiceResult

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MIN_LIMIT = 1
MAX_LIKES = 200

ERROR_BAD_REQUEST = "V1_DISCOVERY_BAD_REQUEST"
ERROR_MISSING_HOST = "V1_DISCOVERY_MISSING_HOST"
ERROR_ENGINE_UNAVAILABLE = "V1_DISCOVERY_ENGINE_UNAVAILABLE"
ERROR_NOT_FOUND = "V1_DISCOVERY_NOT_FOUND"


@dataclass(frozen=True)
class PageRequest:
    """Parsed v1 list request parameters."""

    limit: int
    offset: int
    debug: bool


def error_result(status: int, message: str, code: str) -> ServiceResult:
    """Build a v1 error result."""
    return ServiceResult(status, {"error": message, "code": code})


def _first_query_value(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    return values[0]


def _parse_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def parse_limit(value: str | None) -> int:
    """Parse and clamp v1 list limit."""
    if value is None or not str(value).strip():
        return DEFAULT_LIMIT
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("Invalid limit") from exc
    if parsed < MIN_LIMIT:
        raise ValueError("Invalid limit")
    return min(parsed, MAX_LIMIT)


def encode_cursor(kind: str, offset: int, seed: dict[str, str] | None = None) -> str:
    """Encode an opaque Client-owned cursor."""
    payload: dict[str, Any] = {"v": 1, "kind": kind, "offset": offset}
    if seed:
        payload["seed"] = seed
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str | None, expected_kind: str, seed: dict[str, str] | None = None) -> int:
    """Decode and validate an opaque cursor for one route kind."""
    if not value:
        return 0
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - all malformed cursors are bad requests
        raise ValueError("Invalid cursor") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid cursor")
    if payload.get("v") != 1 or payload.get("kind") != expected_kind:
        raise ValueError("Invalid cursor")
    offset = payload.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("Invalid cursor")
    if seed is not None and payload.get("seed") != seed:
        raise ValueError("Invalid cursor")
    return offset


def validate_query_params(
    params: dict[str, list[str]],
    allowed: set[str],
) -> ServiceResult | None:
    """Reject unknown query parameters before contacting Engine."""
    for key in params:
        if key not in allowed:
            return error_result(400, f"Unknown query parameter: {key}", ERROR_BAD_REQUEST)
    return None


def parse_page_request(
    params: dict[str, list[str]],
    kind: str,
    *,
    seed: dict[str, str] | None = None,
) -> PageRequest | ServiceResult:
    """Parse common v1 list request parameters."""
    try:
        limit = parse_limit(_first_query_value(params, "limit"))
        offset = decode_cursor(_first_query_value(params, "cursor"), kind, seed=seed)
    except ValueError as exc:
        return error_result(400, str(exc), ERROR_BAD_REQUEST)
    return PageRequest(limit=limit, offset=offset, debug=_parse_bool(_first_query_value(params, "debug")))


def build_list_envelope(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    offset: int,
    kind: str,
    source: str,
    fallback: bool = False,
    fallback_reason: str | None = None,
    seed: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the public v1 list response envelope."""
    items = rows[:limit]
    has_more = len(rows) > limit
    next_cursor = encode_cursor(kind, offset + len(items), seed=seed) if has_more else None
    meta: dict[str, Any] = {"source": source, "fallback": bool(fallback)}
    if fallback_reason:
        meta["fallback_reason"] = fallback_reason
    return {
        "items": items,
        "pagination": {"limit": limit, "next_cursor": next_cursor, "has_more": has_more},
        "meta": meta,
    }


def _engine_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _stored_likes_for_engine(users: UsersRepository, user_id: str) -> list[dict[str, str]]:
    users.get_or_create_user(user_id)
    rows = users.fetch_recent_likes(user_id, MAX_LIKES)
    likes: list[dict[str, str]] = []
    for row in rows:
        uuid = str(row.get("video_uuid") or "").strip()
        host = str(row.get("instance_domain") or "").strip()
        if not uuid or not host:
            continue
        likes.append({"uuid": uuid, "host": host})
    return likes


def handle_recommendations(
    users: UsersRepository,
    engine_base_url: str,
    user_id: str,
    params: dict[str, list[str]],
) -> ServiceResult:
    """Handle ``GET /api/v1/discovery/recommendations``."""
    if rejected := validate_query_params(params, {"limit", "cursor", "debug", "user_id", "userId"}):
        return rejected
    page = parse_page_request(params, "recommendations")
    if isinstance(page, ServiceResult):
        return page
    likes = _stored_likes_for_engine(users, user_id)
    try:
        payload = fetch_engine_recommendations(
            engine_base_url,
            likes,
            user_id,
            page.offset + page.limit + 1,
            debug=page.debug,
        )
    except EngineApiError as exc:
        return error_result(502, f"Engine unavailable: {exc}", ERROR_ENGINE_UNAVAILABLE)
    rows = _engine_rows(payload)[page.offset : page.offset + page.limit + 1]
    no_signals = not likes
    return ServiceResult(
        200,
        build_list_envelope(
            rows,
            limit=page.limit,
            offset=page.offset,
            kind="recommendations",
            source="recommendations",
            fallback=no_signals,
            fallback_reason="guest_profile" if no_signals else None,
        ),
    )


def handle_random(engine_base_url: str, params: dict[str, list[str]]) -> ServiceResult:
    """Handle ``GET /api/v1/discovery/random``."""
    if rejected := validate_query_params(params, {"limit", "cursor", "debug"}):
        return rejected
    page = parse_page_request(params, "random")
    if isinstance(page, ServiceResult):
        return page
    try:
        # Random is a continuous feed, not a stable ordered collection; the cursor
        # is only an opaque continuation token for the frontend contract.
        payload = fetch_engine_random(engine_base_url, page.limit + 1, debug=page.debug)
    except EngineApiError as exc:
        return error_result(502, f"Engine unavailable: {exc}", ERROR_ENGINE_UNAVAILABLE)
    rows = _engine_rows(payload)
    return ServiceResult(
        200,
        build_list_envelope(
            rows,
            limit=page.limit,
            offset=page.offset,
            kind="random",
            source="random",
        ),
    )


def handle_ordered_feed(engine_base_url: str, params: dict[str, list[str]], kind: str) -> ServiceResult:
    """Handle v1 fresh/popular feeds."""
    if rejected := validate_query_params(params, {"limit", "cursor"}):
        return rejected
    page = parse_page_request(params, kind)
    if isinstance(page, ServiceResult):
        return page
    fetcher = fetch_engine_fresh if kind == "fresh" else fetch_engine_popular
    try:
        payload = fetcher(engine_base_url, page.offset + page.limit + 1)
    except EngineApiError as exc:
        return error_result(502, f"Engine unavailable: {exc}", ERROR_ENGINE_UNAVAILABLE)
    rows = _engine_rows(payload)[page.offset : page.offset + page.limit + 1]
    return ServiceResult(
        200,
        build_list_envelope(rows, limit=page.limit, offset=page.offset, kind=kind, source=kind),
    )


def handle_video(engine_base_url: str, video_ref: str, params: dict[str, list[str]]) -> ServiceResult:
    """Handle ``GET /api/v1/videos/{id}``."""
    if rejected := validate_query_params(params, {"host"}):
        return rejected
    host = str(_first_query_value(params, "host") or "").strip()
    if not host:
        return error_result(400, "Missing host", ERROR_MISSING_HOST)
    try:
        status, payload = fetch_engine_video(engine_base_url, video_ref, host)
    except EngineApiError as exc:
        return error_result(502, f"Engine unavailable: {exc}", ERROR_ENGINE_UNAVAILABLE)
    if status == 404:
        return error_result(404, "Video not found", ERROR_NOT_FOUND)
    if status >= 400:
        return error_result(status, str(payload.get("error") or "Engine video failed"), ERROR_BAD_REQUEST)
    payload.setdefault("video_id", video_ref)
    payload.setdefault("video_uuid", payload.get("videoUuid"))
    payload.setdefault("instance_domain", host)
    return ServiceResult(200, payload)


def handle_similar(engine_base_url: str, video_ref: str, params: dict[str, list[str]]) -> ServiceResult:
    """Handle ``GET /api/v1/videos/{id}/similar``."""
    if rejected := validate_query_params(params, {"host", "limit", "cursor", "debug"}):
        return rejected
    host = str(_first_query_value(params, "host") or "").strip()
    if not host:
        return error_result(400, "Missing host", ERROR_MISSING_HOST)
    seed = {"id": video_ref, "host": host}
    page = parse_page_request(params, "similar", seed=seed)
    if isinstance(page, ServiceResult):
        return page
    try:
        payload = fetch_engine_similar(
            engine_base_url,
            video_ref,
            host,
            page.offset + page.limit + 1,
            debug=page.debug,
        )
    except EngineApiError as exc:
        return error_result(502, f"Engine unavailable: {exc}", ERROR_ENGINE_UNAVAILABLE)
    rows = _engine_rows(payload)[page.offset : page.offset + page.limit + 1]
    return ServiceResult(
        200,
        build_list_envelope(
            rows,
            limit=page.limit,
            offset=page.offset,
            kind="similar",
            source="similar",
            seed=seed,
        ),
    )
