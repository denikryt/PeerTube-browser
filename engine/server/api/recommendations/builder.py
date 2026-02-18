"""Provide builder runtime helpers."""

from __future__ import annotations

# Recommendation pipeline builder.
#
# This module centralizes:
# - selection of "similar from likes" source (ANN vs cache-optimized + fallback),
# - construction of generator deps with error-threshold filtering,
# - creation of the mixing strategy with configured generator ordering/ratios.
#
# It does not run queries directly; it only composes dependencies and returns a
# ready-to-use recommendation strategy.


from dataclasses import dataclass
from typing import Any, Callable

from recommendations.candidates.explore_range import ExploreRangeDeps, ExploreRangeGenerator
from recommendations.candidates.exploit_from_likes import (
    ExploitFromLikesDeps,
    ExploitFromLikesGenerator,
)
from recommendations.candidates.fresh_videos import FreshVideosDeps, FreshVideosGenerator
from recommendations.candidates.popular_videos import PopularVideosDeps, PopularVideosGenerator
from recommendations.candidates.random_videos import RandomVideosDeps, RandomVideosGenerator
from recommendations.mixer import MixerDeps, MixingRecommendationStrategy
from recommendations.sources import build_similar_from_likes_source
from recommendations.sources.ann_similar_from_likes import (
    AnnSimilarFromLikesDeps,
    AnnSimilarFromLikesSource,
)
from recommendations.sources.cached_similar_from_likes import (
    CachedSimilarFromLikesDeps,
    CachedSimilarFromLikesSource,
)


@dataclass(frozen=True)
class RecommendationBuilderDeps:
    """Concrete callables required to build recommendation generators.

    All callables are injected from server/runtime wiring to avoid import
    cycles and to keep this module pure (no DB/index globals).
    """
    fetch_recent_likes: Callable[[str, int], list[dict[str, Any]]]
    fetch_seed_embedding: Callable[
        [Any, str | None, str | None, str | None], dict[str, Any] | None
    ]
    fetch_seed_embeddings_for_likes: Callable[
        [Any, list[dict[str, Any]]], dict[str, dict[str, Any]]
    ]
    get_similar_candidates: Callable[[Any, dict[str, Any], int, Any], list[dict[str, Any]]]
    like_key: Callable[[Any], str]
    fetch_embeddings_by_ids: Callable[[Any, list[dict[str, Any]]], dict[str, Any]]
    fetch_random_rows: Callable[..., list[dict[str, Any]]]
    fetch_random_rows_from_cache: Callable[..., list[dict[str, Any]]]
    fetch_recent_videos: Callable[..., list[dict[str, Any]]]
    fetch_popular_videos: Callable[..., list[dict[str, Any]]]


@dataclass(frozen=True)
class RecommendationBuilderSettings:
    """Configuration values that influence generator behavior."""
    max_likes: int
    max_likes_for_recs: int
    similar_per_like: int
    default_similar_from_likes_source: bool
    video_error_threshold: int
    fresh_pool_size: int


def build_recommendation_strategy(
    config: dict[str, Any],
    deps: RecommendationBuilderDeps,
    settings: RecommendationBuilderSettings,
) -> MixingRecommendationStrategy:
    """Build and return the recommendation mixing strategy.

    Inputs:
    - config: recommendation pipeline config (ratios, counts, order, batch size).
    - deps: functional dependencies for data access and similarity retrieval.
    - settings: global numeric settings used by generators.

    Output:
    - MixingRecommendationStrategy configured with exploit/explore/fresh generators.
    """
    def fetch_random_rows_filtered(conn: Any, limit: int) -> list[dict[str, Any]]:
        """Handle fetch random rows filtered."""
        return deps.fetch_random_rows(
            conn, limit, error_threshold=settings.video_error_threshold
        )

    def fetch_random_rows_from_cache_filtered(server: Any, limit: int) -> list[dict[str, Any]]:
        """Handle fetch random rows from cache filtered."""
        return deps.fetch_random_rows_from_cache(
            server, limit, error_threshold=settings.video_error_threshold
        )

    def fetch_recent_videos_filtered(conn: Any, limit: int) -> list[dict[str, Any]]:
        """Handle fetch recent videos filtered."""
        return deps.fetch_recent_videos(
            conn, limit, error_threshold=settings.video_error_threshold
        )

    def fetch_popular_videos_filtered(conn: Any, limit: int) -> list[dict[str, Any]]:
        """Handle fetch popular videos filtered."""
        return deps.fetch_popular_videos(
            conn, limit, error_threshold=settings.video_error_threshold
        )

    ann_deps = AnnSimilarFromLikesDeps(
        fetch_recent_likes=deps.fetch_recent_likes,
        fetch_seed_embedding=deps.fetch_seed_embedding,
        fetch_seed_embeddings_for_likes=deps.fetch_seed_embeddings_for_likes,
        get_similar_candidates=deps.get_similar_candidates,
        like_key=deps.like_key,
        max_likes=settings.max_likes,
        max_likes_for_recs=settings.max_likes_for_recs,
        similar_per_like=settings.similar_per_like,
    )
    cached_deps = CachedSimilarFromLikesDeps(
        fetch_recent_likes=deps.fetch_recent_likes,
        fetch_seed_embedding=deps.fetch_seed_embedding,
        fetch_seed_embeddings_for_likes=deps.fetch_seed_embeddings_for_likes,
        get_similar_candidates=deps.get_similar_candidates,
        like_key=deps.like_key,
        max_likes=settings.max_likes,
        max_likes_for_recs=settings.max_likes_for_recs,
        similar_per_like=settings.similar_per_like,
    )
    source_name = (
        CachedSimilarFromLikesSource.name
        if settings.default_similar_from_likes_source
        else AnnSimilarFromLikesSource.name
    )
    likes_source = build_similar_from_likes_source(source_name, ann_deps, cached_deps)
    likes_fallback = None
    if likes_source.name == CachedSimilarFromLikesSource.name:
        likes_fallback = build_similar_from_likes_source(
            AnnSimilarFromLikesSource.name, ann_deps, cached_deps
        )

    generators = {
        ExploitFromLikesGenerator.name: ExploitFromLikesGenerator(
            ExploitFromLikesDeps(
                source=likes_source,
                fallback_source=likes_fallback,
                fetch_recent_likes=deps.fetch_recent_likes,
                max_likes=settings.max_likes,
            )
        ),
        PopularVideosGenerator.name: PopularVideosGenerator(
            PopularVideosDeps(
                fetch_popular_videos=fetch_popular_videos_filtered,
                fetch_recent_likes=deps.fetch_recent_likes,
                fetch_embeddings_by_ids=deps.fetch_embeddings_by_ids,
                like_key=deps.like_key,
                max_likes=settings.max_likes,
            )
        ),
        RandomVideosGenerator.name: RandomVideosGenerator(
            RandomVideosDeps(
                fetch_random_rows_from_cache=fetch_random_rows_from_cache_filtered,
                fetch_random_rows=fetch_random_rows_filtered,
                fetch_recent_likes=deps.fetch_recent_likes,
                fetch_embeddings_by_ids=deps.fetch_embeddings_by_ids,
                like_key=deps.like_key,
                max_likes=settings.max_likes,
            )
        ),
        ExploreRangeGenerator.name: ExploreRangeGenerator(
            ExploreRangeDeps(
                fetch_recent_likes=deps.fetch_recent_likes,
                fetch_embeddings_by_ids=deps.fetch_embeddings_by_ids,
                like_key=deps.like_key,
                max_likes=settings.max_likes,
                fetch_random_rows_from_cache=fetch_random_rows_from_cache_filtered,
                fetch_random_rows=fetch_random_rows_filtered,
            )
        ),
        FreshVideosGenerator.name: FreshVideosGenerator(
            FreshVideosDeps(
                fetch_recent_videos=fetch_recent_videos_filtered,
                fetch_recent_likes=deps.fetch_recent_likes,
                fetch_embeddings_by_ids=deps.fetch_embeddings_by_ids,
                like_key=deps.like_key,
                max_likes=settings.max_likes,
                pool_size=settings.fresh_pool_size or settings.similar_per_like,
            )
        ),
    }
    mixer_deps = MixerDeps(
        like_key=deps.like_key,
        fetch_recent_likes=deps.fetch_recent_likes,
        max_likes=settings.max_likes,
    )
    return MixingRecommendationStrategy(generators, config, mixer_deps)
