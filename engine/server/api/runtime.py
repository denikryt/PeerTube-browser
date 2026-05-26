"""Runtime state for the FastAPI Engine API adapter.

The state mirrors the attributes that the stdlib ``SimilarServer`` exposed to
route modules. Keeping the attribute names stable lets Stage 10 change the HTTP
framework without changing Engine route, service, recommendation, or data code.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from http_utils import RateLimiter


@dataclass
class EngineRuntimeState:
    """Shared Engine runtime dependencies used by FastAPI route adapters."""

    db: Any
    similarity_db: Any
    random_cache_db: Any
    index: Any
    embeddings_dim: int
    embeddings_count: int
    default_limit: int
    normalize_queries: bool
    refresh_similarity_cache: bool
    similarity_require_full_cache: bool
    similarity_allow_ann_on_cache_miss: bool
    similarity_search_limit: int
    similarity_max_per_author: int
    similarity_exclude_source_author: bool
    recommendation_strategy: Any
    related_personalization_deps: Any
    related_personalization_enabled: bool
    video_error_threshold: int
    recommendations_debug_enabled: bool
    use_client_likes: bool
    rate_limiter: RateLimiter | None
    popularity_like_weight: float
    enable_instance_ignore: bool
    enable_channel_blocklist: bool
    engine_ingest_mode: str
    index_lock: threading.Lock = field(default_factory=threading.Lock)
    db_lock: threading.Lock = field(default_factory=threading.Lock)
    similarity_db_lock: threading.Lock = field(default_factory=threading.Lock)
    random_cache_lock: threading.Lock = field(default_factory=threading.Lock)
