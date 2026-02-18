"""Provide similarity cache manager runtime helpers."""

from __future__ import annotations

# Centralized cache policy helpers for similarity candidates.
#
# This module encapsulates all cache validity rules for similarity candidates:
# - when cached rows are allowed to be read
# - when cache entries must be refreshed
# - when writes are permitted
# It keeps cache behavior consistent across recommendation routes.


import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from data.similarity_cache import (
    fetch_cached_similarities,
    has_cached_similarities,
    store_similarity_cache,
)


@dataclass(frozen=True)
class SimilarityCachePolicy:
    """Cache control knobs for similarity candidate reads/writes."""
    refresh: bool = False
    require_full: bool = True
    allow_read: bool = True
    allow_write: bool = True


def _source_label(source: dict[str, Any]) -> str:
    """Handle source label."""
    video_id = source.get("video_id")
    instance = source.get("instance_domain") or ""
    return f"{video_id}@{instance}" if video_id else str(source)


def read_cached_similarities(
    conn: sqlite3.Connection | None,
    source: dict[str, Any],
    limit: int,
    policy: SimilarityCachePolicy,
) -> list[dict[str, Any]]:
    """Read cached similars if policy allows and the cache is valid."""
    if conn is None or not policy.allow_read or policy.refresh:
        return []
    cached = fetch_cached_similarities(conn, source, limit)
    label = _source_label(source)
    if not cached:
        logging.info("[similar-cache] miss empty source=%s limit=%d", label, limit)
        return []
    if cached and any(entry.get("score") is None for entry in cached):
        logging.info(
            "[similar-cache] miss invalid-score source=%s count=%d", label, len(cached)
        )
        return []
    if policy.require_full and cached and len(cached) != limit:
        logging.info(
            "[similar-cache] miss partial source=%s count=%d limit=%d",
            label,
            len(cached),
            limit,
        )
        return []
    logging.info("[similar-cache] hit source=%s count=%d limit=%d", label, len(cached), limit)
    return cached


def should_write_cache(
    conn: sqlite3.Connection | None,
    source: dict[str, Any],
    policy: SimilarityCachePolicy,
) -> bool:
    """Return True when a cache write is permitted and needed."""
    if conn is None or not policy.allow_write:
        return False
    if policy.refresh:
        return True
    return not has_cached_similarities(conn, source)


def write_cache(
    conn: sqlite3.Connection | None,
    source: dict[str, Any],
    items: list[dict[str, Any]],
    computed_at: int,
    policy: SimilarityCachePolicy,
) -> None:
    """Write cache entries when policy allows it and the cache is stale/missing."""
    if not should_write_cache(conn, source, policy):
        return
    store_similarity_cache(conn, source, items, computed_at)
