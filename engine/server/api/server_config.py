"""Provide server config runtime helpers."""

import os


def _resolve_mode_env(name: str, default: str) -> str:
    """Handle resolve mode env."""
    raw = os.environ.get(name, default).strip().lower()
    return raw if raw in {"bridge", "activitypub"} else default


def _resolve_log_profile_env(name: str, default: str) -> str:
    """Handle resolve log profile env."""
    raw = os.environ.get(name, default).strip().lower()
    return raw if raw in {"verbose", "focused"} else default


# Recommendation-domain defaults live in recommendations.config. This module
# re-exports them so existing startup code and tests can keep importing from
# server_config while Stage 5 moves ownership into the recommendation package.
try:
    from recommendations.config import (
        BATCH_SIZE,
        DEFAULT_FRESH_POOL_SIZE,
        DEFAULT_POPULAR_POOL_SIZE,
        RECOMMENDATION_PIPELINE,
        validate_recommendation_config,
    )
except ModuleNotFoundError:  # pragma: no cover - package import fallback.
    from engine.server.api.recommendations.config import (
        BATCH_SIZE,
        DEFAULT_FRESH_POOL_SIZE,
        DEFAULT_POPULAR_POOL_SIZE,
        RECOMMENDATION_PIPELINE,
        validate_recommendation_config,
    )

# Related videos personalization configuration (watch page).
# enabled: toggles re-ranking within the existing similar-videos pool.
# alpha: weight for the base similarity score (video-to-video).
# beta: weight for the user similarity score (candidate vs liked embeddings).
# max_likes: max recent likes considered when computing user similarity.
RELATED_VIDEOS_PERSONALIZATION = {
    "enabled": True,
    "alpha": 0.2,
    "beta": 0.8,
    "max_likes": 5,
}

# Number of recent likes to sample for like-based recommendations.
MAX_LIKES_FOR_RECS = 10
# Number of likes stored per user (0 means unlimited).
MAX_LIKES = 100
# FAISS nprobe: higher improves recall, lower improves speed.
DEFAULT_NPROBE = 24
# Use similarity cache for personalized feed (fallback to ANN if cache misses).
DEFAULT_USE_SIMILARITY_CACHE = True
# Whether to L2-normalize query vectors before ANN search.
DEFAULT_NORMALIZE_QUERIES = False
# Precomputed random rowids stored for fast random feed responses.
DEFAULT_RANDOM_CACHE_SIZE = 500000
# When enabled, random cache is built with per-instance/author caps.
DEFAULT_RANDOM_CACHE_FILTERED_MODE = True
# Caps applied only when DEFAULT_RANDOM_CACHE_FILTERED_MODE is enabled (0 disables).
DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE = 0
DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR = 100
# Rebuild random cache on startup even if it already meets size.
DEFAULT_RANDOM_CACHE_REFRESH = True
# Weight multiplier for likes in the materialized popularity score.
DEFAULT_POPULARITY_LIKE_WEIGHT = 2.0
# Force rewrite similarity cache entries on recommendation requests by default.
DEFAULT_SIMILARITY_CACHE_REFRESH = False
# Number of similar videos cached per seed video.
DEFAULT_SIMILAR_PER_LIKE = 1000
# Require full cache entries (exactly limit rows) before using similarity cache.
DEFAULT_SIMILARITY_REQUIRE_FULL_CACHE = False
# Allow ANN fallback when cache misses/partial in cache-optimized source.
DEFAULT_SIMILARITY_ALLOW_ANN_ON_CACHE_MISS = True
# Absolute ANN search limit for similarity queries (0 means use per-request limit).
DEFAULT_SIMILARITY_SEARCH_LIMIT = 5000
# Max similar videos cached per author/channel (0 disables the limit).
DEFAULT_SIMILARITY_MAX_PER_AUTHOR = 1
# Whether to exclude the source video's author from the cache build.
DEFAULT_SIMILARITY_EXCLUDE_SOURCE_AUTHOR = False
# Host and port for the similarity server.
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 7070
# Default data paths used by the Engine server (repo-root relative).
DEFAULT_DB_PATH = "engine/server/db/whitelist.db"
DEFAULT_INDEX_PATH = "engine/server/db/whitelist-video-embeddings.faiss"
DEFAULT_USERS_DB_PATH = "engine/server/db/users.db"
DEFAULT_SIMILARITY_DB_PATH = "engine/server/db/similarity-cache.db"
DEFAULT_RANDOM_CACHE_DB_PATH = "engine/server/db/random-cache.db"

# Include cached dynamic stats (views, likes) in API responses.
INCLUDE_DYNAMIC_STATS = True
# Allow returning debug metadata in recommendation responses when debug=1 is passed.
RECOMMENDATIONS_DEBUG_ENABLED = True
# Hide videos after this many recorded access errors (0 disables the filter).
VIDEO_ERROR_THRESHOLD = 3

# Use client-provided likes JSON as the default source (temporary mode).
DEFAULT_USE_CLIENT_LIKES = True
# Max client likes accepted per request.
DEFAULT_CLIENT_LIKES_MAX = 5
# Max JSON body size for recommendation POST requests (bytes).
DEFAULT_CLIENT_LIKES_BODY_LIMIT = 65536
# Simple in-memory rate limit for API requests (0 disables).
DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60

# Moderation filters for feed/similar output.
DEFAULT_ENABLE_INSTANCE_IGNORE = True
DEFAULT_ENABLE_CHANNEL_BLOCKLIST = True
# Optional future toggle for /api/video hide behavior.
DEFAULT_HIDE_BLOCKED_IN_VIDEO_API = False

# Bridge contract switch for Engine ingest surface.
# bridge: accept /internal/events/ingest from trusted client service.
# activitypub: bridge endpoint remains disabled; AP subscriber path will own writes.
ENGINE_INGEST_MODE = _resolve_mode_env("ENGINE_INGEST_MODE", "bridge")

# Recommendation/similarity log view mode hint.
# verbose: full stream.
# focused: compact operational subset for live viewer scripts.
DEFAULT_RECOMMENDATIONS_LOG_PROFILE = _resolve_log_profile_env(
    "RECOMMENDATIONS_LOG_PROFILE", "verbose"
)
