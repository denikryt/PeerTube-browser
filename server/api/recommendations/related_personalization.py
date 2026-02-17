from __future__ import annotations

"""Re-rank related (similar) videos using user likes without changing the pool.

This module is a *post-processing* step for related videos returned by /api/similar
when a seed video is provided. It does not perform ANN search, does not add/remove
candidates, and does not touch cache. It only reorders the existing list.

Pipeline:
1) Fetch recent likes for the user (limited by max_likes).
2) Fetch embeddings for likes and for the candidate pool.
3) For each candidate, compute:
   - base_score: candidate["score"] from similarity search (default 0.0)
   - user_score: max cosine similarity between candidate vector and any liked vector
4) Final score = alpha * base_score + beta * user_score
5) Sort by final score (desc), stable by original index.

If any required data is missing (no user_id, no likes, missing embeddings), the
input list is returned unchanged.
"""

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from recommendations.keys import like_key


@dataclass(frozen=True)
class RelatedPersonalizationDeps:
    fetch_recent_likes: Callable[[Any, str, int], list[dict[str, Any]]]
    fetch_embeddings_by_ids: Callable[[Any, list[dict[str, Any]]], dict[str, np.ndarray]]
    max_likes: int
    alpha: float
    beta: float


def rerank_related_videos(
    server: Any,
    user_id: str,
    candidates: list[dict[str, Any]],
    deps: RelatedPersonalizationDeps,
) -> list[dict[str, Any]]:
    """Reorder related videos based on user likes without changing the pool."""
    if not candidates or not user_id:
        return candidates

    with server.user_db_lock:
        likes = deps.fetch_recent_likes(server.user_db, user_id, deps.max_likes)
    if not likes:
        return candidates

    with server.db_lock:
        liked_embeddings = deps.fetch_embeddings_by_ids(server.db, likes)
        candidate_embeddings = deps.fetch_embeddings_by_ids(server.db, candidates)
    if not liked_embeddings or not candidate_embeddings:
        return candidates

    liked_vectors = _normalize_vectors(list(liked_embeddings.values()))
    if not liked_vectors:
        return candidates

    base_alpha = float(deps.alpha)
    user_beta = float(deps.beta)
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, candidate in enumerate(candidates):
        key = like_key(candidate)
        vector = candidate_embeddings.get(key)
        user_score = 0.0
        if vector is not None:
            normalized = _normalize_vector(vector)
            if normalized is not None:
                user_score = _max_similarity(normalized, liked_vectors)
        base_score = candidate.get("score")
        base_value = float(base_score) if base_score is not None else 0.0
        final_score = (base_alpha * base_value) + (user_beta * user_score)
        scored.append((final_score, index, candidate))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored]


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
