from __future__ import annotations

"""ANN-backed similarity source for recommendations, via shared candidates pipeline."""

import random
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from data.similarity_candidates import SimilarityCandidatesPolicy


@dataclass(frozen=True)
class AnnSimilarFromLikesDeps:
    """Dependencies for ANN similarity candidates sourced from recent likes."""
    get_or_create_user: Callable[[sqlite3.Connection, str], None]
    fetch_recent_likes: Callable[[sqlite3.Connection, str, int], list[dict[str, Any]]]
    fetch_seed_embedding: Callable[
        [sqlite3.Connection, str | None, str | None, str | None], dict[str, Any] | None
    ]
    fetch_seed_embeddings_for_likes: Callable[
        [sqlite3.Connection, list[dict[str, Any]]], dict[str, dict[str, Any]]
    ]
    get_similar_candidates: Callable[
        [Any, dict[str, Any], int, SimilarityCandidatesPolicy], list[dict[str, Any]]
    ]
    like_key: Callable[[Any], str]
    max_likes: int
    max_likes_for_recs: int
    similar_per_like: int


class AnnSimilarFromLikesSource:
    name = "ann"

    def __init__(self, deps: AnnSimilarFromLikesDeps) -> None:
        self.deps = deps

    def get_candidates(
        self, server: Any, user_id: str, limit: int, refresh_cache: bool = False
    ) -> list[dict[str, Any]]:
        """Return candidates similar to recent likes using ANN + cache policy."""
        import logging
        logging.info("[recommendations] exploit source=ann")
        with server.user_db_lock:
            self.deps.get_or_create_user(server.user_db, user_id)
            recent_likes = self.deps.fetch_recent_likes(
                server.user_db, user_id, self.deps.max_likes
            )
        if not recent_likes:
            return []
        if len(recent_likes) > self.deps.max_likes_for_recs:
            recent_likes = random.sample(recent_likes, self.deps.max_likes_for_recs)
        with server.db_lock:
            seed_map = self.deps.fetch_seed_embeddings_for_likes(server.db, recent_likes)
        liked_keys = {self.deps.like_key(entry) for entry in recent_likes}
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        for like in recent_likes:
            like_id = self.deps.like_key(like)
            seed = seed_map.get(like_id)
            if seed is None and like.get("video_uuid"):
                uuid_key = (
                    f"uuid::{like.get('video_uuid')}::{like.get('instance_domain') or ''}"
                )
                seed = seed_map.get(uuid_key)
            if not seed:
                continue
            policy = SimilarityCandidatesPolicy(
                refresh_cache=refresh_cache,
                require_full_cache=bool(
                    getattr(server, "similarity_require_full_cache", True)
                ),
            )
            entries = self.deps.get_similar_candidates(
                server, seed, self.deps.similar_per_like, policy
            )
            for entry in entries:
                key = self.deps.like_key(entry)
                if key in liked_keys or key in seen:
                    continue
                seen.add(key)
                rows.append(entry)
        random.shuffle(rows)
        return rows[:limit]
