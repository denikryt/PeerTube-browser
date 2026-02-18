"""Provide popular videos runtime helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import random
from time import perf_counter

from recommendations.filters import apply_author_instance_caps

@dataclass(frozen=True)
class PopularVideosDeps:
    """Represent popular videos deps behavior."""
    fetch_popular_videos: Callable[[Any, int], list[dict[str, Any]]]
    fetch_recent_likes: Callable[[str, int], list[dict[str, Any]]]
    fetch_embeddings_by_ids: Callable[[Any, list[dict[str, Any]]], dict[str, np.ndarray]]
    like_key: Callable[[Any], str]
    max_likes: int


class PopularVideosGenerator:
    """Represent popular videos generator behavior."""
    name = "popular"

    def __init__(self, deps: PopularVideosDeps) -> None:
        """Initialize the instance."""
        self.deps = deps

    def get_candidates(
        self,
        server: Any,
        user_id: str,
        limit: int,
        refresh_cache: bool = False,
        config: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Handle get candidates."""
        if limit <= 0:
            return []
        config = config or {}
        pool_size = int(config.get("pool_size") or 0)
        max_per_instance = int(config.get("max_per_instance") or 0)
        max_per_author = int(config.get("max_per_author") or 0)
        likes = self.deps.fetch_recent_likes(user_id, self.deps.max_likes)

        pool_start = perf_counter()
        with server.db_lock:
            pool = self.deps.fetch_popular_videos(server.db, max(pool_size, limit))
        pool_ms = int((perf_counter() - pool_start) * 1000)
        if not pool:
            return []
        pool, _, _, _ = apply_author_instance_caps(
            pool,
            max_per_author,
            max_per_instance,
            self.deps.like_key,
        )
        if not pool:
            return []
        if not likes:
            total_ms = int((perf_counter() - pool_start) * 1000)
            logging.info(
                "[recommendations] popular timing pool=%dms total=%dms size=%d",
                pool_ms,
                total_ms,
                len(pool),
            )
            return _random_from_pool(pool, limit)

        emb_start = perf_counter()
        with server.db_lock:
            liked_embeddings = self.deps.fetch_embeddings_by_ids(server.db, likes)
            pool_embeddings = self.deps.fetch_embeddings_by_ids(server.db, pool)
        emb_ms = int((perf_counter() - emb_start) * 1000)
        if not liked_embeddings or not pool_embeddings:
            total_ms = int((perf_counter() - pool_start) * 1000)
            logging.info(
                "[recommendations] popular timing pool=%dms emb=%dms total=%dms size=%d",
                pool_ms,
                emb_ms,
                total_ms,
                len(pool),
            )
            return _random_from_pool(pool, limit)

        liked_vectors = _normalize_vectors(list(liked_embeddings.values()))
        if not liked_vectors:
            total_ms = int((perf_counter() - pool_start) * 1000)
            logging.info(
                "[recommendations] popular timing pool=%dms emb=%dms total=%dms size=%d",
                pool_ms,
                emb_ms,
                total_ms,
                len(pool),
            )
            return _random_from_pool(pool, limit)

        score_start = perf_counter()
        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in pool:
            key = self.deps.like_key(entry)
            vector = pool_embeddings.get(key)
            score = 0.0
            if vector is not None:
                normalized = _normalize_vector(vector)
                if normalized is not None:
                    score = _max_similarity(normalized, liked_vectors)
            entry["similarity_score"] = score
            scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        score_ms = int((perf_counter() - score_start) * 1000)
        logging.info(
            "[recommendations] popular candidates scored=%d pool=%d",
            len(scored),
            len(pool),
        )
        total_ms = int((perf_counter() - pool_start) * 1000)
        logging.info(
            "[recommendations] popular timing pool=%dms emb=%dms score=%dms total=%dms size=%d",
            pool_ms,
            emb_ms,
            score_ms,
            total_ms,
            len(pool),
        )
        ordered = [item[1] for item in scored]
        return _random_from_pool(ordered, limit)


def _normalize_vectors(vectors: list[np.ndarray]) -> list[np.ndarray]:
    """Handle normalize vectors."""
    normalized: list[np.ndarray] = []
    for vector in vectors:
        normed = _normalize_vector(vector)
        if normed is not None:
            normalized.append(normed)
    return normalized


def _normalize_vector(vector: np.ndarray) -> np.ndarray | None:
    """Handle normalize vector."""
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm == 0:
        return None
    return vector / norm


def _max_similarity(vector: np.ndarray, liked_vectors: list[np.ndarray]) -> float:
    """Handle max similarity."""
    if not liked_vectors:
        return 0.0
    best = -1.0
    for liked in liked_vectors:
        score = float(np.dot(vector, liked))
        if score > best:
            best = score
    return best if best > 0 else 0.0


def _random_from_pool(
    candidates: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Handle random from pool."""
    if limit <= 0 or not candidates:
        return []
    if len(candidates) <= limit:
        return candidates
    return random.sample(candidates, limit)
