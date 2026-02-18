"""Provide sources runtime helpers."""

from __future__ import annotations

# Source registry and factory for "similar from likes" recommendation inputs.


from typing import Any, Protocol

from recommendations.sources.ann_similar_from_likes import AnnSimilarFromLikesDeps, AnnSimilarFromLikesSource
from recommendations.sources.cached_similar_from_likes import (
    CachedSimilarFromLikesDeps,
    CachedSimilarFromLikesSource,
)


class SimilarFromLikesSource(Protocol):
    """Interface for sources that return candidates similar to user likes."""
    name: str

    def get_candidates(
        self, server: Any, user_id: str, limit: int, refresh_cache: bool = False
    ) -> list[dict[str, Any]]:
        """Return candidates similar to the user's liked videos."""
        raise NotImplementedError


def build_similar_from_likes_source(
    name: str,
    ann_deps: AnnSimilarFromLikesDeps,
    cached_deps: CachedSimilarFromLikesDeps,
) -> SimilarFromLikesSource:
    """Build a similar-from-likes source by name ("ann" or "cache-optimized")."""
    if name == AnnSimilarFromLikesSource.name:
        return AnnSimilarFromLikesSource(ann_deps)
    if name == CachedSimilarFromLikesSource.name:
        return CachedSimilarFromLikesSource(cached_deps)
    raise ValueError(f"Unknown similar-from-likes source: {name}")
