"""Video metadata endpoint handler.

Responsibilities:
- Resolve video row by id/uuid/host.
- Merge DB metadata with live instance metadata (when available).
- Return normalized response for the client video page.
"""
import sqlite3
from typing import Any
from urllib.parse import quote

from data.serving_moderation import ServingVisibility, build_serving_visibility_sql, serving_visibility_from_server
from data.video_thumbnails import apply_thumbnail_api_fields
from route_results import RouteResult
from services.peertube_video_detail import fetch_peertube_video_detail


def fetch_video_row(
    conn: sqlite3.Connection,
    video_id: str,
    host: str | None,
    visibility: ServingVisibility,
) -> dict[str, Any] | None:
    """Fetch a video row from DB by id/uuid and optional host."""
    # Enforce canonical availability and active moderation before picking any candidate.
    visibility_sql = build_serving_visibility_sql("v", visibility)
    params = {"id": video_id, "host": host}
    row = conn.execute(
        """
        SELECT
          v.video_id,
          v.video_uuid,
          v.instance_domain,
          v.channel_id,
          v.channel_name,
          v.channel_url,
          v.account_name,
          v.account_url,
          v.title,
          v.description,
          v.thumbnail_url,
          v.thumbnail_candidates_json,
          v.preview_path,
          v.embed_path,
          v.published_at,
          v.video_url,
          v.views,
          v.likes,
          v.dislikes,
          v.tags_json,
          v.category,
          v.nsfw,
          v.last_checked_at,
          c.channel_name AS channel_slug,
          c.display_name AS channel_display_name,
          c.followers_count AS channel_followers_count,
          c.avatar_url AS channel_avatar_url
        FROM videos v
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        WHERE (v.video_id = :id OR v.video_uuid = :id)
          AND (:host IS NULL OR v.instance_domain = :host)
          AND {visibility_sql}
        LIMIT 1
        """.format(visibility_sql=visibility_sql),
        params,
    ).fetchone()
    if row is None:
        return None
    return apply_thumbnail_api_fields(dict(row))


def resolve_asset_url(host: str, value: str | None) -> str:
    """Normalize asset URL to absolute https URL for an instance."""
    if not value or not host:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"https://{host}{value}"


def handle_video_request(server: Any, params: dict[str, list[str]]) -> RouteResult:
    """Return /api/video merged metadata response data."""
    id_param = params.get("id", params.get("video_id", [None]))[0]
    host_param = params.get("host", params.get("instance_domain", [None]))[0]
    if not id_param:
        return RouteResult(400, {"error": "Missing video id"})
    with server.db_lock:
        row = fetch_video_row(
            server.db,
            id_param,
            host_param,
            visibility=serving_visibility_from_server(server),
        )
    if not row:
        return RouteResult(404, {"error": "Video not found"})

    instance_domain = row.get("instance_domain") or ""
    # The network address uses only the canonical UUID already admitted by SQLite.
    observation = fetch_peertube_video_detail(instance_domain, row.get("video_uuid"))
    if observation.kind in {"not_found", "gone"}:
        return RouteResult(404, {"error": "Video not found"})
    dynamic = observation.detail if observation.kind == "available" else {}

    title = dynamic.get("title") or row.get("title")
    description = dynamic.get("description") or row.get("description")
    views = dynamic.get("views")
    if views is None:
        views = row.get("views")
    likes = dynamic.get("likes")
    if likes is None:
        likes = row.get("likes")
    dislikes = dynamic.get("dislikes")
    if dislikes is None:
        dislikes = row.get("dislikes")

    channel_display = (
        dynamic.get("channel_display")
        or row.get("channel_display_name")
        or row.get("channel_name")
    )
    channel_slug = dynamic.get("channel_slug") or row.get("channel_slug")
    channel_followers = dynamic.get("channel_followers")
    if channel_followers is None:
        channel_followers = row.get("channel_followers_count")
    channel_url = row.get("channel_url")
    if not channel_url and channel_slug and instance_domain:
        channel_url = f"https://{instance_domain}/video-channels/{quote(channel_slug)}"

    embed_url = resolve_asset_url(instance_domain, row.get("embed_path"))
    original_url = row.get("video_url")
    if not original_url and instance_domain:
        video_key = row.get("video_uuid") or row.get("video_id")
        if video_key:
            original_url = f"https://{instance_domain}/videos/watch/{quote(video_key)}"

    response = {
        "video_id": row.get("video_id") or "",
        "video_uuid": row.get("video_uuid") or "",
        "instance_domain": instance_domain or "",
        "videoUuid": row.get("video_uuid") or "",
        "title": title or "",
        "description": description or "",
        "channelName": channel_display or "",
        "channelUrl": channel_url or "",
        "channelAvatarUrl": row.get("channel_avatar_url") or "",
        "subscribersCount": channel_followers,
        "instanceName": instance_domain or "",
        "instanceUrl": f"https://{instance_domain}" if instance_domain else "",
        "accountName": row.get("account_name") or "",
        "accountUrl": row.get("account_url") or "",
        "accountAvatarUrl": dynamic.get("account_avatar_url") or "",
        "embedUrl": embed_url or "",
        "originalUrl": original_url or "",
        "thumbnail_url": row.get("thumbnail_url"),
        "thumbnail_urls": row.get("thumbnail_urls") or [],
        "preview_path": row.get("preview_path"),
        "views": views,
        "likes": likes,
        "dislikes": dislikes,
        "publishedAt": row.get("published_at"),
    }

    # TODO(peertube-browser-persisted-video-counter-refresh): Move persisted counter refresh
    # to Updater; direct-video requests must remain read-only.
    return RouteResult(200, response)
