# Pool size for popular candidates (0 uses per-request limit).
DEFAULT_POPULAR_POOL_SIZE = 5000
# Pool size for fresh candidates (0 uses DEFAULT_SIMILAR_PER_LIKE).
DEFAULT_FRESH_POOL_SIZE = 5000

# Recommendation pipeline configuration and batch sizing.
# Notes:
# - Profiles allow distinct behavior for "home" (no seed) and "upnext" (seed).
# - gather_ratio sets candidate fetch share; mix_ratio sets output mix (with fallback when a layer is short).
# - overfetch_factor inflates per-layer fetch sizes to survive filters/dedup.
# - scoring combines similarity/freshness/popularity (+ layer bonus) into final score.
# - layers (explore/exploit/fresh) are mixed by configured ratios with fallback order.
# - soft_caps are applied after mixing to enforce diversity constraints.

RECOMMENDATION_PIPELINE = {
    "default_profile": "home",
    "profiles": {
        "home": {
            # Total items returned per feed batch.
            "batch_size": 48,

            # Fetch extra per layer to improve fill rate after filtering/dedup.
            # 2 means "fetch ~2x more than needed per layer" to compensate for filters.
            "overfetch_factor": 1,
            "generators": {
                # gather_ratio controls candidate fetch share; mix_ratio controls output share.
                # shuffle applies within the generator pool before scoring.
                # enabled toggles generator participation.
                "random": {
                    "enabled": True,
                    "gather_ratio": 0.1,
                    "mix_ratio": 0.1,
                    "shuffle": True,
                    "below_explore_min": True,
                    "explore_min": 0.2,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "popular": {
                    "enabled": True,
                    "gather_ratio": 0.1,
                    "mix_ratio": 0.1,
                    "shuffle": True,
                    "pool_size": DEFAULT_POPULAR_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "explore": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.2,
                    "shuffle": True,
                    "pool_size": 5000,
                    "similarity_min": 0.2,
                    "similarity_max": 0.4,
                    "requires_likes": True,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "exploit": {
                    "enabled": True,
                    "gather_ratio": 0.5,
                    "mix_ratio": 0.5,
                    "shuffle": True,
                    "pool_size": 2000,
                    "exploit_min": 0.4,
                    "requires_likes": True,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "fresh": {
                    "enabled": True,
                    "gather_ratio": 0.1,
                    "mix_ratio": 0.1,
                    "shuffle": True,
                    "pool_size": DEFAULT_FRESH_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
            },
            # Order for candidate collection and fallback when a layer runs out.
            "mixing": {"order": ["explore", "exploit", "popular", "random", "fresh"]},
            # Scoring configuration for unified ranking.
            "scoring": {
                # Weights for feature aggregation into final score.
                # Higher weight = stronger influence on final order.
                # similarity=1.0 is the baseline; freshness/popularity are smaller nudges.
                "weights": {"similarity": 1.0, "freshness": 0.25, "popularity": 0.2},
                # Per-layer additive bonus to nudge sources up/down.
                # Example: exploit +0.15 shifts high-similarity candidates upward.
                "layer_weights": {
                    "exploit": 0.15,
                    "explore": 0.05,
                    "popular": 0.05,
                    "random": 0.0,
                    "fresh": 0.05,
                },
                # Half-life (days) for freshness decay.
                # 14 => score halves every ~14 days since publish.
                "freshness_half_life_days": 14,
                # Popularity feature weighting (log-normalized internally).
                # likes are weighted more than views in the popularity sub-score.
                "popularity": {"views": 1.0, "likes": 2.0},
            },
            # Optional caps and post-filters.
            # soft_caps.min/max are per-layer constraints applied after ranking.
            # fresh<=12 keeps fresh from dominating (even if scored high).
            "soft_caps": {"max": {"fresh": 12}},
            # post_filters removed: limits are enforced per-layer before mixing.
        },
        "guest_home": {
            "batch_size": 48,
            "overfetch_factor": 2,
            "generators": {
                "random": {
                    "enabled": True,
                    "gather_ratio": 0.6,
                    "mix_ratio": 0.6,
                    "shuffle": True,
                    "below_explore_min": False,
                    "explore_min": 0.2,
                    "max_per_instance": 0,
                    "max_per_author": 2,
                },
                "popular": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.2,
                    "shuffle": True,
                    "pool_size": DEFAULT_POPULAR_POOL_SIZE,
                    "max_per_instance": 0,
                    "max_per_author": 2,
                },
                "fresh": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.2,
                    "shuffle": True,
                    "pool_size": DEFAULT_FRESH_POOL_SIZE,
                    "max_per_instance": 0,
                    "max_per_author": 2,
                },
            },
            "mixing": {"order": ["popular", "random", "fresh"]},
            "scoring": {
                "weights": {"similarity": 0.2, "freshness": 0.35, "popularity": 0.45},
                "layer_weights": {"popular": 0.05, "random": 0.0, "fresh": 0.05},
                "freshness_half_life_days": 14,
                "popularity": {"views": 1.0, "likes": 2.0},
            },
            "soft_caps": {"max": {"fresh": 12}},
        },
        "upnext": {
            # Up Next uses the same layers but different scoring/ratios.
            "scoring": {
                # Bias more toward similarity, less toward freshness/popularity.
                "weights": {"similarity": 1.0, "freshness": 0.1, "popularity": 0.1},
                # Longer half-life => freshness decays slower for upnext.
                "freshness_half_life_days": 30,
                "popularity": {"views": 1.0, "likes": 1.0},
            },
            "generators": {
                "random": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.05,
                    "shuffle": True,
                    "below_explore_min": True,
                    "explore_min": 0.25,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "popular": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.05,
                    "shuffle": True,
                    "pool_size": DEFAULT_POPULAR_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "explore": {
                    "enabled": True,
                    "gather_ratio": 0.1,
                    "mix_ratio": 0.1,
                    "shuffle": True,
                    "pool_size": 1200,
                    "similarity_min": 0.25,
                    "similarity_max": 0.55,
                    "requires_likes": True,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "exploit": {
                    "enabled": True,
                    "gather_ratio": 0.75,
                    "mix_ratio": 0.75,
                    "shuffle": True,
                    "pool_size": 2000,
                    "exploit_min": 0.7,
                    "requires_likes": True,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "fresh": {
                    "enabled": True,
                    "gather_ratio": 0.05,
                    "mix_ratio": 0.05,
                    "shuffle": True,
                    "pool_size": DEFAULT_FRESH_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
            },
            "mixing": {"order": ["explore", "exploit", "popular", "random", "fresh"]},
        },
        "guest_upnext": {
            "scoring": {
                "weights": {"similarity": 1.0, "freshness": 0.1, "popularity": 0.1},
                "freshness_half_life_days": 30,
                "popularity": {"views": 1.0, "likes": 1.0},
            },
            "generators": {
                "random": {
                    "enabled": True,
                    "gather_ratio": 0.4,
                    "mix_ratio": 0.4,
                    "shuffle": True,
                    "below_explore_min": False,
                    "explore_min": 0.25,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "popular": {
                    "enabled": True,
                    "gather_ratio": 0.4,
                    "mix_ratio": 0.4,
                    "shuffle": True,
                    "pool_size": DEFAULT_POPULAR_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
                "fresh": {
                    "enabled": True,
                    "gather_ratio": 0.2,
                    "mix_ratio": 0.2,
                    "shuffle": True,
                    "pool_size": DEFAULT_FRESH_POOL_SIZE,
                    "max_per_instance": 5,
                    "max_per_author": 2,
                },
            },
            "mixing": {"order": ["popular", "random", "fresh"]},
        },
    },
}

# Default number of videos returned per feed batch.
BATCH_SIZE = RECOMMENDATION_PIPELINE["profiles"]["home"]["batch_size"]

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
# Force rewrite similarity cache entries on /api/similar requests by default.
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
# Default data paths used by the server.
DEFAULT_DB_PATH = "server/db/whitelist.db"
DEFAULT_INDEX_PATH = "server/db/whitelist-video-embeddings.faiss"
DEFAULT_USERS_DB_PATH = "server/db/users.db"
DEFAULT_SIMILARITY_DB_PATH = "server/db/similarity-cache.db"
DEFAULT_RANDOM_CACHE_DB_PATH = "server/db/random-cache.db"

# Include cached dynamic stats (views, likes) in API responses.
INCLUDE_DYNAMIC_STATS = True
# Allow returning debug metadata in /api/similar when debug=1 is passed.
RECOMMENDATIONS_DEBUG_ENABLED = True
# Hide videos after this many recorded access errors (0 disables the filter).
VIDEO_ERROR_THRESHOLD = 3

# Use client-provided likes JSON as the default source (temporary mode).
DEFAULT_USE_CLIENT_LIKES = True
# Max client likes accepted per request.
DEFAULT_CLIENT_LIKES_MAX = 5
# Max JSON body size for /api/similar (bytes).
DEFAULT_CLIENT_LIKES_BODY_LIMIT = 65536
# Simple in-memory rate limit for API requests (0 disables).
DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
