"""Video metadata endpoint handler.

Responsibilities:
- Resolve video row by id/uuid/host.
- Merge DB metadata with live instance metadata (when available).
- Return normalized response for the client video page.
"""
import json
import logging
import sqlite3
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from data.time import now_ms
from data.popularity import compute_popularity
from http_utils import respond_json


def fetch_video_row(
    conn: sqlite3.Connection,
    video_id: str,
    host: str | None,
    error_threshold: int | None = None,
) -> dict[str, Any] | None:
    """Fetch a video row from DB by id/uuid and optional host."""
    error_clause = ""
    params = {"id": video_id, "host": host}
    if error_threshold is not None and error_threshold > 0:
        error_clause = "AND (v.error_count IS NULL OR v.error_count < :threshold)"
        params["threshold"] = error_threshold
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
          {error_clause}
        LIMIT 1
        """.format(error_clause=error_clause),
        params,
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def fetch_instance_json(host: str, path: str) -> dict[str, Any] | None:
    """Fetch JSON from a PeerTube instance API path."""
    url = f"https://{host}{path}"
    req = Request(url, headers={"accept": "application/json"})
    try:
        with urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                return None
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except (HTTPError, URLError, TimeoutError) as exc:  # pragma: no cover
        logging.info("[video] instance request failed: %s", exc)
        return None


def resolve_asset_url(host: str, value: str | None) -> str:
    """Normalize asset URL to absolute https URL for an instance."""
    if not value or not host:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"https://{host}{value}"


def pick_text(*values: Any) -> str | None:
    """Return the first non-empty string value."""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def pick_number(*values: Any) -> int | None:
    """Return the first numeric value (int-like) or None."""
    for value in values:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def resolve_avatar_url(host: str, source: Any) -> str:
    """Extract avatar URL from API payload and normalize to absolute URL."""
    if not isinstance(source, dict):
        return ""
    avatar = source.get("avatar")
    if isinstance(avatar, dict):
        url = avatar.get("url")
        if isinstance(url, str):
            return resolve_asset_url(host, url)
        path = avatar.get("path")
        if isinstance(path, str):
            return resolve_asset_url(host, path)
    return ""


def to_tags_json(value: Any) -> str | None:
    """Convert list of tags to JSON string (or None)."""
    if isinstance(value, list):
        tags = [tag for tag in value if isinstance(tag, str)]
        return json.dumps(tags) if tags else None
    return None


def extract_category(value: Any) -> str | None:
    """Extract category label/name from API payload."""
    if isinstance(value, dict):
        return pick_text(value.get("label"), value.get("name"))
    if isinstance(value, str):
        return value
    return None


def to_nullable_bool(value: Any) -> int | None:
    """Normalize truthy/falsy values into 0/1 or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value != 0)
    if isinstance(value, str):
        return int(value.strip().lower() in {"1", "true", "yes"})
    return None


def fetch_instance_video_dynamic(host: str, video_id: str) -> dict[str, Any]:
    """Fetch live video metadata from instance and normalize fields."""
    detail = fetch_instance_json(host, f"/api/v1/videos/{quote(video_id)}") or {}
    account = detail.get("account") or {}
    channel = detail.get("channel") or {}
    tags = detail.get("tags") or []
    channel_slug = pick_text(channel.get("name"))
    channel_display = pick_text(channel.get("displayName"), channel.get("display_name"))
    channel_followers = pick_number(
        channel.get("followersCount"), channel.get("followers_count"), channel.get("followers")
    )

    channel_detail = None
    if channel_slug:
        channel_detail = fetch_instance_json(host, f"/api/v1/video-channels/{quote(channel_slug)}")
        if isinstance(channel_detail, dict):
            channel_display = pick_text(
                channel_display,
                channel_detail.get("displayName"),
                channel_detail.get("display_name"),
            )
            channel_followers = pick_number(
                channel_detail.get("followersCount"),
                channel_detail.get("followers_count"),
                channel_detail.get("followers"),
            ) or channel_followers
    return {
        "title": pick_text(detail.get("name"), detail.get("title")),
        "description": pick_text(detail.get("description")),
        "views": pick_number(detail.get("views"), detail.get("viewsCount"), detail.get("views_count")),
        "likes": pick_number(detail.get("likes"), detail.get("likesCount"), detail.get("likes_count")),
        "dislikes": pick_number(
            detail.get("dislikes"), detail.get("dislikesCount"), detail.get("dislikes_count")
        ),
        "tags_json": to_tags_json(tags),
        "category": extract_category(detail.get("category")),
        "nsfw": to_nullable_bool(detail.get("nsfw")),
        "channel_slug": channel_slug,
        "channel_display": channel_display,
        "channel_followers": channel_followers,
        "account_name": pick_text(account.get("displayName"), account.get("display_name"), account.get("name")),
        "account_url": pick_text(account.get("url")),
        "account_avatar_url": resolve_avatar_url(host, account) or resolve_avatar_url(host, detail),
    }


def handle_video_request(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    """Handle /api/video request and respond with merged metadata."""
    id_param = params.get("id", params.get("video_id", [None]))[0]
    host_param = params.get("host", params.get("instance_domain", [None]))[0]
    if not id_param:
        respond_json(handler, 400, {"error": "Missing video id"})
        return True
    with server.db_lock:
        row = fetch_video_row(
            server.db,
            id_param,
            host_param,
            error_threshold=server.video_error_threshold,
        )
    if not row:
        respond_json(handler, 404, {"error": "Video not found"})
        return True

    instance_domain = row.get("instance_domain") or host_param or ""
    dynamic = fetch_instance_video_dynamic(instance_domain, id_param) if instance_domain else {}

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
    tags_json = dynamic.get("tags_json")
    if tags_json is None:
        tags_json = row.get("tags_json")
    category = dynamic.get("category")
    if category is None:
        category = row.get("category")
    nsfw = dynamic.get("nsfw")
    if nsfw is None:
        nsfw = row.get("nsfw")

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
        "views": views,
        "likes": likes,
        "dislikes": dislikes,
        "publishedAt": row.get("published_at"),
    }

    channel_id = row.get("channel_id")
    if dynamic and instance_domain and row.get("video_id"):
        checked_at = now_ms()
        popularity = compute_popularity(
            views,
            likes,
            row.get("published_at"),
            float(getattr(server, "popularity_like_weight", 2.0)),
            now_ms_value=checked_at,
        )
        try:
            with server.db_lock:
                with server.db:
                    server.db.execute(
                        """
                        UPDATE videos
                        SET title = ?, description = ?, channel_name = ?, views = ?, likes = ?, dislikes = ?,
                            popularity = ?,
                            tags_json = ?, category = ?, nsfw = ?, last_checked_at = ?
                        WHERE video_id = ? AND instance_domain = ?
                        """,
                        (
                            title,
                            description,
                            channel_display,
                            views,
                            likes,
                            dislikes,
                            popularity,
                            tags_json,
                            category,
                            nsfw,
                            checked_at,
                            row.get("video_id"),
                            instance_domain,
                        ),
                    )
                    if channel_id:
                        server.db.execute(
                            """
                            UPDATE channels
                            SET channel_name = ?, display_name = ?, followers_count = ?
                            WHERE channel_id = ? AND instance_domain = ?
                            """,
                            (
                                channel_slug,
                                channel_display,
                                channel_followers,
                                channel_id,
                                instance_domain,
                            ),
                        )
                    server.db.execute(
                        """
                        UPDATE instances
                        SET last_error = NULL, last_error_at = NULL, last_error_source = NULL
                        WHERE host = ?
                        """,
                        (instance_domain,),
                    )
        except sqlite3.OperationalError as exc:
            logging.warning(
                "[video] failed to persist dynamic metadata for video_id=%s host=%s: %s",
                row.get("video_id"),
                instance_domain,
                exc,
            )

    respond_json(handler, 200, response)
    return True
