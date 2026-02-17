from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from time import perf_counter

from recommendations.filters import apply_author_instance_caps

@dataclass(frozen=True)
class RandomVideosDeps:
    fetch_random_rows_from_cache: Callable[[Any, int], list[dict[str, Any]]]
    fetch_random_rows: Callable[[Any, int], list[dict[str, Any]]]
    fetch_recent_likes: Callable[[str, int], list[dict[str, Any]]]
    fetch_embeddings_by_ids: Callable[[Any, list[dict[str, Any]]], dict[str, np.ndarray]]
    like_key: Callable[[Any], str]
    max_likes: int


class RandomVideosGenerator:
    name = "random"

    def __init__(self, deps: RandomVideosDeps) -> None:
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
        below_explore = bool(config.get("below_explore_min", False))
        explore_min = float(config.get("explore_min", 0.0))
        max_per_instance = int(config.get("max_per_instance") or 0)
        max_per_author = int(config.get("max_per_author") or 0)

        pool_start = perf_counter()
        pool = self._fetch_pool_with_caps(server, limit, max_per_instance, max_per_author)
        pool_ms = int((perf_counter() - pool_start) * 1000)
        if not pool:
            return []
        if not below_explore:
            logging.info(
                "[recommendations] random timing pool=%dms total=%dms size=%d",
                pool_ms,
                pool_ms,
                len(pool),
            )
            return pool

        likes = self.deps.fetch_recent_likes(user_id, self.deps.max_likes)
        if not likes:
            return pool

        emb_start = perf_counter()
        with server.db_lock:
            liked_embeddings = self.deps.fetch_embeddings_by_ids(server.db, likes)
            pool_embeddings = self.deps.fetch_embeddings_by_ids(server.db, pool)
        emb_ms = int((perf_counter() - emb_start) * 1000)
        if not liked_embeddings or not pool_embeddings:
            total_ms = int((perf_counter() - pool_start) * 1000)
            logging.info(
                "[recommendations] random timing pool=%dms emb=%dms total=%dms size=%d",
                pool_ms,
                emb_ms,
                total_ms,
                len(pool),
            )
            return pool

        liked_vectors = _normalize_vectors(list(liked_embeddings.values()))
        if not liked_vectors:
            total_ms = int((perf_counter() - pool_start) * 1000)
            logging.info(
                "[recommendations] random timing pool=%dms emb=%dms total=%dms size=%d",
                pool_ms,
                emb_ms,
                total_ms,
                len(pool),
            )
            return pool

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
            if score < explore_min:
                filtered.append(entry)
        score_ms = int((perf_counter() - score_start) * 1000)

        if len(filtered) > limit:
            filtered = random.sample(filtered, limit)
        logging.info(
            "[recommendations] random below explore_min=%s in-range=%d pool=%d",
            f"{explore_min:.4f}",
            len(filtered),
            len(pool),
        )
        total_ms = int((perf_counter() - pool_start) * 1000)
        logging.info(
            "[recommendations] random timing pool=%dms emb=%dms score=%dms total=%dms size=%d",
            pool_ms,
            emb_ms,
            score_ms,
            total_ms,
            len(pool),
        )
        return filtered if filtered else pool

    def _fetch_pool(self, server: Any, limit: int) -> list[dict[str, Any]]:
        rows = self.deps.fetch_random_rows_from_cache(server, limit)
        if rows:
            return rows
        with server.db_lock:
            return self.deps.fetch_random_rows(server.db, limit)

    def _fetch_pool_with_caps(
        self,
        server: Any,
        limit: int,
        max_per_instance: int,
        max_per_author: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        if max_per_instance <= 0 and max_per_author <= 0:
            return self._fetch_pool(server, limit)

        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        instance_counts: dict[str, int] = {}
        author_counts: dict[str, int] = {}
        attempts = 0
        max_attempts = 5

        while len(selected) < limit and attempts < max_attempts:
            batch = self._fetch_pool(server, limit)
            if not batch:
                break
            filtered, seen, author_counts, instance_counts = apply_author_instance_caps(
                batch,
                max_per_author,
                max_per_instance,
                self.deps.like_key,
                limit=limit - len(selected),
                seen=seen,
                author_counts=author_counts,
                instance_counts=instance_counts,
            )
            if filtered:
                selected.extend(filtered)
            attempts += 1

        return selected


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
