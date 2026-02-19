"""Provide ann runtime helpers."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

try:
    import faiss  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "faiss is required. Install faiss-cpu in your Python environment."
    ) from exc

from data.embeddings import normalize_vector
from data.metadata import fetch_metadata


def compute_similar_items(server: Any, seed: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """Compute similar items using ANN, mirroring the precompute script behavior."""
    vector = seed["embedding"]
    if server.normalize_queries:
        vector = normalize_vector(vector)
    search_limit = max(limit + 1, limit)
    configured_limit = int(getattr(server, "similarity_search_limit", 0) or 0)
    if configured_limit > 0:
        search_limit = max(search_limit, configured_limit)
    logging.info(
        "[similar-server] ann_search nprobe=%s search_limit=%d configured_limit=%d",
        getattr(getattr(server, "index", None), "nprobe", None),
        search_limit,
        configured_limit,
    )
    with server.index_lock:
        scores, ids = server.index.search(vector.reshape(1, -1), search_limit)
    rowids = [int(item) for item in ids[0] if int(item) > 0]
    logging.info(
        "[similar-server] ann_rowids=%d search_limit=%d",
        len(rowids),
        search_limit,
    )
    with server.db_lock:
        metadata = fetch_metadata(
            server.db,
            rowids,
            error_threshold=getattr(server, "video_error_threshold", None),
        )
    logging.info("[similar-server] ann_metadata=%d", len(metadata))
    source_author_key = None
    if server.similarity_exclude_source_author:
        source_author_key = _author_key(
            seed.get("channel_id") or seed.get("meta", {}).get("channel_id"),
            seed.get("instance_domain") or seed.get("meta", {}).get("instance_domain"),
        )
    author_limit = server.similarity_max_per_author
    author_counts: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for score, rowid in zip(scores[0], ids[0]):
        rowid_int = int(rowid)
        if rowid_int == seed["rowid"]:
            continue
        meta = metadata.get(rowid_int)
        if not meta:
            continue
        author_key = _author_key(meta.get("channel_id"), meta.get("instance_domain"))
        if source_author_key and author_key == source_author_key:
            continue
        if author_limit > 0 and author_key:
            if author_counts.get(author_key, 0) >= author_limit:
                continue
        items.append(
            {
                "video_id": meta["video_id"],
                "instance_domain": meta["instance_domain"],
                "score": float(score),
            }
        )
        if author_limit > 0 and author_key:
            author_counts[author_key] = author_counts.get(author_key, 0) + 1
        if len(items) >= limit:
            break
    logging.info("[similar-server] ann_candidates=%d limit=%d", len(items), limit)
    return [{**item, "rank": index} for index, item in enumerate(items, start=1)]


def search_index(
    index: faiss.Index,
    vector: np.ndarray,
    limit: int,
    exclude_rowid: int | None,
) -> tuple[list[int], list[float]]:
    """Search the ANN index and optionally exclude a rowid."""
    if vector.ndim != 1:
        raise ValueError("Query vector must be 1D")
    k = max(limit + 5, limit)
    scores, ids = index.search(vector.reshape(1, -1), k)
    scores_list = scores[0].tolist()
    ids_list = ids[0].tolist()
    filtered_ids: list[int] = []
    filtered_scores: list[float] = []
    for score, rowid in zip(scores_list, ids_list):
        if rowid < 0:
            continue
        if exclude_rowid is not None and rowid == exclude_rowid:
            continue
        if rowid in filtered_ids:
            continue
        filtered_ids.append(rowid)
        filtered_scores.append(float(score))
        if len(filtered_ids) >= limit:
            break
    return filtered_ids, filtered_scores


def _author_key(channel_id: str | None, instance_domain: str | None) -> str | None:
    """Handle author key."""
    if not channel_id:
        return None
    return f"{channel_id}::{instance_domain or ''}"
