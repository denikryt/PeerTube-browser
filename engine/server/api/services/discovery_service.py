"""Internal Engine discovery provider services."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from data.random_videos import fetch_popular_videos, fetch_recent_videos
from data.serving_moderation import apply_serving_moderation_filters
from route_results import RouteResult

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
)


def stable_video_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project DB rows to the stable Engine row subset without importing ANN stack."""
    return [{field: row.get(field) for field in STABLE_VIDEO_FIELDS} for row in rows]


def _parse_limit(raw: str | None, default_limit: int) -> int:
    try:
        parsed = int(raw or "0")
    except ValueError:
        return 0
    if parsed <= 0:
        return default_limit
    if default_limit > 0 and parsed > default_limit:
        return default_limit
    return parsed


def handle_internal_discovery(server: Any, source: str, params: dict[str, list[str]]) -> RouteResult:
    """Return internal fresh/popular discovery provider rows."""
    limit = _parse_limit(params.get("limit", [str(server.default_limit)])[0], server.default_limit)
    if limit <= 0:
        limit = 20
    with server.db_lock:
        if source == "fresh":
            rows = fetch_recent_videos(server.db, limit, error_threshold=server.video_error_threshold)
        elif source == "popular":
            rows = fetch_popular_videos(server.db, limit, error_threshold=server.video_error_threshold)
        else:
            return RouteResult(404, {"error": "Not found"})
    filtered, _ = apply_serving_moderation_filters(server, rows)
    return RouteResult(
        200,
        {
            "generatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
            "source": source,
            "rows": stable_video_rows(filtered),
        },
    )
