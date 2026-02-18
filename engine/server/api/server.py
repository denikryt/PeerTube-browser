#!/usr/bin/env python3
"""Similarity server API for embeddings and recommendations.

This module wires together data access, ANN search, cache-backed similarity
candidate generation, and recommendation mixing into HTTP handlers.
"""
import logging
import argparse
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parent
if str(server_dir) not in sys.path:
    # Allow imports from engine/server when running this module directly.
    sys.path.insert(0, str(server_dir))

from server_config import (
    BATCH_SIZE,
    DEFAULT_NPROBE,
    DEFAULT_NORMALIZE_QUERIES,
    DEFAULT_RANDOM_CACHE_SIZE,
    DEFAULT_RANDOM_CACHE_FILTERED_MODE,
    DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR,
    DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE,
    DEFAULT_RANDOM_CACHE_REFRESH,
    DEFAULT_FRESH_POOL_SIZE,
    DEFAULT_POPULARITY_LIKE_WEIGHT,
    DEFAULT_SIMILAR_PER_LIKE,
    DEFAULT_SIMILARITY_CACHE_REFRESH,
    DEFAULT_SIMILARITY_EXCLUDE_SOURCE_AUTHOR,
    DEFAULT_SIMILARITY_MAX_PER_AUTHOR,
    DEFAULT_SIMILARITY_ALLOW_ANN_ON_CACHE_MISS,
    DEFAULT_SIMILARITY_REQUIRE_FULL_CACHE,
    DEFAULT_SIMILARITY_SEARCH_LIMIT,
    DEFAULT_USE_SIMILARITY_CACHE,
    DEFAULT_DB_PATH,
    DEFAULT_INDEX_PATH,
    DEFAULT_RANDOM_CACHE_DB_PATH,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    DEFAULT_SIMILARITY_DB_PATH,
    MAX_LIKES,
    MAX_LIKES_FOR_RECS,
    RECOMMENDATIONS_DEBUG_ENABLED,
    RECOMMENDATION_PIPELINE,
    RELATED_VIDEOS_PERSONALIZATION,
    VIDEO_ERROR_THRESHOLD,
    DEFAULT_USE_CLIENT_LIKES,
    DEFAULT_RATE_LIMIT_MAX_REQUESTS,
    DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    DEFAULT_ENABLE_INSTANCE_IGNORE,
    DEFAULT_ENABLE_CHANNEL_BLOCKLIST,
    ENGINE_INGEST_MODE,
    DEFAULT_RECOMMENDATIONS_LOG_PROFILE,
)
from logging_profiles import configure_engine_logging
from data.db import connect_db, connect_similarity_db
from data.embeddings import (
    fetch_embeddings_by_ids,
    fetch_seed_embedding,
    fetch_seed_embeddings_for_likes,
)
from data.random_videos import (
    fetch_random_rows,
    fetch_random_rows_from_cache,
    fetch_recent_videos,
    fetch_popular_videos,
)
from data.similarity_candidates import get_similar_candidates
from data.similarity_cache import ensure_similarity_schema
from data.interaction_events import ensure_interaction_event_schema
from data.random_cache import connect_random_cache_db, populate_random_cache
from data.channels import ensure_channels_indexes
from data.videos import ensure_video_indexes
from data.moderation import ensure_moderation_schema
from recommendations import RecommendationStrategy
from recommendations.keys import like_key
from recommendations.builder import (
    RecommendationBuilderDeps,
    RecommendationBuilderSettings,
    build_recommendation_strategy,
)
from recommendations.related_personalization import (
    RelatedPersonalizationDeps,
)
from handlers.similar import SimilarHandler
from http_utils import RateLimiter
from request_context import fetch_recent_likes_request
from scripts.cli_format import CompactHelpFormatter
try:
    import faiss  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "faiss is required. Install faiss-cpu in your Python environment."
    ) from exc


SIMILAR_PER_LIKE = DEFAULT_SIMILAR_PER_LIKE
SIMILARITY_SEARCH_LIMIT = DEFAULT_SIMILARITY_SEARCH_LIMIT
SIMILARITY_MAX_PER_AUTHOR = DEFAULT_SIMILARITY_MAX_PER_AUTHOR
SIMILARITY_EXCLUDE_SOURCE_AUTHOR = DEFAULT_SIMILARITY_EXCLUDE_SOURCE_AUTHOR
DEV_SERVER_PORT = 7071


def _parse_port(value: str) -> int:
    """Handle parse port."""
    port = int(value)
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError("port must be in range 1..65535")
    return port


def parse_args() -> argparse.Namespace:
    """Handle parse args."""
    parser = argparse.ArgumentParser(
        description="Run PeerTube Browser API server.",
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help=(
            "Enable dev defaults: bind port 7071 and disable random cache refresh "
            "(unless explicitly overridden)."
        ),
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_SERVER_HOST,
        help="Server host/interface to bind.",
    )
    parser.add_argument(
        "--port",
        type=_parse_port,
        default=None,
        help=(
            "Server TCP port to bind. "
            f"Defaults to {DEFAULT_SERVER_PORT} (or {DEV_SERVER_PORT} with --dev)."
        ),
    )
    refresh_group = parser.add_mutually_exclusive_group()
    refresh_group.add_argument(
        "--random-cache-refresh",
        dest="random_cache_refresh",
        action="store_true",
        help="Force random cache refresh on startup.",
    )
    refresh_group.add_argument(
        "--no-random-cache-refresh",
        dest="random_cache_refresh",
        action="store_false",
        help="Disable random cache refresh on startup.",
    )
    parser.set_defaults(random_cache_refresh=None)
    return parser.parse_args()


def set_nprobe(index: faiss.Index, nprobe: int) -> None:
    """Set FAISS nprobe on a supported index."""
    ivf_index = None
    if hasattr(faiss, "extract_index_ivf"):
        try:
            ivf_index = faiss.extract_index_ivf(index)
        except Exception:  # pragma: no cover
            ivf_index = None
    if ivf_index is not None:
        ivf_index.nprobe = nprobe
    if hasattr(index, "nprobe"):
        index.nprobe = nprobe
    elif hasattr(index, "index") and hasattr(index.index, "nprobe"):
        index.index.nprobe = nprobe
    logging.info(
        "[similar-server] ann_nprobe_configured=%d index_type=%s ivf_type=%s",
        nprobe,
        type(index).__name__,
        type(ivf_index).__name__ if ivf_index is not None else None,
    )


class SimilarServer(ThreadingHTTPServer):
    """Threaded HTTP server with shared DB and index handles."""
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        db: sqlite3.Connection,
        similarity_db: sqlite3.Connection | None,
        random_cache_db: sqlite3.Connection | None,
        index: faiss.Index,
        embeddings_dim: int,
        embeddings_count: int,
        default_limit: int,
        normalize_queries: bool,
        refresh_similarity_cache: bool,
        similarity_require_full_cache: bool,
        similarity_allow_ann_on_cache_miss: bool,
        similarity_search_limit: int,
        similarity_max_per_author: int,
        similarity_exclude_source_author: bool,
        recommendation_strategy: RecommendationStrategy,
        related_personalization_deps: RelatedPersonalizationDeps | None,
        related_personalization_enabled: bool,
        video_error_threshold: int,
        recommendations_debug_enabled: bool,
        use_client_likes: bool,
        rate_limiter: RateLimiter | None,
        popularity_like_weight: float,
        enable_instance_ignore: bool,
        enable_channel_blocklist: bool,
        engine_ingest_mode: str,
    ) -> None:
        """Initialize the instance."""
        super().__init__(server_address, handler_class)
        self.db = db
        self.index = index
        self.embeddings_dim = embeddings_dim
        self.embeddings_count = embeddings_count
        self.default_limit = default_limit
        self.normalize_queries = normalize_queries
        self.similarity_db = similarity_db
        self.random_cache_db = random_cache_db
        self.refresh_similarity_cache = refresh_similarity_cache
        self.similarity_require_full_cache = similarity_require_full_cache
        self.similarity_allow_ann_on_cache_miss = similarity_allow_ann_on_cache_miss
        self.similarity_search_limit = similarity_search_limit
        self.similarity_max_per_author = similarity_max_per_author
        self.similarity_exclude_source_author = similarity_exclude_source_author
        self.recommendation_strategy = recommendation_strategy
        self.related_personalization_deps = related_personalization_deps
        self.related_personalization_enabled = related_personalization_enabled
        self.video_error_threshold = video_error_threshold
        self.recommendations_debug_enabled = recommendations_debug_enabled
        self.use_client_likes = use_client_likes
        self.rate_limiter = rate_limiter
        self.popularity_like_weight = popularity_like_weight
        self.enable_instance_ignore = enable_instance_ignore
        self.enable_channel_blocklist = enable_channel_blocklist
        self.engine_ingest_mode = engine_ingest_mode
        self.index_lock = threading.Lock()
        self.db_lock = threading.Lock()
        self.similarity_db_lock = threading.Lock()
        self.random_cache_lock = threading.Lock()


def main() -> None:
    """Run the similarity server."""
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    host = args.host
    default_port = DEV_SERVER_PORT if args.dev else DEFAULT_SERVER_PORT
    port = args.port if args.port is not None else default_port
    if args.random_cache_refresh is None:
        random_cache_refresh = False if args.dev else DEFAULT_RANDOM_CACHE_REFRESH
    else:
        random_cache_refresh = bool(args.random_cache_refresh)

    active_log_profile = configure_engine_logging(DEFAULT_RECOMMENDATIONS_LOG_PROFILE)

    repo_root = script_dir.parents[2]
    db_path = (repo_root / DEFAULT_DB_PATH).resolve()
    index_path = (repo_root / DEFAULT_INDEX_PATH).resolve()
    similarity_db_path = (repo_root / DEFAULT_SIMILARITY_DB_PATH).resolve()
    random_cache_path = (repo_root / DEFAULT_RANDOM_CACHE_DB_PATH).resolve()

    db = connect_db(db_path)
    ensure_moderation_schema(db)
    ensure_interaction_event_schema(db)
    ensure_channels_indexes(db)
    ensure_video_indexes(db)
    similarity_db = connect_similarity_db(similarity_db_path)
    ensure_similarity_schema(similarity_db)
    random_cache_path.parent.mkdir(parents=True, exist_ok=True)
    random_cache_db = connect_random_cache_db(random_cache_path)
    populate_random_cache(
        db,
        random_cache_db,
        DEFAULT_RANDOM_CACHE_SIZE,
        random_cache_refresh,
        DEFAULT_RANDOM_CACHE_FILTERED_MODE,
        DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE,
        DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR,
    )
    embeddings_dim = db.execute("SELECT embedding_dim FROM video_embeddings LIMIT 1").fetchone()
    if not embeddings_dim:
        raise RuntimeError("No embeddings found in database.")
    dim_value = int(embeddings_dim[0])

    logging.info("loading FAISS index=%s", index_path)
    index = faiss.read_index(str(index_path), faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY)
    set_nprobe(index, DEFAULT_NPROBE)

    if index.d != dim_value:
        raise RuntimeError(
            f"Index dimension {index.d} does not match database dimension {dim_value}"
        )
    embeddings_count = int(index.ntotal)
    recommendation_deps = RecommendationBuilderDeps(
        fetch_recent_likes=fetch_recent_likes_request,
        fetch_seed_embedding=fetch_seed_embedding,
        fetch_seed_embeddings_for_likes=fetch_seed_embeddings_for_likes,
        get_similar_candidates=get_similar_candidates,
        like_key=like_key,
        fetch_embeddings_by_ids=fetch_embeddings_by_ids,
        fetch_random_rows=fetch_random_rows,
        fetch_random_rows_from_cache=fetch_random_rows_from_cache,
        fetch_recent_videos=fetch_recent_videos,
        fetch_popular_videos=fetch_popular_videos,
    )
    recommendation_settings = RecommendationBuilderSettings(
        max_likes=MAX_LIKES,
        max_likes_for_recs=MAX_LIKES_FOR_RECS,
        similar_per_like=SIMILAR_PER_LIKE,
        default_similar_from_likes_source=DEFAULT_USE_SIMILARITY_CACHE,
        video_error_threshold=VIDEO_ERROR_THRESHOLD,
        fresh_pool_size=DEFAULT_FRESH_POOL_SIZE,
    )
    recommendation_strategy = build_recommendation_strategy(
        RECOMMENDATION_PIPELINE, recommendation_deps, recommendation_settings
    )
    recommendation_strategy.settings = recommendation_settings
    personalization_config = RELATED_VIDEOS_PERSONALIZATION
    related_personalization_deps = None
    if personalization_config.get("enabled"):
        related_personalization_deps = RelatedPersonalizationDeps(
            fetch_recent_likes=fetch_recent_likes_request,
            fetch_embeddings_by_ids=fetch_embeddings_by_ids,
            max_likes=int(personalization_config.get("max_likes", MAX_LIKES)),
            alpha=float(personalization_config.get("alpha", 0.0)),
            beta=float(personalization_config.get("beta", 0.0)),
        )

    rate_limiter = RateLimiter(
        DEFAULT_RATE_LIMIT_MAX_REQUESTS, DEFAULT_RATE_LIMIT_WINDOW_SECONDS
    )
    server = SimilarServer(
        (host, port),
        SimilarHandler,
        db,
        similarity_db,
        random_cache_db,
        index,
        dim_value,
        embeddings_count,
        BATCH_SIZE,
        DEFAULT_NORMALIZE_QUERIES,
        DEFAULT_SIMILARITY_CACHE_REFRESH,
        DEFAULT_SIMILARITY_REQUIRE_FULL_CACHE,
        DEFAULT_SIMILARITY_ALLOW_ANN_ON_CACHE_MISS,
        SIMILARITY_SEARCH_LIMIT,
        SIMILARITY_MAX_PER_AUTHOR,
        SIMILARITY_EXCLUDE_SOURCE_AUTHOR,
        recommendation_strategy,
        related_personalization_deps,
        bool(personalization_config.get("enabled")),
        VIDEO_ERROR_THRESHOLD,
        RECOMMENDATIONS_DEBUG_ENABLED,
        DEFAULT_USE_CLIENT_LIKES,
        rate_limiter,
        DEFAULT_POPULARITY_LIKE_WEIGHT,
        DEFAULT_ENABLE_INSTANCE_IGNORE,
        DEFAULT_ENABLE_CHANNEL_BLOCKLIST,
        ENGINE_INGEST_MODE,
    )

    logging.info("[similar-server] listening on http://%s:%d", host, port)
    logging.info("[similar-server] log_mode_hint=%s", active_log_profile)
    logging.info(
        "[similar-server] mode=%s random_cache_refresh=%s",
        "dev" if args.dev else "default",
        "true" if random_cache_refresh else "false",
    )
    logging.info("[similar-server] ingest_mode=%s", ENGINE_INGEST_MODE)
    logging.info("[similar-server] db=%s index=%s total=%d", db_path, index_path, embeddings_count)
    logging.info("[similar-server] strategy=%s", recommendation_strategy.name)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("shutting down")
    finally:
        server.server_close()
        db.close()
        if similarity_db is not None:
            similarity_db.close()
        if random_cache_db is not None:
            random_cache_db.close()


if __name__ == "__main__":
    main()
