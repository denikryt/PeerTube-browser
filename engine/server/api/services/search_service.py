"""Engine internal search service helpers.

The service validates provider-route input, keeps cursors scoped to video search,
and delegates all index ownership to ``data.video_search``.
"""
from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from route_results import RouteResult
from data.serving_moderation import serving_visibility_from_server
try:
    from engine.server.api.services.video_filter_service import allowed_with_filters, parse_video_filters
except ModuleNotFoundError:  # pragma: no cover - direct server.py execution path
    from services.video_filter_service import allowed_with_filters, parse_video_filters

try:
    from data.video_search import normalize_fts_query, search_videos
except ModuleNotFoundError:  # pragma: no cover - package import fallback.
    from engine.server.data.video_search import normalize_fts_query, search_videos

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MIN_LIMIT = 1
KIND = "search_videos"


@dataclass(frozen=True)
class SearchPage:
    """Validated provider search request parameters."""

    query: str
    limit: int
    offset: int
    filters: Any


def _first(params: dict[str, list[str]], key: str) -> str | None:
    """Return the first parsed query parameter value."""
    values = params.get(key)
    return values[0] if values else None


def _parse_limit(raw: str | None) -> int:
    """Parse and clamp Engine provider limits to the v1 safe range."""
    if raw is None or not str(raw).strip():
        return DEFAULT_LIMIT
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_LIMIT
    return min(max(parsed, MIN_LIMIT), MAX_LIMIT)


def encode_cursor(offset: int) -> str:
    """Encode an internal provider offset cursor scoped to video search."""
    raw = json.dumps({"v": 1, "kind": KIND, "offset": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str | None) -> int:
    """Decode the provider cursor while accepting plain numeric offsets for tests/tools."""
    if not value:
        return 0
    if str(value).isdigit():
        return max(int(str(value)), 0)
    try:
        padded = str(value) + "=" * (-len(str(value)) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - malformed cursors share one HTTP error.
        raise ValueError("Invalid cursor") from exc
    if (
        not isinstance(payload, dict)
        or type(payload.get("v")) is not int
        or payload.get("v") != 1
        or payload.get("kind") != KIND
    ):
        raise ValueError("Invalid cursor")
    offset = payload.get("offset")
    if type(offset) is not int or offset < 0:
        raise ValueError("Invalid cursor")
    return offset


def parse_video_search_params(params: dict[str, list[str]]) -> SearchPage | RouteResult:
    """Validate provider route params before touching the FTS index."""
    for key in params:
        if key not in allowed_with_filters("q", "limit", "cursor"):
            return RouteResult(400, {"error": f"Unknown query parameter: {key}"})
    query = (_first(params, "q") or "").strip()
    if not query or not normalize_fts_query(query):
        return RouteResult(400, {"error": "Missing or invalid q"})
    try:
        offset = decode_cursor(_first(params, "cursor"))
        filters = parse_video_filters(params)
    except ValueError as exc:
        return RouteResult(400, {"error": str(exc)})
    return SearchPage(query=query, limit=_parse_limit(_first(params, "limit")), offset=offset, filters=filters)


def handle_internal_video_search(server: Any, params: dict[str, list[str]]) -> RouteResult:
    """Return Engine provider video search rows for the Client backend."""
    page = parse_video_search_params(params)
    if isinstance(page, RouteResult):
        return page
    try:
        with server.db_lock:
            rows, next_offset = search_videos(
                server.db,
                query=page.query,
                limit=page.limit,
                offset=page.offset,
                filters=page.filters,
                visibility=serving_visibility_from_server(server),
            )
    except sqlite3.OperationalError as exc:
        # Missing FTS tables should be a controlled deploy/index-state response,
        # not an uncaught traceback in the provider route.
        return RouteResult(503, {"error": f"Video search index unavailable: {exc}"})
    return RouteResult(
        200,
        {
            "rows": rows,
            "limit": page.limit,
            "next_cursor": encode_cursor(next_offset) if next_offset is not None else None,
            "has_more": next_offset is not None,
        },
    )
