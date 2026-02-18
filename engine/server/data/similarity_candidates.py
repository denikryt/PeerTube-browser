"""Provide similarity candidates runtime helpers."""

from __future__ import annotations

# Unified similarity candidate pipeline (cache -> filters -> ranking -> rows).
#
# This module provides a single entry point for building similar candidates used by
# recommendation routes. It centralizes cache policy, ANN fallback,
# and filtering rules (seed exclusion, per-author limits, and error thresholds).


import logging
from time import perf_counter
from dataclasses import dataclass
from typing import Any

from data.metadata import fetch_metadata_by_ids
from data.similarity_cache_manager import (
    SimilarityCachePolicy,
    read_cached_similarities,
    write_cache,
)
from data.time import now_ms
from recommendations.keys import like_key


@dataclass(frozen=True)
class SimilarityCandidatesPolicy:
    """Controls cache usage and ANN fallback behavior for candidate selection."""
    refresh_cache: bool = False
    use_cache: bool = True
    require_full_cache: bool = True
    allow_cache_write: bool = True
    allow_compute: bool = True


def get_similar_candidates(
    server: Any,
    seed: dict[str, Any],
    limit: int,
    policy: SimilarityCandidatesPolicy | None = None,
) -> list[dict[str, Any]]:
    """Return similar candidates for a seed video using cache/ANN policy.

    Output rows include full metadata and a "score" field. Filters are applied
    consistently with the ANN pipeline (seed exclusion, per-author limit, and
    optional exclusion of the source author).
    """
    if limit <= 0:
        return []
    if policy is None:
        policy = SimilarityCandidatesPolicy()

    embedding = seed.get("embedding")
    if embedding is None:
        embedding = seed.get("vector")
    if embedding is None:
        return []
    if seed.get("embedding") is None and seed.get("vector") is not None:
        seed = {**seed, "embedding": seed.get("vector")}

    source = _source_from_seed(seed)
    cache_policy = SimilarityCachePolicy(
        refresh=policy.refresh_cache,
        require_full=policy.require_full_cache,
        allow_read=policy.use_cache,
        allow_write=policy.allow_cache_write,
    )

    timings = {"cache": 0, "compute": 0, "metadata": 0, "filter": 0, "total": 0}
    total_start = perf_counter()
    entries: list[dict[str, Any]] = []
    if source and policy.use_cache:
        cache_start = perf_counter()
        entries = _read_cache(server, source, limit, cache_policy)
        timings["cache"] = int((perf_counter() - cache_start) * 1000)

    if not entries:
        if not policy.allow_compute:
            logging.info(
                "[similar-cache] compute disabled source=%s",
                f"{source.get('video_id')}@{source.get('instance_domain') or ''}"
                if source
                else "unknown",
            )
            return []
        compute_start = perf_counter()
        entries = _compute_candidates(server, seed, limit)
        timings["compute"] = int((perf_counter() - compute_start) * 1000)
        if source:
            _write_cache(server, source, entries, cache_policy)

    rows, meta_ms, filter_ms = _build_rows(server, entries, seed, limit)
    timings["metadata"] = meta_ms
    timings["filter"] = filter_ms
    timings["total"] = int((perf_counter() - total_start) * 1000)
    logging.info(
        "[similar-server] timing cache=%dms compute=%dms meta=%dms filter=%dms total=%dms",
        timings["cache"],
        timings["compute"],
        timings["metadata"],
        timings["filter"],
        timings["total"],
    )
    return rows


def _read_cache(
    server: Any,
    source: dict[str, Any],
    limit: int,
    policy: SimilarityCachePolicy,
) -> list[dict[str, Any]]:
    """Read cached candidates under the similarity DB lock when available."""
    conn = getattr(server, "similarity_db", None)
    if conn is None:
        return []
    lock = getattr(server, "similarity_db_lock", None)
    if lock is None:
        return read_cached_similarities(conn, source, limit, policy)
    with lock:
        return read_cached_similarities(conn, source, limit, policy)


def _write_cache(
    server: Any,
    source: dict[str, Any],
    entries: list[dict[str, Any]],
    policy: SimilarityCachePolicy,
) -> None:
    """Write candidates to cache under the similarity DB lock when available."""
    conn = getattr(server, "similarity_db", None)
    if conn is None:
        return
    lock = getattr(server, "similarity_db_lock", None)
    if lock is None:
        write_cache(conn, source, entries, now_ms(), policy)
        return
    with lock:
        write_cache(conn, source, entries, now_ms(), policy)


def _compute_candidates(
    server: Any, seed: dict[str, Any], limit: int
) -> list[dict[str, Any]]:
    """Compute candidates via ANN, defaulting to data.ann.compute_similar_items."""
    compute = getattr(server, "compute_similar_items", None)
    if compute is None:
        from data.ann import compute_similar_items

        compute = compute_similar_items
    return compute(server, seed, limit)


def _build_rows(
    server: Any,
    entries: list[dict[str, Any]],
    seed: dict[str, Any],
    limit: int,
) -> tuple[list[dict[str, Any]], int, int]:
    """Resolve cached/ANN entries into full metadata rows and apply filters."""
    if not entries:
        return [], 0, 0
    db = getattr(server, "db", None)
    if db is None:
        return [], 0, 0
    lock = getattr(server, "db_lock", None)
    meta_start = perf_counter()
    if lock is None:
        metadata = fetch_metadata_by_ids(
            db, entries, error_threshold=getattr(server, "video_error_threshold", None)
        )
    else:
        with lock:
            metadata = fetch_metadata_by_ids(
                db,
                entries,
                error_threshold=getattr(server, "video_error_threshold", None),
            )
    meta_ms = int((perf_counter() - meta_start) * 1000)

    source_meta = _source_from_seed(seed)
    source_key = like_key(source_meta) if source_meta else None
    source_author_key = _author_key(
        source_meta.get("channel_id") if source_meta else None,
        source_meta.get("instance_domain") if source_meta else None,
    )
    author_limit = int(getattr(server, "similarity_max_per_author", 0) or 0)
    exclude_source_author = bool(getattr(server, "similarity_exclude_source_author", False))

    filter_start = perf_counter()
    author_counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for entry in entries:
        meta = metadata.get(like_key(entry))
        if not meta:
            continue
        if source_key and like_key(meta) == source_key:
            continue
        author_key = _author_key(meta.get("channel_id"), meta.get("instance_domain"))
        if exclude_source_author and source_author_key and author_key == source_author_key:
            continue
        if author_limit > 0 and author_key:
            if author_counts.get(author_key, 0) >= author_limit:
                continue
        if author_limit > 0 and author_key:
            author_counts[author_key] = author_counts.get(author_key, 0) + 1
        rows.append({**meta, "score": entry.get("score")})
        if len(rows) >= limit:
            break
    filter_ms = int((perf_counter() - filter_start) * 1000)

    logging.info("[similar-server] candidates=%d limit=%d", len(rows), limit)
    return rows, meta_ms, filter_ms


def _source_from_seed(seed: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a stable (video_id, instance_domain, channel_id) source from seed."""
    video_id = seed.get("video_id")
    instance_domain = seed.get("instance_domain")
    channel_id = seed.get("channel_id")
    meta = seed.get("meta") or {}
    if not video_id:
        video_id = meta.get("video_id")
    if instance_domain is None:
        instance_domain = meta.get("instance_domain")
    if channel_id is None:
        channel_id = meta.get("channel_id")
    if not video_id:
        return None
    return {
        "video_id": video_id,
        "instance_domain": instance_domain or "",
        "channel_id": channel_id,
    }


def _author_key(channel_id: str | None, instance_domain: str | None) -> str | None:
    """Build a stable author key for per-author filtering."""
    if not channel_id:
        return None
    return f"{channel_id}::{instance_domain or ''}"
