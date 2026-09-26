"""Client-owned public Search API v1 service helpers."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from lib.engine_api_client import EngineApiError, fetch_engine_channel_search, fetch_engine_video_search
from schemas import ServiceResult
from services.video_filters_v1 import FILTER_KEYS, PublicVideoFilters, parse_public_video_filters
from services.video_rows import normalize_video_rows_for_browser

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MIN_LIMIT = 1
ERROR_BAD_REQUEST = "V1_SEARCH_BAD_REQUEST"
ERROR_ENGINE_UNAVAILABLE = "V1_SEARCH_ENGINE_UNAVAILABLE"


@dataclass(frozen=True)
class SearchRequest:
    """Validated public search request values."""
    query: str
    limit: int
    offset: int
    filters: PublicVideoFilters


def error_result(status: int, message: str, code: str) -> ServiceResult:
    """Build a v1 search error payload."""
    return ServiceResult(status, {"error": message, "code": code})


def _first(params: dict[str, list[str]], key: str) -> str | None:
    """Return the first raw value for one single-valued public search key."""
    values = params.get(key)
    return values[0] if values else None


def _parse_limit(value: str | None) -> int:
    """Parse and clamp public search limits while preserving legacy defaults."""
    if value is None or not str(value).strip():
        return DEFAULT_LIMIT
    try:
        parsed = int(value)
    except ValueError:
        return DEFAULT_LIMIT
    return min(max(parsed, MIN_LIMIT), MAX_LIMIT)


def encode_cursor(kind: str, offset: int, query: str, filters: PublicVideoFilters | None = None) -> str:
    """Encode a Client-owned search cursor scoped to its full selection identity."""
    payload: dict[str, Any] = {"v": 2 if filters is not None else 1, "kind": kind, "offset": offset, "q": query}
    if filters is not None:
        payload["filters"] = filters.cursor_key()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str | None, expected_kind: str, query: str, filters: PublicVideoFilters | None = None) -> int:
    """Decode a cursor and reject cross-query/filter/endpoint reuse."""
    if not value:
        return 0
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Invalid cursor") from exc
    expected_version = 2 if filters is not None else 1
    if (
        not isinstance(payload, dict)
        or type(payload.get("v")) is not int
        or payload.get("v") != expected_version
        or payload.get("kind") != expected_kind
        or payload.get("q") != query
    ):
        raise ValueError("Invalid cursor")
    if filters is not None and payload.get("filters") != filters.cursor_key():
        raise ValueError("Invalid cursor")
    offset = payload.get("offset")
    if type(offset) is not int or offset < 0:
        raise ValueError("Invalid cursor")
    return offset


def _validate_params(params: dict[str, list[str]], kind: str, *, video: bool) -> SearchRequest | ServiceResult:
    """Validate public search parameters at the Client protocol boundary."""
    allowed = {"q", "limit", "cursor", *FILTER_KEYS} if video else {"q", "limit", "cursor"}
    for key in params:
        if key not in allowed:
            return error_result(400, f"Unknown query parameter: {key}", ERROR_BAD_REQUEST)
    query = (_first(params, "q") or "").strip()
    if not query:
        return error_result(400, "Missing q", ERROR_BAD_REQUEST)
    try:
        filters = parse_public_video_filters(params) if video else PublicVideoFilters()
        offset = decode_cursor(_first(params, "cursor"), kind, query, filters if video else None)
    except ValueError as exc:
        return error_result(400, str(exc), ERROR_BAD_REQUEST)
    return SearchRequest(query=query, limit=_parse_limit(_first(params, "limit")), offset=offset, filters=filters)


def _envelope(items: list[dict[str, Any]], *, query: str, limit: int, offset: int, kind: str, source: str, filters: PublicVideoFilters | None = None, index: str | None = None, normalize_video_items: bool = False) -> dict[str, Any]:
    """Build the public v1 search envelope from one extra fetched row."""
    raw_page_items = items[:limit]
    page_items = normalize_video_rows_for_browser(raw_page_items) if normalize_video_items else raw_page_items
    has_more = len(items) > limit
    meta: dict[str, Any] = {"source": source, "query": query}
    if filters is not None:
        meta["filters"] = filters.as_dict()
    if index:
        meta["index"] = index
    return {
        "items": page_items,
        "pagination": {
            "limit": limit,
            "next_cursor": encode_cursor(kind, offset + len(page_items), query, filters) if has_more else None,
            "has_more": has_more,
        },
        "meta": meta,
    }


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract dictionary rows from an Engine search response defensively."""
    rows = payload.get("rows")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def handle_video_search(engine_base_url: str, params: dict[str, list[str]]) -> ServiceResult:
    """Handle video search with a cursor bound to query plus video filters."""
    req = _validate_params(params, "search_videos", video=True)
    if isinstance(req, ServiceResult):
        return req
    try:
        payload = fetch_engine_video_search(engine_base_url, req.query, req.limit, req.offset, req.filters.as_query())
    except EngineApiError as exc:
        if exc.status is not None and 400 <= exc.status < 500:
            return error_result(exc.status, str(exc.body.get("error") or "Invalid search request"), ERROR_BAD_REQUEST)
        return error_result(502, f"Engine unavailable: {exc}", ERROR_ENGINE_UNAVAILABLE)
    rows = normalize_video_rows_for_browser(_rows(payload))
    has_more = bool(payload.get("has_more")) and bool(payload.get("next_cursor"))
    return ServiceResult(200, {
        "items": rows,
        "pagination": {
            "limit": req.limit,
            "next_cursor": encode_cursor("search_videos", req.offset + len(rows), req.query, req.filters) if has_more else None,
            "has_more": has_more,
        },
        "meta": {
            "source": "search_videos",
            "query": req.query,
            "filters": req.filters.as_dict(),
            "index": "sqlite_fts5_light",
        },
    })


def handle_channel_search(engine_base_url: str, params: dict[str, list[str]]) -> ServiceResult:
    """Handle channel search without applying video-only filters."""
    req = _validate_params(params, "search_channels", video=False)
    if isinstance(req, ServiceResult):
        return req
    try:
        payload = fetch_engine_channel_search(engine_base_url, req.query, req.limit + 1, req.offset)
    except EngineApiError as exc:
        return error_result(502, f"Engine unavailable: {exc}", ERROR_ENGINE_UNAVAILABLE)
    return ServiceResult(200, _envelope(_rows(payload), query=req.query, limit=req.limit, offset=req.offset, kind="search_channels", source="search_channels"))
