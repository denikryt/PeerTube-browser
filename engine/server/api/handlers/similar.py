"""Similarity HTTP handler for Engine read surface.

Routes:
- /recommendations (POST): recommendation feed and debug payloads.
- /videos/{id}/similar (GET): id-based similar alias.
- /videos/similar (POST): extended similar route.
- /api/health: health check.
- /api/channels: channels listing.
- /api/video: single video metadata.
- /internal/videos/resolve: internal Client read lookup by video_id/uuid(+host).
- /internal/videos/metadata: internal Client metadata batch lookup.
- /internal/events/ingest: internal bridge ingest for normalized events.

Key steps:
- Parse seed/params, resolve likes (client JSON or users DB).
- Build candidate pools, score, mix, and return stable rows.
"""
import logging
import json
from time import perf_counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

import numpy as np

from data.ann import search_index
from data.channels import fetch_channels
from data.embeddings import normalize_vector, resolve_seed
from data.metadata import fetch_metadata
from data.random_videos import fetch_random_rows, fetch_random_rows_from_cache
from data.serving_moderation import apply_serving_moderation_filters
from data.similarity_candidates import SimilarityCandidatesPolicy, get_similar_candidates
from data.time import now_ms
from recommendations.debug import attach_debug_info
from recommendations.profile import resolve_profile_config_with_guest
from recommendations.related_personalization import rerank_related_videos
from recommendations.scoring import score_and_rank_list
from server_config import (
    DEFAULT_CLIENT_LIKES_BODY_LIMIT,
    DEFAULT_CLIENT_LIKES_MAX,
    INCLUDE_DYNAMIC_STATS,
    MAX_LIKES,
)
from http_utils import read_json_body, respond_json, respond_options, resolve_user_id
from request_context import (
    clear_request_context,
    fetch_recent_likes_request,
    set_request_client_likes,
    set_request_id,
)
from handlers.internal_events import handle_internal_events_ingest
from handlers.internal_client_reads import (
    handle_internal_video_resolve,
    handle_internal_videos_metadata,
)
from handlers.video import handle_video_request


SIMILAR_POST_ROUTES = {"/recommendations", "/videos/similar"}


STABLE_VIDEO_FIELDS = (
    "video_id",
    "video_uuid",
    "instance_domain",
    "title",
    "thumbnail_url",
    "preview_path",
    "channel_avatar_url",
    "channel_name",
    "channel_display_name",
    "channel_url",
    "published_at",
    "duration",
    "video_url",
    "embed_path",
)

if INCLUDE_DYNAMIC_STATS:
    STABLE_VIDEO_FIELDS = STABLE_VIDEO_FIELDS + ("views", "likes", "dislikes")


def stable_video_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project a row to stable fields returned to clients."""
    return {field: row.get(field) for field in STABLE_VIDEO_FIELDS}


def stable_video_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project a list of rows to stable response fields."""
    return [stable_video_row(row) for row in rows]


def maybe_attach_debug(
    stable_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    enabled: bool,
) -> list[dict[str, Any]]:
    """Attach debug info when enabled."""
    if not enabled:
        return stable_rows
    return attach_debug_info(stable_rows, source_rows)


def _parse_client_likes(payload: dict[str, Any], max_items: int) -> list[dict[str, str]]:
    """Validate client likes JSON to uuid/host pairs."""
    raw = payload.get("likes")
    if not isinstance(raw, list):
        return []
    likes: list[dict[str, str]] = []
    for entry in raw[: max_items if max_items > 0 else None]:
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


def _resolve_client_likes(server: Any, likes: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Resolve client likes (uuid/host) to internal video_id rows."""
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
            WHERE {conditions}
            """,
            params,
        ).fetchall()
    lookup = {
        f"{row['video_uuid']}::{row['instance_domain']}": row["video_id"]
        for row in rows
    }
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


class SimilarHandler(BaseHTTPRequestHandler):
    """HTTP handler for Engine read endpoints and bridge ingest."""

    def _get_client_ip(self) -> str:
        """Resolve client IP behind reverse proxy headers when available."""
        forwarded_for = self.headers.get("X-Forwarded-For", "").strip()
        if forwarded_for:
            first = forwarded_for.split(",", 1)[0].strip()
            if first:
                return first
        real_ip = self.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
        if self.client_address:
            return self.client_address[0]
        return "unknown"

    def _get_full_url(self) -> str:
        """Build absolute URL from forwarded headers and request path."""
        host = self.headers.get("Host", "").strip()
        if not host:
            return self.path
        proto = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip() or "http"
        return f"{proto}://{host}{self.path}"

    def log_message(self, format: str, *args: Any) -> None:
        """Emit structured access logs with real client IP and full URL."""
        status = args[1] if len(args) > 1 else "-"
        size = args[2] if len(args) > 2 else "-"
        logging.info(
            "[access] ip=%s method=%s url=%s status=%s bytes=%s",
            self._get_client_ip(),
            self.command or "-",
            self._get_full_url(),
            status,
            size,
        )

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight."""
        respond_options(self)

    def do_POST(self) -> None:  # noqa: N802
        """Handle similarity and internal bridge ingest endpoints."""
        url = urlparse(self.path)
        if url.path in SIMILAR_POST_ROUTES:
            self._handle_similar_request(method="POST")
            return
        if url.path == "/internal/videos/resolve":
            handle_internal_video_resolve(self, self.server)
            return
        if url.path == "/internal/videos/metadata":
            handle_internal_videos_metadata(self, self.server)
            return
        if url.path == "/internal/events/ingest":
            if getattr(self.server, "engine_ingest_mode", "bridge") != "bridge":
                respond_json(
                    self,
                    501,
                    {
                        "error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE",
                        "mode": getattr(self.server, "engine_ingest_mode", "bridge"),
                    },
                )
                return
            handle_internal_events_ingest(self, self.server)
            return
        respond_json(self, 404, {"error": "Not found"})

    def do_GET(self) -> None:  # noqa: N802
        """Handle health, profile, and similarity endpoints."""
        url = urlparse(self.path)
        if url.path.startswith("/api/") and not self._rate_limit_check(url.path):
            respond_json(self, 429, {"error": "Rate limit exceeded"})
            return
        if url.path == "/api/health":
            payload = {
                "ok": True,
                "total": self.server.embeddings_count,
                "embeddingDim": self.server.embeddings_dim,
            }
            respond_json(self, 200, payload)
            return

        params = parse_qs(url.query)
        if url.path == "/api/channels":
            limit = _parse_int(params.get("limit", [None])[0])
            if limit <= 0:
                limit = 100
            limit = min(limit, 500)
            offset = _parse_int(params.get("offset", [None])[0])
            max_videos = _parse_non_negative_int(params.get("maxVideos", [None])[0])
            with self.server.db_lock:
                rows, total = fetch_channels(
                    self.server.db,
                    limit=limit,
                    offset=offset,
                    query=params.get("q", [""])[0] or "",
                    instance=params.get("instance", [""])[0] or "",
                    min_followers=_parse_int(params.get("minFollowers", [None])[0]),
                    min_videos=_parse_int(params.get("minVideos", [None])[0]),
                    max_videos=max_videos,
                    sort=params.get("sort", ["followers"])[0] or "followers",
                    direction=params.get("dir", ["desc"])[0] or "desc",
                )
            respond_json(
                self,
                200,
                {
                    "generatedAt": now_ms(),
                    "total": total,
                    "rows": rows,
                },
            )
            return

        if url.path == "/api/video":
            handle_video_request(self, self.server, params)
            return

        video_path_id = _extract_video_id_from_similar_path(url.path)
        if video_path_id is not None:
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            params.setdefault("id", [video_path_id])
            self._handle_similar(params)
            return

        respond_json(self, 404, {"error": "Not found"})

    def _rate_limit_check(self, path: str) -> bool:
        """Check per-IP rate limit for a path."""
        limiter = getattr(self.server, "rate_limiter", None)
        if limiter is None:
            return True
        ip = self._get_client_ip()
        key = f"{ip}:{path}"
        return limiter.allow(key)

    def _handle_similar_request(self, method: str) -> None:
        """Parse client likes and dispatch to similarity handler."""
        url = urlparse(self.path)
        if not self._rate_limit_check(url.path):
            respond_json(self, 429, {"error": "Rate limit exceeded"})
            return
        params = parse_qs(url.query)
        client_likes: list[dict[str, Any]] = []
        use_client_likes = bool(getattr(self.server, "use_client_likes", False))
        if method == "POST":
            length = self.headers.get("content-length")
            size = int(length or "0")
            if size > DEFAULT_CLIENT_LIKES_BODY_LIMIT:
                respond_json(self, 400, {"error": "Invalid JSON body"})
                return
            try:
                body = read_json_body(self)
            except ValueError as exc:
                respond_json(self, 400, {"error": str(exc)})
                return
            if isinstance(body, dict):
                incoming_payload = {
                    "likes": body.get("likes", []),
                    "user_id": body.get("user_id"),
                    "mode": body.get("mode"),
                }
                logging.info(
                    "[recommendations] incoming likes body=%s",
                    json.dumps(incoming_payload, ensure_ascii=True, separators=(",", ":")),
                )
            parsed = _parse_client_likes(body, DEFAULT_CLIENT_LIKES_MAX)
            client_likes = _resolve_client_likes(self.server, parsed)
        set_request_client_likes(client_likes, use_client_likes)

        try:
            self._handle_similar(params)
        finally:
            clear_request_context()

    def _fetch_random_rows(self, limit: int) -> list[dict[str, Any]]:
        """Fetch random rows from cache or DB."""
        rows = fetch_random_rows_from_cache(
            self.server, limit, error_threshold=self.server.video_error_threshold
        )
        if rows:
            return rows
        with self.server.db_lock:
            return fetch_random_rows(
                self.server.db,
                limit,
                error_threshold=self.server.video_error_threshold,
            )

    def _respond_rows(
        self,
        rows: list[dict[str, Any]],
        include_debug: bool,
        request_id: str,
        started_at: datetime,
        seed_payload: dict[str, Any],
    ) -> None:
        """Serialize rows and write HTTP response."""
        filtered_rows, _ = apply_serving_moderation_filters(
            self.server, rows, request_id=request_id
        )

        stable_rows = stable_video_rows(filtered_rows)
        stable_rows = maybe_attach_debug(stable_rows, filtered_rows, include_debug)
        duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        logging.info(
            "[similar-server][%s] done count=%d duration_ms=%d",
            request_id,
            len(stable_rows),
            duration_ms,
        )
        respond_json(
            self,
            200,
            {
                "generatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
                "total": self.server.embeddings_count,
                "count": len(stable_rows),
                "seed": seed_payload,
                "rows": stable_rows,
            },
        )

    def _handle_random(
        self,
        limit: int,
        include_debug: bool,
        request_id: str,
        started_at: datetime,
    ) -> None:
        """Handle explicit random feed requests."""
        rows = self._fetch_random_rows(limit)
        self._respond_rows(
            rows,
            include_debug,
            request_id,
            started_at,
            seed_payload={"random": True},
        )

    def _handle_home(
        self,
        user_id: str,
        limit: int,
        refresh_cache: bool,
        include_debug: bool,
        request_id: str,
        started_at: datetime,
        mode: str,
    ) -> None:
        """Handle home feed recommendations."""
        rows = self.server.recommendation_strategy.generate_recommendations(
            self.server, user_id, limit, refresh_cache, mode=mode
        )
        if not rows:
            rows = self._fetch_random_rows(limit)
            self._respond_rows(
                rows,
                include_debug,
                request_id,
                started_at,
                seed_payload={"user_id": user_id, "random": True, "mode": mode},
            )
            return
        self._respond_rows(
            rows,
            include_debug,
            request_id,
            started_at,
            seed_payload={"user_id": user_id, "mode": mode},
        )

    def _handle_seed_with_embedding(
        self,
        seed: dict[str, Any],
        user_id: str,
        limit: int,
        refresh_cache: bool,
        include_debug: bool,
        request_id: str,
        started_at: datetime,
        mode: str,
    ) -> None:
        """Handle similar videos when seed embedding is available."""
        recent_likes = fetch_recent_likes_request(user_id, MAX_LIKES)
        likes_available = bool(recent_likes)
        profile_name, profile_config = resolve_profile_config_with_guest(
            self.server.recommendation_strategy.config, mode, likes_available
        )
        logging.info(
            "[recommendations] profile=%s likes=%s",
            profile_name,
            "yes" if likes_available else "no",
        )
        policy = SimilarityCandidatesPolicy(
            refresh_cache=refresh_cache,
            use_cache=True,
            require_full_cache=bool(
                getattr(self.server, "similarity_require_full_cache", True)
            ),
        )
        settings = getattr(self.server.recommendation_strategy, "settings", None)
        similar_per_like = int(getattr(settings, "similar_per_like", 0) or 0)
        related_start = perf_counter()
        rows = get_similar_candidates(self.server, seed, similar_per_like, policy)
        related_ms = int((perf_counter() - related_start) * 1000)
        if rows:
            score_start = perf_counter()
            rows = score_and_rank_list(
                rows, profile_config, layer_name=mode, now_ms_value=now_ms()
            )
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
                self.server.related_personalization_enabled
                and self.server.related_personalization_deps is not None
            ):
                personalize_start = perf_counter()
                rows = rerank_related_videos(
                    self.server,
                    user_id,
                    rows,
                    self.server.related_personalization_deps,
                )
                personalize_ms = int((perf_counter() - personalize_start) * 1000)
                logging.info(
                    "[similar-server][%s] timing personalize=%dms",
                    request_id,
                    personalize_ms,
                )
            seed_payload = dict(seed.get("meta") or {})
            seed_payload["mode"] = mode
            self._respond_rows(
                rows,
                include_debug,
                request_id,
                started_at,
                seed_payload=seed_payload,
            )
            return
        respond_json(
            self,
            200,
            {
                "generatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
                "total": self.server.embeddings_count,
                "count": 0,
                "seed": seed.get("meta"),
                "rows": [],
            },
        )

    def _handle_vector_search(
        self,
        seed: dict[str, Any],
        limit: int,
        include_debug: bool,
        request_id: str,
        started_at: datetime,
    ) -> None:
        """Handle raw vector ANN search path."""
        if seed["vector"] is None:
            respond_json(
                self,
                400,
                {
                    "error": "Missing vector or video reference",
                    "hint": "Provide ?id=...&host=... or ensure a user profile exists",
                },
            )
            return
        vector = seed["vector"]
        if self.server.normalize_queries:
            vector = normalize_vector(vector)

        search_start = perf_counter()
        with self.server.index_lock:
            rowids, scores = search_index(
                self.server.index, vector, limit, seed["exclude_rowid"]
            )
        search_ms = int((perf_counter() - search_start) * 1000)

        meta_start = perf_counter()
        with self.server.db_lock:
            metadata = fetch_metadata(
                self.server.db,
                rowids,
                error_threshold=self.server.video_error_threshold,
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
        for rowid, score in zip(rowids, scores):
            meta = metadata.get(rowid)
            if not meta:
                continue
            rows.append({**meta, "score": score})
        self._respond_rows(
            rows,
            include_debug,
            request_id,
            started_at,
            seed_payload=seed["meta"],
        )

    def _handle_similar(self, params: dict[str, list[str]]) -> None:
        """Main similarity request handler (home, seed, vector, random)."""
        limit = _parse_int(params.get("limit", [str(self.server.default_limit)])[0])
        if limit == 0:
            limit = self.server.default_limit
        if self.server.default_limit > 0 and limit > self.server.default_limit:
            limit = self.server.default_limit
        vector_param = params.get("vector", [None])[0]
        id_param = params.get("id", params.get("video_id", [None]))[0]
        host_param = params.get("host", params.get("instance_domain", [None]))[0]
        uuid_param = params.get("uuid", params.get("video_uuid", [None]))[0]
        user_id = resolve_user_id(
            params.get("user_id", params.get("userId", [None]))[0]
        )
        random_param = params.get("random", [None])[0]
        refresh_cache = (
            _parse_bool(params.get("refresh_cache", [None])[0])
            or self.server.refresh_similarity_cache
        )
        debug_requested = _parse_bool(params.get("debug", [None])[0])
        debug_enabled = bool(getattr(self.server, "recommendations_debug_enabled", False))
        if debug_requested and not debug_enabled:
            respond_json(self, 403, {"error": "Debug mode is disabled"})
            return
        include_debug = debug_requested and bool(
            getattr(self.server, "recommendations_debug_enabled", False)
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
                self._handle_random(limit, include_debug, request_id, started_at)
                return
            seed_start = perf_counter()
            with self.server.db_lock:
                seed = (
                    resolve_seed(
                        self.server.db,
                        self.server.embeddings_dim,
                        vector_param,
                        id_param,
                        host_param,
                        uuid_param,
                    )
                    if (vector_param or id_param or uuid_param)
                    else None
                )
            seed_ms = int((perf_counter() - seed_start) * 1000)
            logging.info(
                "[similar-server][%s] timing resolve_seed=%dms",
                request_id,
                seed_ms,
            )

            mode = "home" if seed is None else "upnext"

            if seed is None:
                self._handle_home(
                    user_id,
                    limit,
                    refresh_cache,
                    include_debug,
                    request_id,
                    started_at,
                    mode,
                )
                return

            if seed.get("meta") and seed.get("embedding") is not None:
                self._handle_seed_with_embedding(
                    seed,
                    user_id,
                    limit,
                    refresh_cache,
                    include_debug,
                    request_id,
                    started_at,
                    mode,
                )
                return

            if seed.get("random"):
                rows = self._fetch_random_rows(limit)
                self._respond_rows(
                    rows,
                    include_debug,
                    request_id,
                    started_at,
                    seed_payload=seed["meta"],
                )
                return

            self._handle_vector_search(
                seed, limit, include_debug, request_id, started_at
            )
        except ValueError as exc:
            bad_request = {
                "Invalid vector parameter",
                "Vector dimension does not match embeddings",
                "Vector norm is zero",
            }
            status = 400 if str(exc) in bad_request else 500
            respond_json(self, status, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover
            logging.exception("server error")
            respond_json(self, 500, {"error": str(exc)})
        finally:
            clear_request_context()


def _parse_int(value: str | None) -> int:
    """Parse a positive integer; return 0 on invalid input."""
    try:
        parsed = int(value or "0")
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _parse_bool(value: str | None) -> bool:
    """Parse boolean-like values from query params."""
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_non_negative_int(value: str | None) -> int | None:
    """Parse a non-negative integer; return None on invalid input."""
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _make_request_id() -> str:
    """Generate a short request id for logs."""
    return hex(np.random.randint(0, 0xFFFFFF))[2:].zfill(6)


def _extract_video_id_from_similar_path(path: str) -> str | None:
    """Resolve /videos/{id}/similar route shape to seed video id."""
    if not path.startswith("/videos/") or not path.endswith("/similar"):
        return None
    parts = path.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "videos" or parts[2] != "similar":
        return None
    video_id = parts[1].strip()
    return video_id or None
