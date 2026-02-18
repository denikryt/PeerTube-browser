"""Provide cached similar from likes runtime helpers."""

from __future__ import annotations

# Cache-optimized similarity source for recommendations via shared candidates pipeline.


import random
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from data.similarity_candidates import SimilarityCandidatesPolicy


@dataclass(frozen=True)
class CachedSimilarFromLikesDeps:
    """Dependencies for cache-only similarity candidates sourced from recent likes."""
    fetch_recent_likes: Callable[[str, int], list[dict[str, Any]]]
    fetch_seed_embedding: Callable[
        [Any, str | None, str | None, str | None], dict[str, Any] | None
    ]
    fetch_seed_embeddings_for_likes: Callable[
        [Any, list[dict[str, Any]]], dict[str, dict[str, Any]]
    ]
    get_similar_candidates: Callable[
        [Any, dict[str, Any], int, SimilarityCandidatesPolicy], list[dict[str, Any]]
    ]
    like_key: Callable[[Any], str]
    max_likes: int
    max_likes_for_recs: int
    similar_per_like: int


class CachedSimilarFromLikesSource:
    """Represent cached similar from likes source behavior."""
    name = "cache-optimized"

    def __init__(self, deps: CachedSimilarFromLikesDeps) -> None:
        """Initialize the instance."""
        self.deps = deps

    def get_candidates(
        self, server: Any, user_id: str, limit: int, refresh_cache: bool = False
    ) -> list[dict[str, Any]]:
        """Return cached candidates similar to recent likes (no ANN fallback)."""
        import logging
        logging.info("[recommendations] exploit source=cache-optimized")
        recent_likes = self.deps.fetch_recent_likes(user_id, self.deps.max_likes)
        if not recent_likes:
            return []
        if len(recent_likes) > self.deps.max_likes_for_recs:
            recent_likes = random.sample(recent_likes, self.deps.max_likes_for_recs)

        seed_batch_start = perf_counter()
        with server.db_lock:
            seed_map = self.deps.fetch_seed_embeddings_for_likes(server.db, recent_likes)
        seed_batch_ms = int((perf_counter() - seed_batch_start) * 1000)
        resolved_seed_count = len(
            [key for key in seed_map.keys() if not key.startswith("uuid::")]
        )
        logging.info(
            "[recommendations] exploit cache seed batch ms=%d likes=%d resolved=%d",
            seed_batch_ms,
            len(recent_likes),
            resolved_seed_count,
        )

        liked_keys = {self.deps.like_key(entry) for entry in recent_likes}
        total_likes = len(recent_likes)
        resolved_likes = 0
        skipped_likes: list[str] = []

        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        policy = SimilarityCandidatesPolicy(
            refresh_cache=refresh_cache,
            allow_compute=bool(
                getattr(server, "similarity_allow_ann_on_cache_miss", True)
            ),
            require_full_cache=bool(
                getattr(server, "similarity_require_full_cache", True)
            ),
        )
        for like in recent_likes:
            like_id = self.deps.like_key(like)
            like_start = perf_counter()
            seed_key = like_id
            seed = seed_map.get(seed_key)
            seed_lookup_ms = 0
            if seed is None and like.get("video_uuid"):
                uuid_key = (
                    f"uuid::{like.get('video_uuid')}::{like.get('instance_domain') or ''}"
                )
                seed = seed_map.get(uuid_key)
            if not seed:
                logging.info(
                    "[recommendations] exploit cache like=%s seed=missing seed_lookup_ms=%dms",
                    like_id,
                    seed_lookup_ms,
                )
                skipped_likes.append(self.deps.like_key(like))
                continue
            resolved_likes += 1
            cand_start = perf_counter()
            candidates = self.deps.get_similar_candidates(
                server, seed, self.deps.similar_per_like, policy
            )
            cand_ms = int((perf_counter() - cand_start) * 1000)
            like_ms = int((perf_counter() - like_start) * 1000)
            logging.info(
                "[recommendations] exploit cache like=%s seed_lookup_ms=%dms candidates_ms=%dms total_ms=%dms rows=%d",
                like_id,
                seed_lookup_ms,
                cand_ms,
                like_ms,
                len(candidates),
            )
            for row in candidates:
                key = self.deps.like_key(row)
                if key in liked_keys or key in seen:
                    continue
                seen.add(key)
                rows.append(row)

        random.shuffle(rows)
        logging.info(
            "[recommendations] exploit cache likes total=%d resolved=%d skipped=%d",
            total_likes,
            resolved_likes,
            len(skipped_likes),
        )
        if skipped_likes:
            logging.info(
                "[recommendations] exploit cache likes skipped=%s",
                ", ".join(skipped_likes),
            )
        return rows[:limit]
