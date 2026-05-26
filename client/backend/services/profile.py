"""Client profile service for local profile and likes metadata behavior."""
from __future__ import annotations

from typing import Any

from lib.engine_api_client import (
    EngineApiError,
    fetch_metadata_for_entries,
    resolve_videos_by_uuid_host,
)
from lib.http_utils import resolve_user_id
from lib.time_utils import now_ms
from repositories.users import UsersRepository
from schemas import ServiceResult


def parse_positive_int(value: str | None) -> int:
    """Parse a positive integer using current Client backend query semantics."""
    try:
        parsed = int(value or "0")
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def parse_client_likes(payload: dict[str, Any], max_items: int) -> list[dict[str, str]]:
    """Parse frontend uuid/host likes into Engine identity entries."""
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


def get_user_profile(users: UsersRepository, user_id: str, max_likes: int) -> ServiceResult:
    """Return the local Client profile payload for one user."""
    users.get_or_create_user(user_id)
    likes = users.fetch_recent_likes(user_id, max_likes)
    return ServiceResult(200, {"user_id": user_id, "likes": likes, "updatedAt": now_ms()})


def reset_user_profile(users: UsersRepository, raw_user_id: Any) -> ServiceResult:
    """Clear local Client likes for one user and return the current reset payload."""
    user_id = resolve_user_id(str(raw_user_id) if raw_user_id is not None else None)
    users.get_or_create_user(user_id)
    users.clear_likes(user_id)
    return ServiceResult(200, {"user_id": user_id, "likes": [], "updatedAt": now_ms()})


def get_profile_likes_metadata(
    users: UsersRepository,
    engine_base_url: str,
    user_id: str,
    limit: int,
    max_likes: int,
) -> ServiceResult:
    """Return Engine-enriched metadata for locally stored likes."""
    bounded_limit = min(limit, max_likes) if limit > 0 else max_likes
    users.get_or_create_user(user_id)
    likes = users.fetch_recent_likes(user_id, bounded_limit)
    try:
        rows = fetch_metadata_for_entries(engine_base_url, likes)
    except EngineApiError as exc:
        return ServiceResult(502, {"error": f"Engine metadata failed: {exc}"})
    return ServiceResult(200, {"user_id": user_id, "likes": rows, "updatedAt": now_ms()})


def get_client_likes_metadata(
    engine_base_url: str,
    body: dict[str, Any],
    max_client_likes: int,
) -> ServiceResult:
    """Resolve frontend-provided uuid/host likes and return Engine metadata rows."""
    likes = parse_client_likes(body, max_client_likes)
    if not likes:
        return ServiceResult(200, {"likes": [], "updatedAt": now_ms()})
    try:
        resolved = resolve_videos_by_uuid_host(engine_base_url, likes)
        rows = fetch_metadata_for_entries(engine_base_url, resolved)
    except EngineApiError as exc:
        return ServiceResult(502, {"error": f"Engine metadata failed: {exc}"})
    return ServiceResult(200, {"likes": rows, "updatedAt": now_ms()})
