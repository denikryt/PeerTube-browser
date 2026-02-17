from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from time import perf_counter

from recommendations.filters import apply_author_instance_caps

@dataclass(frozen=True)
class ExploreRangeDeps:
    fetch_recent_likes: Callable[[str, int], list[dict[str, Any]]]
    fetch_embeddings_by_ids: Callable[[Any, list[dict[str, Any]]], dict[str, np.ndarray]]
    like_key: Callable[[Any], str]
    max_likes: int
    fetch_random_rows_from_cache: Callable[[Any, int], list[dict[str, Any]]]
    fetch_random_rows: Callable[[Any, int], list[dict[str, Any]]]


class ExploreRangeGenerator:
    name = "explore"

    def __init__(self, deps: ExploreRangeDeps) -> None:
        self.deps = deps

    def get_candidates(
        self,
        server: Any,
        user_id: str,
        limit: int,
        refresh_cache: bool = False,
        config: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        config = config or {}
        explore_min = float(config.get("similarity_min", 0.0))
        explore_max = float(config.get("similarity_max", 1.0))
        pool_size = int(config.get("pool_size") or 0)
        max_per_instance = int(config.get("max_per_instance") or 0)
        max_per_author = int(config.get("max_per_author") or 0)
        pool_limit = max(pool_size, limit)

        likes = self.deps.fetch_recent_likes(user_id, self.deps.max_likes)

        if not likes:
            return []
        pool_start = perf_counter()
        pool = self._fetch_pool(server, pool_limit)
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

        emb_start = perf_counter()
        with server.db_lock:
            liked_embeddings = self.deps.fetch_embeddings_by_ids(server.db, likes)
            pool_embeddings = self.deps.fetch_embeddings_by_ids(server.db, pool)
        emb_ms = int((perf_counter() - emb_start) * 1000)
        if not liked_embeddings or not pool_embeddings:
            total_ms = int((perf_counter() - pool_start) * 1000)
            logging.info(
                "[recommendations] explore timing pool=%dms emb=%dms total=%dms size=%d",
                pool_ms,
                emb_ms,
                total_ms,
                len(pool),
            )
            return _sample_pool(pool, limit)

        liked_vectors = _normalize_vectors(list(liked_embeddings.values()))
        if not liked_vectors:
            total_ms = int((perf_counter() - pool_start) * 1000)
            logging.info(
                "[recommendations] explore timing pool=%dms emb=%dms total=%dms size=%d",
                pool_ms,
                emb_ms,
                total_ms,
                len(pool),
            )
            return _sample_pool(pool, limit)

        score_start = perf_counter()
        filtered: list[dict[str, Any]] = []
        for entry in pool:
            key = self.deps.like_key(entry)
            vector = pool_embeddings.get(key)
            score = 0.0
            if vector is not None:
                normalized = _normalize_vector(vector)
                if normalized is not None:
                    score = _max_similarity(normalized, liked_vectors)
            entry["similarity_score"] = score
            if explore_min <= score < explore_max:
                filtered.append(entry)
        score_ms = int((perf_counter() - score_start) * 1000)

        in_range = len(filtered)
        similarities = [
            float(item.get("similarity_score") or 0.0)
            for item in pool
        ]
        pool_min = min(similarities) if similarities else None
        pool_max = max(similarities) if similarities else None
        logging.info(
            "[recommendations] explore pool similarity min=%s max=%s pool=%d",
            f"{pool_min:.4f}" if pool_min is not None else "n/a",
            f"{pool_max:.4f}" if pool_max is not None else "n/a",
            len(pool),
        )
        if in_range > limit:
            filtered = random.sample(filtered, limit)
        else:
            filtered.sort(key=lambda item: float(item.get("similarity_score") or 0.0), reverse=True)
        for entry in filtered:
            entry["debug_explore_pool_size"] = len(pool)
            entry["debug_explore_in_range"] = in_range
        logging.info(
            "[recommendations] explore candidates in-range=%d pool=%d min=%.4f max=%.4f",
            in_range,
            len(pool),
            explore_min,
            explore_max,
        )
        total_ms = int((perf_counter() - pool_start) * 1000)
        logging.info(
            "[recommendations] explore timing pool=%dms emb=%dms score=%dms total=%dms size=%d",
            pool_ms,
            emb_ms,
            score_ms,
            total_ms,
            len(pool),
        )
        return filtered[:limit]

    def _fetch_pool(self, server: Any, limit: int) -> list[dict[str, Any]]:
        rows = self.deps.fetch_random_rows_from_cache(server, limit)
        if rows:
            return rows
        with server.db_lock:
            return self.deps.fetch_random_rows(server.db, limit)


def _sample_pool(pool: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or not pool:
        return []
    if len(pool) <= limit:
        shuffled = list(pool)
        random.shuffle(shuffled)
        return shuffled
    return random.sample(pool, limit)


def _normalize_vectors(vectors: list[np.ndarray]) -> list[np.ndarray]:
    normalized: list[np.ndarray] = []
    for vector in vectors:
        normed = _normalize_vector(vector)
        if normed is not None:
            normalized.append(normed)
    return normalized


def _normalize_vector(vector: np.ndarray) -> np.ndarray | None:
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm == 0:
        return None
    return vector / norm


def _max_similarity(vector: np.ndarray, liked_vectors: list[np.ndarray]) -> float:
    if not liked_vectors:
        return 0.0
    best = -1.0
    for liked in liked_vectors:
        score = float(np.dot(vector, liked))
        if score > best:
            best = score
    return best if best > 0 else 0.0
