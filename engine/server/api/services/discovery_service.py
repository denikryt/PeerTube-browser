"""Internal Engine discovery provider services and continuation contracts."""
from __future__ import annotations

import base64
import json
import math
import random
from datetime import datetime, timezone
from typing import Any, Mapping

from data.random_cache import RandomCacheUnavailable, read_random_cache_meta
from data.random_videos import (
    FRESH_ORDER,
    POPULAR_ORDER,
    fetch_fresh_page,
    fetch_popular_page,
    fetch_random_provider_range,
)
from data.serving_moderation import serving_visibility_from_server
from data.video_filters import VideoFilters
from route_results import RouteResult
try:
    from engine.server.api.services.video_filter_service import FILTER_KEYS, parse_video_filters
except ModuleNotFoundError:  # pragma: no cover - direct server.py execution path
    from services.video_filter_service import FILTER_KEYS, parse_video_filters

DISCOVERY_DEFAULT_LIMIT = 20
DISCOVERY_MAX_LIMIT = 50
_CURSOR_VERSION = 1

STABLE_VIDEO_FIELDS = (
    "video_id",
    "video_uuid",
    "instance_domain",
    "title",
    "thumbnail_url",
    "preview_path",
    "channel_avatar_url",
    "channel_name",
    "channel_display_name",
    "channel_url",
    "published_at",
    "duration",
    "video_url",
    "embed_path",
    "views",
    "likes",
    "dislikes",
    "language",
    "language_label",
    "category",
    "category_id",
)


def stable_video_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project canonical rows to the stable Engine browser metadata subset."""
    return [{field: row.get(field) for field in STABLE_VIDEO_FIELDS} for row in rows]


def _parse_limit(params: dict[str, list[str]]) -> int:
    """Parse the paged-provider limit independently from recommendation config."""
    values = params.get("limit")
    if not values:
        return DISCOVERY_DEFAULT_LIMIT
    if len(values) != 1:
        raise ValueError("Repeated query parameter: limit")
    try:
        parsed = int(values[0])
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid limit") from exc
    if parsed <= 0:
        raise ValueError("Invalid limit")
    return min(parsed, DISCOVERY_MAX_LIMIT)


def _single_cursor(params: dict[str, list[str]]) -> str | None:
    """Read at most one optional provider cursor value."""
    values = params.get("cursor")
    if not values:
        return None
    if len(values) != 1 or not str(values[0]).strip():
        raise ValueError("Invalid cursor")
    return str(values[0]).strip()


def _encode_cursor(payload: Mapping[str, Any]) -> str:
    """Encode an opaque Engine-owned provider cursor."""
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> dict[str, Any]:
    """Decode an opaque provider cursor and reject malformed/non-object payloads."""
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - malformed cursors are one protocol error
        raise ValueError("Invalid cursor") from exc
    if (
        not isinstance(payload, dict)
        or type(payload.get("v")) is not int
        or payload.get("v") != _CURSOR_VERSION
    ):
        raise ValueError("Invalid cursor")
    return payload


def _decode_ordered_cursor(
    value: str | None,
    *,
    source: str,
    filters: VideoFilters,
    order: tuple[tuple[str, str], ...],
) -> dict[str, Any] | None:
    """Validate an ordered cursor against source, filters and non-null sort keys."""
    if value is None:
        return None
    payload = _decode_cursor(value)
    if payload.get("kind") != "ordered" or payload.get("source") != source:
        raise ValueError("Invalid cursor")
    if payload.get("filters") != list(filters.canonical_key()):
        raise ValueError("Invalid cursor")
    after = payload.get("after")
    if not isinstance(after, dict):
        raise ValueError("Invalid cursor")
    expected = {field for field, _ in order}
    if set(after) != expected or any(after[field] is None for field in expected):
        raise ValueError("Invalid cursor")

    # Cursor values are protocol state, not trusted SQLite parameters. Validate
    # the concrete normalized sort-key domains at the boundary that knows the
    # ordering tuple so malformed cursors cannot create partial/undefined seeks.
    for field, _direction in order:
        value = after[field]
        if field.endswith("_is_null"):
            if type(value) is not int or value not in {0, 1}:
                raise ValueError("Invalid cursor")
        elif field in {"published_sort", "effective_likes_sort", "views_sort", "rank_score"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Invalid cursor")
            if not math.isfinite(float(value)):
                raise ValueError("Invalid cursor")
        elif field in {"instance_domain", "video_id"}:
            if not isinstance(value, str) or not value:
                raise ValueError("Invalid cursor")
        else:  # pragma: no cover - provider orders are declared next to this validator
            raise ValueError("Invalid cursor")
    return after


def _encode_ordered_cursor(
    *, source: str, filters: VideoFilters, after: dict[str, Any]
) -> str:
    """Encode the exact projected provider sort keys as a continuation cursor."""
    return _encode_cursor(
        {
            "v": _CURSOR_VERSION,
            "kind": "ordered",
            "source": source,
            "filters": list(filters.canonical_key()),
            "after": after,
        }
    )



def _validate_params(params: dict[str, list[str]]) -> None:
    """Reject unknown internal provider params instead of silently ignoring drift."""
    allowed = {"limit", "cursor", *FILTER_KEYS}
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ValueError(f"Unknown query parameter: {unknown[0]}")


def _provider_response(
    *, source: str, filters: VideoFilters, rows: list[dict[str, Any]], limit: int, next_cursor: str | None
) -> RouteResult:
    """Return one uniform internal discovery provider envelope."""
    return RouteResult(
        200,
        {
            "generatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
            "source": source,
            "rows": stable_video_rows(rows),
            "pagination": {
                "limit": limit,
                "next_cursor": next_cursor,
                "has_more": next_cursor is not None,
            },
            "meta": {"source": source, "filters": filters.as_public_dict()},
        },
    )


def _handle_ordered(server: Any, source: str, params: dict[str, list[str]]) -> RouteResult:
    """Execute Fresh or age-normalized Trending keyset pagination."""
    _validate_params(params)
    limit = _parse_limit(params)
    filters = parse_video_filters(params)
    cursor = _single_cursor(params)
    # ``popular`` is retained for old callers; the public Trending route owns
    # the same persisted score: views/likes discounted by video age.
    order = FRESH_ORDER if source == "fresh" else POPULAR_ORDER
    after = _decode_ordered_cursor(cursor, source=source, filters=filters, order=order)
    fetcher = fetch_fresh_page if source == "fresh" else fetch_popular_page
    with server.db_lock:
        rows = fetcher(
            server.db,
            limit_plus_one=limit + 1,
            filters=filters,
            visibility=serving_visibility_from_server(server),
            after=after,
        )
    has_more = len(rows) > limit
    returned = rows[:limit]
    next_cursor = None
    if has_more and returned:
        next_cursor = _encode_ordered_cursor(
            source=source, filters=filters, after=dict(returned[-1]["_cursor"])
        )
    return _provider_response(
        source=source,
        filters=filters,
        rows=returned,
        limit=limit,
        next_cursor=next_cursor,
    )


def _decode_random_cursor(
    value: str | None,
    *,
    filters: VideoFilters,
) -> dict[str, Any] | None:
    """Validate structural Random continuation state and its filter identity."""
    if value is None:
        return None
    payload = _decode_cursor(value)
    if payload.get("kind") != "random" or payload.get("filters") != list(filters.canonical_key()):
        raise ValueError("Invalid cursor")
    for field in ("start_position", "resume_position"):
        if type(payload.get(field)) is not int or int(payload[field]) <= 0:
            raise ValueError("Invalid cursor")
    return payload


def _encode_random_cursor(
    *,
    filters: VideoFilters,
    build_id: str,
    start_position: int,
    resume_position: int,
) -> str:
    """Encode minimal persisted-order Random continuation state."""
    return _encode_cursor(
        {
            "v": _CURSOR_VERSION,
            "kind": "random",
            "filters": list(filters.canonical_key()),
            "build_id": build_id,
            "start_position": start_position,
            "resume_position": resume_position,
        }
    )


def _handle_random(server: Any, params: dict[str, list[str]]) -> RouteResult:
    """Traverse one validated persisted random order with at most one wrap."""
    _validate_params(params)
    limit = _parse_limit(params)
    filters = parse_video_filters(params)
    if server.random_cache_db is None:
        return RouteResult(503, {"error": "Random provider unavailable", "code": "random_provider_unavailable"})

    with server.random_cache_lock:
        try:
            meta = read_random_cache_meta(server.random_cache_db)
        except RandomCacheUnavailable:
            return RouteResult(503, {"error": "Random provider unavailable", "code": "random_provider_unavailable"})
        count = int(meta["count"])
        if count == 0:
            return _provider_response(source="random", filters=filters, rows=[], limit=limit, next_cursor=None)
        cursor = _decode_random_cursor(_single_cursor(params), filters=filters)

        if cursor is None:
            start_position = random.randint(1, count)
            resume_position = start_position
        else:
            if cursor.get("build_id") != meta["build_id"]:
                return RouteResult(400, {"error": "Random cursor belongs to another cache generation", "code": "stale_cursor"})
            start_position = int(cursor["start_position"])
            resume_position = int(cursor["resume_position"])
            if start_position > count or resume_position > count:
                return RouteResult(400, {"error": "Invalid cursor"})

        needed = limit + 1
        collected: list[dict[str, Any]] = []
        visibility = serving_visibility_from_server(server)

        # The two cursor positions fully encode whether the one legal wrap has
        # happened.  SQL owns filtering/order/LIMIT inside the chosen range.
        if resume_position < start_position:
            collected.extend(
                fetch_random_provider_range(
                    server.random_cache_db,
                    start_position=resume_position,
                    end_position_exclusive=start_position,
                    limit=needed,
                    filters=filters,
                    visibility=visibility,
                )
            )
        else:
            collected.extend(
                fetch_random_provider_range(
                    server.random_cache_db,
                    start_position=resume_position,
                    end_position_exclusive=None,
                    limit=needed,
                    filters=filters,
                    visibility=visibility,
                )
            )
            if len(collected) < needed and start_position > 1:
                collected.extend(
                    fetch_random_provider_range(
                        server.random_cache_db,
                        start_position=1,
                        end_position_exclusive=start_position,
                        limit=needed - len(collected),
                        filters=filters,
                        visibility=visibility,
                    )
                )

    has_more = len(collected) > limit
    returned = collected[:limit]
    next_cursor = None
    if has_more:
        lookahead = collected[limit]
        lookahead_position = int(lookahead["_position"])
        next_cursor = _encode_random_cursor(
            filters=filters,
            build_id=str(meta["build_id"]),
            start_position=start_position,
            resume_position=lookahead_position,
        )
    return _provider_response(
        source="random",
        filters=filters,
        rows=returned,
        limit=limit,
        next_cursor=next_cursor,
    )


def handle_internal_discovery(server: Any, source: str, params: dict[str, list[str]]) -> RouteResult:
    """Return one internal Fresh/Trending/Random discovery provider page."""
    try:
        if source in {"fresh", "popular", "trending"}:
            return _handle_ordered(server, source, params)
        if source == "random":
            return _handle_random(server, params)
        return RouteResult(404, {"error": "Not found"})
    except ValueError as exc:
        return RouteResult(400, {"error": str(exc)})
