"""User profile and likes endpoints.

Responsibilities:
- Record user actions (like/dislike) into users DB.
- Return recent likes or resolved liked videos.
- Reset user profile (clear likes).
- Accept client-provided likes JSON and resolve it to metadata.
"""
from typing import Any

from data.embeddings import fetch_seed_embedding
from data.metadata import fetch_metadata_by_ids
from data.users import (
    clear_likes,
    fetch_recent_likes,
    get_or_create_user,
    record_like,
)
from data.time import now_ms
from recommendations.keys import like_key
from server_config import DEFAULT_CLIENT_LIKES_MAX
from server_config import MAX_LIKES
from http_utils import read_json_body, respond_json, resolve_user_id


def handle_user_action(handler: Any, server: Any) -> bool:
    """Record a like/dislike action and store embedding in users DB."""
    try:
        body = read_json_body(handler)
        action = body.get("action") if isinstance(body, dict) else None
        video_id = body.get("video_id") if isinstance(body, dict) else None
        host = body.get("host") if isinstance(body, dict) else None
        uuid = body.get("uuid") if isinstance(body, dict) else None
        user_id_raw = body.get("user_id") if isinstance(body, dict) else None
        if not video_id:
            respond_json(handler, 400, {"error": "Missing video_id"})
            return True
        user_id = resolve_user_id(str(user_id_raw) if user_id_raw is not None else None)
        with server.db_lock:
            seed = fetch_seed_embedding(server.db, video_id, host, uuid)
        if not seed:
            respond_json(handler, 404, {"error": "Video embedding not found"})
            return True
        with server.user_db_lock:
            record_like(server.user_db, user_id, str(action or ""), seed, MAX_LIKES)
        respond_json(
            handler,
            200,
            {"ok": True, "user_id": user_id, "updatedAt": now_ms()},
        )
        return True
    except ValueError as exc:
        status = 400 if str(exc) in {"Unsupported action", "Invalid vector dimensions"} else 500
        respond_json(handler, status, {"error": str(exc)})
        return True
    except Exception as exc:  # pragma: no cover
        respond_json(handler, 500, {"error": str(exc)})
        return True


def handle_user_profile_reset(handler: Any, server: Any) -> bool:
    """Clear user likes and return an empty profile payload."""
    body = read_json_body(handler)
    user_id_raw = body.get("user_id") if isinstance(body, dict) else None
    user_id = resolve_user_id(str(user_id_raw) if user_id_raw is not None else None)
    with server.user_db_lock:
        get_or_create_user(server.user_db, user_id)
        clear_likes(server.user_db, user_id)
    respond_json(
        handler,
        200,
        {
            "user_id": user_id,
            "likes": [],
            "updatedAt": now_ms(),
        },
    )
    return True


def handle_user_profile(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    """Return raw recent likes for a user (as stored in users DB)."""
    user_id = resolve_user_id(params.get("user_id", params.get("userId", [None]))[0])
    with server.user_db_lock:
        get_or_create_user(server.user_db, user_id)
        likes = fetch_recent_likes(server.user_db, user_id, MAX_LIKES)
    respond_json(
        handler,
        200,
        {
            "user_id": user_id,
            "likes": likes,
            "updatedAt": now_ms(),
        },
    )
    return True


def handle_user_profile_likes(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    """Return resolved liked videos metadata for a user."""
    user_id = resolve_user_id(params.get("user_id", params.get("userId", [None]))[0])
    limit = _parse_int(params.get("limit", [None])[0])
    limit = min(limit, MAX_LIKES) if limit > 0 else MAX_LIKES
    with server.user_db_lock:
        get_or_create_user(server.user_db, user_id)
        likes = fetch_recent_likes(server.user_db, user_id, limit)
    rows: list[dict[str, Any]] = []
    if likes:
        with server.db_lock:
            metadata = fetch_metadata_by_ids(
                server.db,
                likes,
                error_threshold=server.video_error_threshold,
            )
        for like in likes:
            meta = metadata.get(like_key(like))
            if meta:
                rows.append(meta)
    respond_json(
        handler,
        200,
        {
            "user_id": user_id,
            "likes": rows,
            "updatedAt": now_ms(),
        },
    )
    return True


def handle_user_profile_likes_from_client(handler: Any, server: Any) -> bool:
    """Resolve client-provided likes JSON into video metadata rows."""
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True
    likes = _parse_client_likes(body, DEFAULT_CLIENT_LIKES_MAX)
    if not likes:
        respond_json(handler, 200, {"likes": [], "updatedAt": now_ms()})
        return True
    resolved = _resolve_client_likes(server, likes)
    if not resolved:
        respond_json(handler, 200, {"likes": [], "updatedAt": now_ms()})
        return True
    with server.db_lock:
        metadata = fetch_metadata_by_ids(
            server.db,
            resolved,
            error_threshold=server.video_error_threshold,
        )
    rows: list[dict[str, Any]] = []
    for like in resolved:
        meta = metadata.get(like_key(like))
        if meta:
            rows.append(meta)
    respond_json(
        handler,
        200,
        {
            "likes": rows,
            "updatedAt": now_ms(),
        },
    )
    return True


def _parse_int(value: str | None) -> int:
    """Parse a positive integer; return 0 on invalid input."""
    try:
        parsed = int(value or "0")
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _parse_client_likes(payload: dict[str, Any], max_items: int) -> list[dict[str, str]]:
    """Validate and normalize client likes payload to uuid/host pairs."""
    raw = payload.get("likes")
    if not isinstance(raw, list):
        return []
    likes: list[dict[str, str]] = []
    for entry in raw[: max_items if max_items > 0 else None]:
        if not isinstance(entry, dict):
            continue
        uuid = entry.get("uuid")
        host = entry.get("host")
        if not isinstance(uuid, str) or not uuid.strip():
            continue
        if not isinstance(host, str) or not host.strip():
            continue
        likes.append({"video_uuid": uuid.strip(), "instance_domain": host.strip()})
    return likes


def _resolve_client_likes(server: Any, likes: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Map client likes (uuid/host) to internal video_id rows."""
    if not likes:
        return []
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in likes:
        key = f"{entry['video_uuid']}::{entry['instance_domain']}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)

    conditions = " OR ".join(["(video_uuid = ? AND instance_domain = ?)"] * len(unique))
    params: list[Any] = []
    for entry in unique:
        params.append(entry["video_uuid"])
        params.append(entry["instance_domain"])
    with server.db_lock:
        rows = server.db.execute(
            f"""
            SELECT video_id, video_uuid, instance_domain
            FROM videos
            WHERE {conditions}
            """,
            params,
        ).fetchall()
    lookup = {
        f"{row['video_uuid']}::{row['instance_domain']}": row["video_id"]
        for row in rows
    }
    resolved: list[dict[str, Any]] = []
    for entry in unique:
        key = f"{entry['video_uuid']}::{entry['instance_domain']}"
        video_id = lookup.get(key)
        if not video_id:
            continue
        resolved.append(
            {
                "video_id": str(video_id),
                "video_uuid": entry["video_uuid"],
                "instance_domain": entry["instance_domain"],
            }
        )
    return resolved
