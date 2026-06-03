"""Client-owned public Search API v1 service helpers.

The Client backend owns browser-facing envelopes and opaque cursors while keeping
all Engine-owned search and channel data access behind HTTP helper calls.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from lib.engine_api_client import EngineApiError, fetch_engine_channel_search, fetch_engine_video_search
from schemas import ServiceResult
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


def error_result(status: int, message: str, code: str) -> ServiceResult:
    """Build a v1 search error payload."""
    return ServiceResult(status, {"error": message, "code": code})


def _first(params: dict[str, list[str]], key: str) -> str | None:
    """Return the first query parameter value from parse_qs output."""
    values = params.get(key)
    return values[0] if values else None


def _parse_limit(value: str | None) -> int:
    """Parse and clamp public search limits."""
    if value is None or not str(value).strip():
        return DEFAULT_LIMIT
    try:
        parsed = int(value)
    except ValueError:
        return DEFAULT_LIMIT
    return min(max(parsed, MIN_LIMIT), MAX_LIMIT)


def encode_cursor(kind: str, offset: int, query: str) -> str:
    """Encode a Client-owned cursor scoped by endpoint and query text."""
    raw = json.dumps(
        {"v": 1, "kind": kind, "offset": offset, "q": query},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str | None, expected_kind: str, query: str) -> int:
    """Decode a search cursor and reject cross-endpoint or cross-query reuse."""
    if not value:
        return 0
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - malformed cursors map to one v1 error.
        raise ValueError("Invalid cursor") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid cursor")
    if payload.get("v") != 1 or payload.get("kind") != expected_kind or payload.get("q") != query:
        raise ValueError("Invalid cursor")
    offset = payload.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("Invalid cursor")
    return offset


def _validate_params(params: dict[str, list[str]], kind: str) -> SearchRequest | ServiceResult:
    """Validate common public search route parameters."""
    for key in params:
        if key not in {"q", "limit", "cursor"}:
            return error_result(400, f"Unknown query parameter: {key}", ERROR_BAD_REQUEST)
    query = (_first(params, "q") or "").strip()
    if not query:
        return error_result(400, "Missing q", ERROR_BAD_REQUEST)
    try:
        offset = decode_cursor(_first(params, "cursor"), kind, query)
    except ValueError as exc:
        return error_result(400, str(exc), ERROR_BAD_REQUEST)
    return SearchRequest(query=query, limit=_parse_limit(_first(params, "limit")), offset=offset)


def _envelope(
    items: list[dict[str, Any]],
    *,
    query: str,
    limit: int,
    offset: int,
    kind: str,
    source: str,
    index: str | None = None,
    normalize_video_items: bool = False,
) -> dict[str, Any]:
    """Build the public v1 search envelope from one extra fetched row."""
    raw_page_items = items[:limit]
    page_items = normalize_video_rows_for_browser(raw_page_items) if normalize_video_items else raw_page_items
    has_more = len(items) > limit
    meta: dict[str, Any] = {"source": source, "query": query}
    if index:
        meta["index"] = index
    return {
        "items": page_items,
        "pagination": {
            "limit": limit,
            "next_cursor": encode_cursor(kind, offset + len(page_items), query) if has_more else None,
            "has_more": has_more,
        },
        "meta": meta,
    }


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract list rows from Engine payloads defensively."""
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def handle_video_search(engine_base_url: str, params: dict[str, list[str]]) -> ServiceResult:
    """Handle ``GET /api/v1/search/videos`` through Engine HTTP provider calls."""
    req = _validate_params(params, "search_videos")
    if isinstance(req, ServiceResult):
        return req
    try:
        payload = fetch_engine_video_search(engine_base_url, req.query, req.limit + 1, req.offset)
    except EngineApiError as exc:
        return error_result(502, f"Engine unavailable: {exc}", ERROR_ENGINE_UNAVAILABLE)
    return ServiceResult(
        200,
        _envelope(
            _rows(payload),
            query=req.query,
            limit=req.limit,
            offset=req.offset,
            kind="search_videos",
            source="search_videos",
            index="sqlite_fts5_light",
            normalize_video_items=True,
        ),
    )


def handle_channel_search(engine_base_url: str, params: dict[str, list[str]]) -> ServiceResult:
    """Handle ``GET /api/v1/search/channels`` by wrapping Engine channel search."""
    req = _validate_params(params, "search_channels")
    if isinstance(req, ServiceResult):
        return req
    try:
        payload = fetch_engine_channel_search(engine_base_url, req.query, req.limit + 1, req.offset)
    except EngineApiError as exc:
        return error_result(502, f"Engine unavailable: {exc}", ERROR_ENGINE_UNAVAILABLE)
    return ServiceResult(200, _envelope(_rows(payload), query=req.query, limit=req.limit, offset=req.offset, kind="search_channels", source="search_channels"))
