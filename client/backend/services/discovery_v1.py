"""Client-owned Discovery API v1 service helpers."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from lib.engine_api_client import (
    EngineApiError,
    fetch_engine_discovery,
    fetch_engine_recommendations,
    fetch_engine_similar,
    fetch_engine_video,
    fetch_engine_video_facets,
)
from repositories.users import UsersRepository
from schemas import ServiceResult
from services.video_filters_v1 import FILTER_KEYS, PublicVideoFilters, parse_public_video_filters
from services.video_rows import normalize_video_row_for_browser, normalize_video_rows_for_browser

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MIN_LIMIT = 1
MAX_ENGINE_RECOMMENDATION_LIKES = 5

ERROR_BAD_REQUEST = "V1_DISCOVERY_BAD_REQUEST"
ERROR_MISSING_HOST = "V1_DISCOVERY_MISSING_HOST"
ERROR_ENGINE_UNAVAILABLE = "V1_DISCOVERY_ENGINE_UNAVAILABLE"
ERROR_PROVIDER_UNAVAILABLE = "V1_DISCOVERY_PROVIDER_UNAVAILABLE"
ERROR_STALE_CURSOR = "V1_DISCOVERY_STALE_CURSOR"
ERROR_NOT_FOUND = "V1_DISCOVERY_NOT_FOUND"


@dataclass(frozen=True)
class SimilarPageRequest:
    """Legacy Similar pagination request; independent from Discovery provider cursors."""

    limit: int
    offset: int
    debug: bool


def error_result(status: int, message: str, code: str) -> ServiceResult:
    """Build a v1 error result."""
    return ServiceResult(status, {"error": message, "code": code})


def _first_query_value(params: dict[str, list[str]], key: str) -> str | None:
    """Return the first raw value for a single-valued public query key."""
    values = params.get(key)
    return values[0] if values else None


def _parse_bool(value: str | None) -> bool:
    """Parse the existing permissive truthy spelling used by debug flags."""
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


def validate_query_params(params: dict[str, list[str]], allowed: set[str]) -> ServiceResult | None:
    """Reject unknown query parameters before contacting Engine."""
    for key in params:
        if key not in allowed:
            return error_result(400, f"Unknown query parameter: {key}", ERROR_BAD_REQUEST)
    return None


def _encode_legacy_cursor(kind: str, offset: int, seed: dict[str, str] | None = None) -> str:
    """Encode the unchanged Similar cursor v1 contract."""
    payload: dict[str, Any] = {"v": 1, "kind": kind, "offset": offset}
    if seed:
        payload["seed"] = seed
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_legacy_cursor(value: str | None, expected_kind: str, seed: dict[str, str] | None = None) -> int:
    """Decode the Similar-only v1 offset cursor."""
    if not value:
        return 0
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Invalid cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1 or payload.get("kind") != expected_kind:
        raise ValueError("Invalid cursor")
    offset = payload.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("Invalid cursor")
    if seed is not None and payload.get("seed") != seed:
        raise ValueError("Invalid cursor")
    return offset


def _parse_similar_page(params: dict[str, list[str]], kind: str, *, seed: dict[str, str] | None = None) -> SimilarPageRequest | ServiceResult:
    """Parse pagination for Similar without changing its existing cursor contract."""
    try:
        limit = parse_limit(_first_query_value(params, "limit"))
        offset = _decode_legacy_cursor(_first_query_value(params, "cursor"), kind, seed=seed)
    except ValueError as exc:
        return error_result(400, str(exc), ERROR_BAD_REQUEST)
    return SimilarPageRequest(limit=limit, offset=offset, debug=_parse_bool(_first_query_value(params, "debug")))


def _encode_provider_cursor(kind: str, filters: PublicVideoFilters, provider_cursor: str) -> str:
    """Wrap an opaque Engine cursor in the Client-owned source/filter binding."""
    payload = {"v": 2, "kind": kind, "filters": filters.cursor_key(), "provider_cursor": provider_cursor}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_provider_cursor(value: str | None, kind: str, filters: PublicVideoFilters) -> str | None:
    """Reject old, cross-source or cross-filter public Discovery cursors."""
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Invalid cursor") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 2
        or payload.get("kind") != kind
        or payload.get("filters") != filters.cursor_key()
        or not isinstance(payload.get("provider_cursor"), str)
        or not payload["provider_cursor"]
    ):
        raise ValueError("Invalid cursor")
    return payload["provider_cursor"]


def _engine_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract dictionary rows from one Engine list payload defensively."""
    rows = payload.get("rows")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _stored_likes_for_engine(users: UsersRepository, user_id: str) -> list[dict[str, str]]:
    """Map the bounded Client profile likes into the legacy Engine recommendation input."""
    users.get_or_create_user(user_id)
    rows = users.fetch_recent_likes(user_id, MAX_ENGINE_RECOMMENDATION_LIKES)
    likes: list[dict[str, str]] = []
    for row in rows:
        uuid = str(row.get("video_uuid") or "").strip()
        host = str(row.get("instance_domain") or "").strip()
        if uuid and host:
            likes.append({"uuid": uuid, "host": host})
    return likes


def _parse_discovery_request(params: dict[str, list[str]], source: str, *, allow_debug: bool = False) -> tuple[int, PublicVideoFilters, str | None, bool] | ServiceResult:
    """Validate one public Discovery selection and unwrap its provider cursor."""
    allowed = {"limit", "cursor", *FILTER_KEYS}
    if allow_debug:
        allowed.update({"debug", "user_id", "userId"})
    if rejected := validate_query_params(params, allowed):
        return rejected
    try:
        limit = parse_limit(_first_query_value(params, "limit"))
        filters = parse_public_video_filters(params)
        provider_cursor = _decode_provider_cursor(_first_query_value(params, "cursor"), source, filters)
    except ValueError as exc:
        return error_result(400, str(exc), ERROR_BAD_REQUEST)
    return limit, filters, provider_cursor, _parse_bool(_first_query_value(params, "debug"))


def _provider_engine_error(exc: EngineApiError) -> ServiceResult:
    """Map semantic provider HTTP failures without collapsing them into gateway errors."""
    if exc.status == 400 and exc.code == "stale_cursor":
        return error_result(400, "Discovery cursor is stale", ERROR_STALE_CURSOR)
    if exc.status == 503 and exc.code == "random_provider_unavailable":
        return error_result(503, "Random provider unavailable", ERROR_PROVIDER_UNAVAILABLE)
    if exc.status is not None and 400 <= exc.status < 500:
        return error_result(exc.status, str(exc.body.get("error") or "Invalid discovery request"), ERROR_BAD_REQUEST)
    return error_result(502, f"Engine unavailable: {exc}", ERROR_ENGINE_UNAVAILABLE)


def handle_video_facets(engine_base_url: str) -> ServiceResult:
    """Proxy the global facet resource without coupling it to feed/search success."""
    try:
        payload = fetch_engine_video_facets(engine_base_url)
    except EngineApiError as exc:
        return ServiceResult(
            502,
            {
                "error": f"Engine unavailable: {exc}",
                "code": "V1_VIDEO_FACETS_ENGINE_UNAVAILABLE",
            },
        )
    return ServiceResult(200, payload)


def _public_provider_envelope(payload: dict[str, Any], *, source: str, limit: int, filters: PublicVideoFilters) -> dict[str, Any]:
    """Shape Engine-owned pagination without recutting or interpreting its page."""
    pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
    provider_cursor = pagination.get("next_cursor")
    has_more = bool(pagination.get("has_more")) and isinstance(provider_cursor, str) and bool(provider_cursor)
    return {
        "items": normalize_video_rows_for_browser(_engine_rows(payload)),
        "pagination": {
            "limit": limit,
            "next_cursor": _encode_provider_cursor(source, filters, provider_cursor) if has_more else None,
            "has_more": has_more,
        },
        "meta": {"source": source, "fallback": False, "filters": filters.as_dict()},
    }


def handle_ordered_feed(engine_base_url: str, params: dict[str, list[str]], kind: str) -> ServiceResult:
    """Handle Fresh/Popular by forwarding opaque provider continuation state."""
    parsed = _parse_discovery_request(params, kind)
    if isinstance(parsed, ServiceResult):
        return parsed
    limit, filters, provider_cursor, _debug = parsed
    try:
        payload = fetch_engine_discovery(engine_base_url, kind, limit, provider_cursor, filters.as_query())
    except EngineApiError as exc:
        return _provider_engine_error(exc)
    return ServiceResult(200, _public_provider_envelope(payload, source=kind, limit=limit, filters=filters))


def handle_random(engine_base_url: str, params: dict[str, list[str]]) -> ServiceResult:
    """Handle persisted-order Random with the same public provider cursor wrapper."""
    parsed = _parse_discovery_request(params, "random")
    if isinstance(parsed, ServiceResult):
        return parsed
    limit, filters, provider_cursor, _debug = parsed
    try:
        payload = fetch_engine_discovery(engine_base_url, "random", limit, provider_cursor, filters.as_query())
    except EngineApiError as exc:
        return _provider_engine_error(exc)
    return ServiceResult(200, _public_provider_envelope(payload, source="random", limit=limit, filters=filters))


def handle_recommendations(users: UsersRepository, engine_base_url: str, user_id: str, params: dict[str, list[str]]) -> ServiceResult:
    """Adapt the finite legacy home recommendation computation to Discovery v1."""
    parsed = _parse_discovery_request(params, "recommendations", allow_debug=True)
    if isinstance(parsed, ServiceResult):
        return parsed
    limit, filters, provider_cursor, debug = parsed
    if provider_cursor is not None or _first_query_value(params, "cursor"):
        return error_result(400, "Invalid cursor", ERROR_BAD_REQUEST)
    likes = _stored_likes_for_engine(users, user_id)
    try:
        # TEMP-DISCOVERY-RECOMMENDATIONS: adapt the finite legacy Engine batch to terminal Discovery pagination; remove when Engine recommendations expose a native continuation contract.
        payload = fetch_engine_recommendations(engine_base_url, likes, user_id, limit, debug=debug, filters=filters.as_query())
    except EngineApiError as exc:
        if exc.status is not None and 400 <= exc.status < 500:
            return error_result(exc.status, str(exc.body.get("error") or "Invalid discovery request"), ERROR_BAD_REQUEST)
        return error_result(502, f"Engine unavailable: {exc}", ERROR_ENGINE_UNAVAILABLE)
    no_signals = not likes
    meta: dict[str, Any] = {"source": "recommendations", "fallback": no_signals, "filters": filters.as_dict()}
    if no_signals:
        meta["fallback_reason"] = "guest_profile"
    return ServiceResult(200, {
        "items": normalize_video_rows_for_browser(_engine_rows(payload)),
        "pagination": {"limit": limit, "next_cursor": None, "has_more": False},
        "meta": meta,
    })


def _build_similar_envelope(rows: list[dict[str, Any]], *, limit: int, offset: int, seed: dict[str, str]) -> dict[str, Any]:
    """Preserve the pre-existing Similar offset pagination independently of Home."""
    items = normalize_video_rows_for_browser(rows[:limit])
    has_more = len(rows) > limit
    return {
        "items": items,
        "pagination": {
            "limit": limit,
            "next_cursor": _encode_legacy_cursor("similar", offset + len(items), seed=seed) if has_more else None,
            "has_more": has_more,
        },
        "meta": {"source": "similar", "fallback": False},
    }

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
    payload = normalize_video_row_for_browser(payload)
    return ServiceResult(200, payload)


def handle_similar(engine_base_url: str, video_ref: str, params: dict[str, list[str]]) -> ServiceResult:
    """Handle ``GET /api/v1/videos/{id}/similar``."""
    if rejected := validate_query_params(params, {"host", "limit", "cursor", "debug"}):
        return rejected
    host = str(_first_query_value(params, "host") or "").strip()
    if not host:
        return error_result(400, "Missing host", ERROR_MISSING_HOST)
    seed = {"id": video_ref, "host": host}
    page = _parse_similar_page(params, "similar", seed=seed)
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
    return ServiceResult(200, _build_similar_envelope(rows, limit=page.limit, offset=page.offset, seed=seed))
