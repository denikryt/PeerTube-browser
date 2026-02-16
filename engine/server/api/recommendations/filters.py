from __future__ import annotations

from typing import Any, Callable


def build_seen_keys(
    server: Any,
    user_id: str,
    fetch_recent_likes: Callable[[Any, str, int], list[dict[str, Any]]],
    like_key: Callable[[Any], str],
    max_likes: int,
) -> set[str]:
    """Return keys that should be excluded from recommendations."""
    with server.user_db_lock:
        likes = fetch_recent_likes(server.user_db, user_id, max_likes)
    return {like_key(entry) for entry in likes}


def has_likes(
    server: Any,
    user_id: str,
    fetch_recent_likes: Callable[[Any, str, int], list[dict[str, Any]]],
    max_likes: int,
) -> bool:
    """Return True when the user has at least one recent like."""
    with server.user_db_lock:
        likes = fetch_recent_likes(server.user_db, user_id, max_likes)
    return bool(likes)


def apply_author_instance_caps(
    candidates: list[dict[str, Any]],
    max_per_author: int,
    max_per_instance: int,
    like_key: Callable[[Any], str] | None = None,
    *,
    limit: int = 0,
    seen: set[str] | None = None,
    author_counts: dict[str, int] | None = None,
    instance_counts: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], set[str] | None, dict[str, int], dict[str, int]]:
    """Filter candidates by per-author/instance caps, preserving order."""
    if not candidates:
        return [], seen, author_counts or {}, instance_counts or {}
    capped_authors = max_per_author > 0
    capped_instances = max_per_instance > 0
    if not capped_authors and not capped_instances and like_key is None:
        return candidates[: limit if limit > 0 else None], seen, author_counts or {}, instance_counts or {}

    if author_counts is None:
        author_counts = {}
    if instance_counts is None:
        instance_counts = {}
    if like_key is not None and seen is None:
        seen = set()

    def author_key(entry: dict[str, Any]) -> str | None:
        channel_id = entry.get("channel_id") or entry.get("channelId")
        if not channel_id:
            return None
        instance = entry.get("instance_domain") or entry.get("instanceDomain") or ""
        return f"{channel_id}::{instance}"

    def instance_key(entry: dict[str, Any]) -> str:
        return str(entry.get("instance_domain") or entry.get("instanceDomain") or "")

    filtered: list[dict[str, Any]] = []
    remaining = limit if limit > 0 else None
    for entry in candidates:
        if remaining is not None and remaining <= 0:
            break
        if like_key is not None and seen is not None:
            key = like_key(entry)
            if key in seen:
                continue
        author = author_key(entry)
        if capped_authors and author:
            if author_counts.get(author, 0) >= max_per_author:
                continue
        instance = instance_key(entry)
        if capped_instances and instance:
            if instance_counts.get(instance, 0) >= max_per_instance:
                continue
        if like_key is not None and seen is not None:
            seen.add(key)
        if author:
            author_counts[author] = author_counts.get(author, 0) + 1
        if instance:
            instance_counts[instance] = instance_counts.get(instance, 0) + 1
        filtered.append(entry)
        if remaining is not None:
            remaining -= 1

    return filtered, seen, author_counts, instance_counts
