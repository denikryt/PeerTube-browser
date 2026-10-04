"""Recommendation and similar-route orchestration for the Engine API.

This module preserves the current recommendation/similar-route behavior while
keeping orchestration in a framework-neutral service. It intentionally keeps the
existing dict-based payloads, response shapes, request-context behavior, and
recommendation pipeline calls because the route split is not a recommendation
redesign.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

import numpy as np
from data.ann import search_index
from data.embeddings import normalize_vector, resolve_seed
from data.metadata import fetch_metadata_by_index_ids
from data.random_videos import fetch_random_rows, fetch_random_rows_from_cache
from data.serving_moderation import apply_serving_moderation_filters
from data.video_filters import VideoFilters, matches_video_filters
from data.similarity_candidates import SimilarityCandidatesPolicy, get_similar_candidates
from data.time import now_ms
from http_utils import resolve_user_id
from recommendations.debug import attach_debug_info
from recommendations.profile import resolve_profile_config_with_guest
from recommendations.related_personalization import rerank_related_videos
from recommendations.scoring import score_and_rank_list
from recommendations.types import RecommendationResult
from request_context import (
    clear_request_context,
    fetch_recent_likes_request,
    set_request_client_likes,
    set_request_id,
)
from route_results import RouteResult
try:
    from engine.server.api.services.video_filter_service import parse_video_filters
except ModuleNotFoundError:  # pragma: no cover - direct server.py execution path
    from services.video_filter_service import parse_video_filters
from server_config import (
    DEFAULT_CLIENT_LIKES_MAX,
    INCLUDE_DYNAMIC_STATS,
    MAX_LIKES,
)

STABLE_VIDEO_FIELDS = (
    "video_id",
    "video_uuid",
    "instance_domain",
    "title",
    "thumbnail_url",
    "thumbnail_urls",
    "thumbnail_candidates",
    "preview_path",
    "channel_avatar_url",
    "channel_name",
    "channel_display_name",
    "channel_url",
    "published_at",
    "duration",
    "language",
    "language_label",
    "category",
    "category_id",
    "video_url",
    "embed_path",
)

if INCLUDE_DYNAMIC_STATS:
    STABLE_VIDEO_FIELDS = STABLE_VIDEO_FIELDS + ("views", "likes", "dislikes")


def stable_video_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project a DB/recommendation row to stable client-facing fields."""
    return {field: row.get(field) for field in STABLE_VIDEO_FIELDS}


def stable_video_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project multiple rows to the stable Engine API row contract."""
    return [stable_video_row(row) for row in rows]


def maybe_attach_debug(
    stable_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    enabled: bool,
) -> list[dict[str, Any]]:
    """Attach existing debug metadata only when the current debug gate allows it."""
    if not enabled:
        return stable_rows
    return attach_debug_info(stable_rows, source_rows)


def _parse_client_likes(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Validate Client likes JSON to Engine ``video_uuid``/``instance_domain`` pairs."""
    raw = payload.get("likes")
    if not isinstance(raw, list):
        return []
    likes: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        uuid = entry.get("uuid")
        host = entry.get("host")
        if not isinstance(uuid, str) or not uuid.strip():
            continue
        if not isinstance(host, str) or not host.strip():
            continue
        likes.append({"video_uuid": uuid.strip(), "instance_domain": host.strip()})
    return likes


def _recommendations_likes_payload_error(
    path: str, payload: dict[str, Any], max_items: int
) -> dict[str, Any] | None:
    """Return the current API error payload for invalid recommendations likes."""
    if path != "/recommendations" or max_items <= 0:
        return None
    raw_likes = payload.get("likes")
    if not isinstance(raw_likes, list):
        return None
    received = len(raw_likes)
    if received <= max_items:
        for index, entry in enumerate(raw_likes):
            if not isinstance(entry, dict):
                return {
                    "error": "Invalid likes payload",
                    "reason": "likes entry must be an object",
                    "index": index,
                }
            uuid = entry.get("uuid")
            if not isinstance(uuid, str) or not uuid.strip():
                return {
                    "error": "Invalid likes payload",
                    "reason": "likes.uuid must be a non-empty string",
                    "index": index,
                }
            host = entry.get("host")
            if not isinstance(host, str) or not host.strip():
                return {
                    "error": "Invalid likes payload",
                    "reason": "likes.host must be a non-empty string",
                    "index": index,
                }
        return None
    return {
        "error": "Too many likes in request body",
        "code": "too_many_likes",
        "max_likes": max_items,
        "max_allowed": max_items,
        "received": received,
    }


def _resolve_client_likes(server: Any, likes: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Resolve Client likes through the current Engine videos table identity query."""
    if not likes:
        return []
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in likes:
        key = f"{entry['video_uuid']}::{entry['instance_domain']}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)

    # Availability applies to every identity before it enters request-local likes.
    conditions = " OR ".join(["(video_uuid = ? AND instance_domain = ?)"] * len(unique))
    params: list[Any] = []
    for entry in unique:
        params.append(entry["video_uuid"])
        params.append(entry["instance_domain"])
    with server.db_lock:
        rows = server.db.execute(
            f"""
            SELECT video_id, video_uuid, instance_domain
            FROM videos
            WHERE invalid_reason IS NULL AND ({conditions})
            """,
            params,
        ).fetchall()
    lookup = {f"{row['video_uuid']}::{row['instance_domain']}": row["video_id"] for row in rows}
    resolved: list[dict[str, Any]] = []
    for entry in unique:
        key = f"{entry['video_uuid']}::{entry['instance_domain']}"
        video_id = lookup.get(key)
        if not video_id:
            continue
        resolved.append(
            {
                "video_id": str(video_id),
                "video_uuid": entry["video_uuid"],
                "instance_domain": entry["instance_domain"],
            }
        )
    return resolved


def _parse_int(value: str | None) -> int:
    """Parse a positive integer using the existing Engine API fallback semantics."""
    try:
        parsed = int(value or "0")
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _parse_bool(value: str | None) -> bool:
    """Parse current boolean-like query parameter values."""
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_non_negative_int(value: str | None) -> int | None:
    """Parse a non-negative integer; return ``None`` on missing or invalid input."""
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _make_request_id() -> str:
    """Generate the same short random request id used by the legacy handler."""
    return hex(np.random.randint(0, 0xFFFFFF))[2:].zfill(6)


def _extract_video_id_from_similar_path(path: str) -> str | None:
    """Resolve ``/videos/{id}/similar`` route shape to the seed video id."""
    if not path.startswith("/videos/") or not path.endswith("/similar"):
        return None
    parts = path.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "videos" or parts[2] != "similar":
        return None
    video_id = parts[1].strip()
    return video_id or None


def fetch_random_rows_from_server(server: Any, limit: int) -> list[dict[str, Any]]:
    """Fetch random rows through the current cache-first fallback contract."""
    rows = fetch_random_rows_from_cache(server, limit, error_threshold=server.video_error_threshold)
    if rows:
        return rows
    with server.db_lock:
        return fetch_random_rows(
            server.db,
            limit,
            error_threshold=server.video_error_threshold,
        )


def build_rows_response(
    server: Any,
    rows: list[dict[str, Any]],
    include_debug: bool,
    request_id: str,
    started_at: datetime,
    seed_payload: dict[str, Any],
    filters: VideoFilters | None = None,
) -> RouteResult:
    """Build the current Engine recommendation rows response shape."""
    if filters is not None:
        # TEMP-DISCOVERY-RECOMMENDATIONS: final-filter the finite legacy recommendation batch here; remove when recommendations have a native filtered paged/snapshot provider that can refill beyond the legacy batch.
        rows = [row for row in rows if matches_video_filters(row, filters)]
    filtered_rows, _ = apply_serving_moderation_filters(server, rows, request_id=request_id)

    stable_rows = stable_video_rows(filtered_rows)
    stable_rows = maybe_attach_debug(stable_rows, filtered_rows, include_debug)
    duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
    logging.info(
        "[similar-server][%s] done count=%d duration_ms=%d",
        request_id,
        len(stable_rows),
        duration_ms,
    )
    # RecommendationResult is an internal adapter boundary only; the explicit
    # total preserves the existing route contract where total reports the loaded
    # embedding count instead of the number of returned rows.
    result = RecommendationResult(
        rows=tuple(stable_rows),
        seed=seed_payload,
        generated_at=int(datetime.now(timezone.utc).timestamp() * 1000),
        total=server.embeddings_count,
    )
    return RouteResult(200, result.to_response())


def handle_random(
    server: Any,
    limit: int,
    include_debug: bool,
    request_id: str,
    started_at: datetime,
) -> RouteResult:
    """Handle explicit random-feed requests with the current response contract."""
    rows = fetch_random_rows_from_server(server, limit)
    return build_rows_response(
        server,
        rows,
        include_debug,
        request_id,
        started_at,
        seed_payload={"random": True},
    )


def handle_home(
    server: Any,
    user_id: str,
    limit: int,
    refresh_cache: bool,
    include_debug: bool,
    request_id: str,
    started_at: datetime,
    mode: str,
    filters: VideoFilters | None = None,
) -> RouteResult:
    """Handle home recommendations and current random fallback behavior."""
    rows = server.recommendation_strategy.generate_recommendations(
        server, user_id, limit, refresh_cache, mode=mode
    )
    if not rows:
        rows = fetch_random_rows_from_server(server, limit)
        return build_rows_response(
            server,
            rows,
            include_debug,
            request_id,
            started_at,
            seed_payload={"user_id": user_id, "random": True, "mode": mode},
            filters=filters,
        )
    return build_rows_response(
        server,
        rows,
        include_debug,
        request_id,
        started_at,
        seed_payload={"user_id": user_id, "mode": mode},
        filters=filters,
    )


def handle_seed_with_embedding(
    server: Any,
    seed: dict[str, Any],
    user_id: str,
    limit: int,
    refresh_cache: bool,
    include_debug: bool,
    request_id: str,
    started_at: datetime,
    mode: str,
) -> RouteResult:
    """Handle up-next recommendations when a seed embedding is available."""
    recent_likes = fetch_recent_likes_request(user_id, MAX_LIKES)
    likes_available = bool(recent_likes)
    profile_name, profile_config = resolve_profile_config_with_guest(
        server.recommendation_strategy.config, mode, likes_available
    )
    logging.info(
        "[recommendations] profile=%s likes=%s",
        profile_name,
        "yes" if likes_available else "no",
    )
    policy = SimilarityCandidatesPolicy(
        refresh_cache=refresh_cache,
        use_cache=True,
        require_full_cache=bool(getattr(server, "similarity_require_full_cache", True)),
    )
    settings = getattr(server.recommendation_strategy, "settings", None)
    similar_per_like = int(getattr(settings, "similar_per_like", 0) or 0)
    related_start = perf_counter()
    rows = get_similar_candidates(server, seed, similar_per_like, policy)
    related_ms = int((perf_counter() - related_start) * 1000)
    if rows:
        score_start = perf_counter()
        rows = score_and_rank_list(rows, profile_config, layer_name=mode, now_ms_value=now_ms())
        score_ms = int((perf_counter() - score_start) * 1000)
        for row in rows:
            row["debug_profile"] = profile_name
        logging.info(
            "[similar-server][%s] related_entries=%d limit=%d",
            request_id,
            len(rows),
            limit,
        )
        logging.info(
            "[similar-server][%s] timing related=%dms score=%dms total=%dms",
            request_id,
            related_ms,
            score_ms,
            related_ms + score_ms,
        )
        rows = rows[:limit]
        if (
            server.related_personalization_enabled
            and server.related_personalization_deps is not None
        ):
            personalize_start = perf_counter()
            rows = rerank_related_videos(
                server,
                user_id,
                rows,
                server.related_personalization_deps,
            )
            personalize_ms = int((perf_counter() - personalize_start) * 1000)
            logging.info(
                "[similar-server][%s] timing personalize=%dms",
                request_id,
                personalize_ms,
            )
        seed_payload = dict(seed.get("meta") or {})
        seed_payload["mode"] = mode
        return build_rows_response(
            server, rows, include_debug, request_id, started_at, seed_payload
        )
    return RouteResult(
        200,
        {
            "generatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
            "total": server.embeddings_count,
            "count": 0,
            "seed": seed.get("meta"),
            "rows": [],
        },
    )


def handle_vector_search(
    server: Any,
    seed: dict[str, Any],
    limit: int,
    include_debug: bool,
    request_id: str,
    started_at: datetime,
) -> RouteResult:
    """Handle the legacy raw-vector ANN search path."""
    if seed["vector"] is None:
        return RouteResult(
            400,
            {
                "error": "Missing vector or video reference",
                "hint": "Provide ?id=...&host=... or ensure a user profile exists",
            },
        )
    vector = seed["vector"]
    if server.normalize_queries:
        vector = normalize_vector(vector)

    search_start = perf_counter()
    with server.index_lock:
        index_ids, scores = search_index(server.index, vector, limit, seed["exclude_index_id"])
    search_ms = int((perf_counter() - search_start) * 1000)

    meta_start = perf_counter()
    with server.db_lock:
        metadata = fetch_metadata_by_index_ids(
            server.db,
            index_ids,
            error_threshold=server.video_error_threshold,
        )
    meta_ms = int((perf_counter() - meta_start) * 1000)
    logging.info(
        "[similar-server][%s] timing ann=%dms meta=%dms total=%dms",
        request_id,
        search_ms,
        meta_ms,
        search_ms + meta_ms,
    )
    rows = []
    for index_id, score in zip(index_ids, scores, strict=True):
        meta = metadata.get(index_id)
        if not meta:
            continue
        rows.append({**meta, "score": score})
    return build_rows_response(
        server,
        rows,
        include_debug,
        request_id,
        started_at,
        seed_payload=seed["meta"],
    )


def handle_similar(server: Any, params: dict[str, list[str]], *, home_filters: VideoFilters | None = None) -> RouteResult:
    """Execute the current home, seed, vector, or random recommendation path."""
    limit = _parse_int(params.get("limit", [str(server.default_limit)])[0])
    if limit == 0:
        limit = server.default_limit
    if server.default_limit > 0 and limit > server.default_limit:
        limit = server.default_limit
    vector_param = params.get("vector", [None])[0]
    id_param = params.get("id", params.get("video_id", [None]))[0]
    host_param = params.get("host", params.get("instance_domain", [None]))[0]
    uuid_param = params.get("uuid", params.get("video_uuid", [None]))[0]
    user_id = resolve_user_id(params.get("user_id", params.get("userId", [None]))[0])
    random_param = params.get("random", [None])[0]
    refresh_cache = (
        _parse_bool(params.get("refresh_cache", [None])[0]) or server.refresh_similarity_cache
    )
    debug_requested = _parse_bool(params.get("debug", [None])[0])
    debug_enabled = bool(getattr(server, "recommendations_debug_enabled", False))
    if debug_requested and not debug_enabled:
        return RouteResult(403, {"error": "Debug mode is disabled"})
    include_debug = debug_requested and bool(
        getattr(server, "recommendations_debug_enabled", False)
    )

    request_id = _make_request_id()
    started_at = datetime.now(timezone.utc)
    logging.info(
        "[similar-server][%s] start limit=%s id=%s host=%s uuid=%s",
        request_id,
        limit,
        id_param or "",
        host_param or "",
        uuid_param or "",
    )
    set_request_id(request_id)

    try:
        if random_param and random_param != "0":
            return handle_random(server, limit, include_debug, request_id, started_at)
        seed_start = perf_counter()
        with server.db_lock:
            seed = (
                resolve_seed(
                    server.db,
                    server.embeddings_dim,
                    vector_param,
                    id_param,
                    host_param,
                    uuid_param,
                )
                if (vector_param or id_param or uuid_param)
                else None
            )
        seed_ms = int((perf_counter() - seed_start) * 1000)
        logging.info("[similar-server][%s] timing resolve_seed=%dms", request_id, seed_ms)

        mode = "home" if seed is None else "upnext"

        if seed is None:
            return handle_home(
                server,
                user_id,
                limit,
                refresh_cache,
                include_debug,
                request_id,
                started_at,
                mode,
                filters=home_filters,
            )

        if seed.get("meta") and seed.get("embedding") is not None:
            return handle_seed_with_embedding(
                server,
                seed,
                user_id,
                limit,
                refresh_cache,
                include_debug,
                request_id,
                started_at,
                mode,
            )

        if seed.get("random"):
            rows = fetch_random_rows_from_server(server, limit)
            return build_rows_response(
                server,
                rows,
                include_debug,
                request_id,
                started_at,
                seed_payload=seed["meta"],
            )

        return handle_vector_search(server, seed, limit, include_debug, request_id, started_at)
    except ValueError as exc:
        bad_request = {
            "Invalid vector parameter",
            "Vector dimension does not match embeddings",
            "Vector norm is zero",
        }
        status = 400 if str(exc) in bad_request else 500
        return RouteResult(status, {"error": str(exc)})
    except Exception as exc:  # pragma: no cover
        logging.exception("server error")
        return RouteResult(500, {"error": str(exc)})
    finally:
        clear_request_context()


def handle_similar_request(
    server: Any,
    path: str,
    method: str,
    params: dict[str, list[str]],
    body: dict[str, Any] | None = None,
) -> RouteResult:
    """Parse POST body Client likes and dispatch to the existing similar behavior."""
    client_likes: list[dict[str, Any]] = []
    use_client_likes = bool(getattr(server, "use_client_likes", False))
    if method == "POST":
        body = body or {}
        likes_payload_error = _recommendations_likes_payload_error(
            path, body, DEFAULT_CLIENT_LIKES_MAX
        )
        if likes_payload_error is not None:
            return RouteResult(400, likes_payload_error)
        incoming_payload = {
            "likes": body.get("likes", []),
            "user_id": body.get("user_id"),
            "mode": body.get("mode"),
        }
        logging.info(
            "[recommendations] incoming likes body=%s",
            json.dumps(incoming_payload, ensure_ascii=True, separators=(",", ":")),
        )
        parsed = _parse_client_likes(body)
        client_likes = _resolve_client_likes(server, parsed)
    set_request_client_likes(client_likes, use_client_likes)

    try:
        filter_selected = path == "/recommendations" and any(key in params for key in ("language", "category", "tag", "instance"))
        if not filter_selected:
            return handle_similar(server, params)
        try:
            home_filters = parse_video_filters(params)
        except ValueError as exc:
            return RouteResult(400, {"error": str(exc)})
        return handle_similar(server, params, home_filters=home_filters)
    finally:
        clear_request_context()
