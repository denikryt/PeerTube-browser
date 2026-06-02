"""FastAPI app factory for the Client backend.

The route adapters preserve the existing Client backend HTTP contract while
reusing the Stage 3 services and repositories. Public request and response
shapes are still dict/bytes based; Stage 10 intentionally avoids Pydantic public
schemas so validation errors do not change.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

from fastapi import FastAPI, Request
from http_adapters import cors_bytes, cors_json, cors_options, rate_limit_key, read_json_body
from lib.http_utils import resolve_user_id
from lib.time_utils import now_ms
from runtime import ClientRuntimeState
from schemas import ProxyBytesResult, ServiceResult
from services.bridge_publisher import publish_event
from services.discovery_v1 import (
    handle_ordered_feed,
    handle_random,
    handle_recommendations,
    handle_similar as handle_v1_similar,
    handle_video as handle_v1_video,
)
from services.engine_gateway import (
    proxy_engine_request,
    sanitize_get_query,
    sanitize_post_request,
    summarize_proxy_likes,
)
from services.search_v1 import handle_channel_search, handle_video_search
from services.profile import (
    get_client_likes_metadata,
    get_profile_likes_metadata,
    get_user_profile,
    parse_positive_int,
    reset_user_profile,
)
from services.user_actions import handle_user_action

MAX_LIKES = 100
MAX_CLIENT_LIKES = 200
MAX_ENGINE_RECOMMENDATION_LIKES = 5
ENGINE_PROXY_TIMEOUT_SECONDS = 20
ENGINE_PROXY_MAX_BODY_BYTES = 1_000_000
ENGINE_PROXY_RETRY_COUNT = 1
ENGINE_PROXY_RETRY_DELAY_SECONDS = 0.25


def _proxy_response(result: ProxyBytesResult | ServiceResult):
    """Translate service proxy results to FastAPI responses preserving bytes."""
    if isinstance(result, ProxyBytesResult):
        return cors_bytes(result.status, result.payload, result.content_type)
    return cors_json(result.status, result.body)


def _rate_limit_or_none(state: ClientRuntimeState, request: Request, path: str):
    """Apply current rate-limit behavior and return a response on rejection."""
    if not state.rate_limiter.allow(rate_limit_key(request, path)):
        return cors_json(429, {"error": "Rate limit exceeded"})
    return None


def create_app(state: ClientRuntimeState) -> FastAPI:
    """Create the Client FastAPI app using existing service boundaries."""
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.state.runtime = state

    @app.options("/{path:path}")
    async def options_any(path: str) -> Any:
        """Serve current CORS preflight response for all Client routes."""
        return cors_options()

    @app.get("/api/health")
    async def health() -> Any:
        """Return the existing Client health payload."""
        return cors_json(
            200,
            {
                "ok": True,
                "service": "client-backend",
                "engine_ingest_base": state.engine_ingest_base,
                "publish_mode": state.publish_mode,
            },
        )

    @app.get("/api/user-profile")
    async def user_profile(request: Request) -> Any:
        """Return local Client profile data via the existing profile service."""
        if response := _rate_limit_or_none(state, request, "/api/user-profile"):
            return response
        params = request.query_params
        user_id = resolve_user_id(params.get("user_id") or params.get("userId"))
        result = get_user_profile(state.users, user_id, MAX_LIKES)
        return cors_json(result.status, result.body)

    @app.get("/api/user-profile/likes")
    async def user_profile_likes(request: Request) -> Any:
        """Return Engine-enriched metadata for locally stored likes."""
        if response := _rate_limit_or_none(state, request, "/api/user-profile/likes"):
            return response
        params = request.query_params
        user_id = resolve_user_id(params.get("user_id") or params.get("userId"))
        limit = parse_positive_int(params.get("limit"))
        result = get_profile_likes_metadata(
            state.users, state.engine_ingest_base, user_id, limit, MAX_LIKES
        )
        return cors_json(result.status, result.body)

    @app.post("/api/user-action")
    async def user_action(request: Request) -> Any:
        """Apply a Client user action and publish its bridge event."""
        if response := _rate_limit_or_none(state, request, "/api/user-action"):
            return response
        try:
            body = await read_json_body(request)
        except ValueError as exc:
            return cors_json(400, {"error": str(exc)})
        result = handle_user_action(
            state.users, state.engine_ingest_base, state.publish_mode, body, MAX_LIKES
        )
        return cors_json(result.status, result.body)

    @app.post("/api/user-profile/reset")
    async def user_profile_reset(request: Request) -> Any:
        """Clear local Client likes for one user."""
        if response := _rate_limit_or_none(state, request, "/api/user-profile/reset"):
            return response
        try:
            body = await read_json_body(request)
        except ValueError as exc:
            return cors_json(400, {"error": str(exc)})
        raw_user_id = body.get("user_id") if isinstance(body, dict) else None
        result = reset_user_profile(state.users, raw_user_id)
        return cors_json(result.status, result.body)

    @app.post("/api/user-profile/likes")
    async def user_profile_likes_from_client(request: Request) -> Any:
        """Resolve frontend-provided like identities to Engine metadata rows."""
        if response := _rate_limit_or_none(state, request, "/api/user-profile/likes"):
            return response
        try:
            body = await read_json_body(request)
        except ValueError as exc:
            return cors_json(400, {"error": str(exc)})
        result = get_client_likes_metadata(state.engine_ingest_base, body, MAX_CLIENT_LIKES)
        return cors_json(result.status, result.body)

    @app.post("/client/events/publish")
    async def client_events_publish(request: Request) -> Any:
        """Publish a normalized Client event to the configured bridge mode."""
        if response := _rate_limit_or_none(state, request, "/client/events/publish"):
            return response
        try:
            body = await read_json_body(request)
        except ValueError as exc:
            return cors_json(400, {"error": str(exc)})
        if not isinstance(body, dict):
            return cors_json(400, {"error": "Invalid JSON body"})
        if not body.get("event_id"):
            body["event_id"] = f"client-{uuid4()}"
        if not body.get("published_at"):
            body["published_at"] = now_ms()
        result = publish_event(state.publish_mode, state.engine_ingest_base, body)
        return cors_json(200 if result.get("ok") else 502, result)

    @app.get("/api/v1/discovery/random")
    async def v1_discovery_random(request: Request) -> Any:
        """Return Client-owned v1 random discovery feed."""
        path = request.url.path
        if response := _rate_limit_or_none(state, request, path):
            return response
        result = handle_random(state.engine_ingest_base, dict(parse_qs(request.url.query)))
        return cors_json(result.status, result.body)

    @app.get("/api/v1/discovery/fresh")
    async def v1_discovery_fresh(request: Request) -> Any:
        """Return Client-owned v1 fresh discovery feed."""
        path = request.url.path
        if response := _rate_limit_or_none(state, request, path):
            return response
        result = handle_ordered_feed(state.engine_ingest_base, dict(parse_qs(request.url.query)), "fresh")
        return cors_json(result.status, result.body)

    @app.get("/api/v1/discovery/popular")
    async def v1_discovery_popular(request: Request) -> Any:
        """Return Client-owned v1 popular discovery feed."""
        path = request.url.path
        if response := _rate_limit_or_none(state, request, path):
            return response
        result = handle_ordered_feed(state.engine_ingest_base, dict(parse_qs(request.url.query)), "popular")
        return cors_json(result.status, result.body)

    @app.get("/api/v1/discovery/recommendations")
    async def v1_discovery_recommendations(request: Request) -> Any:
        """Return Client-owned v1 personalized/guest recommendations feed."""
        path = request.url.path
        if response := _rate_limit_or_none(state, request, path):
            return response
        params = request.query_params
        user_id = resolve_user_id(params.get("user_id") or params.get("userId"))
        result = handle_recommendations(
            state.users,
            state.engine_ingest_base,
            user_id,
            dict(parse_qs(request.url.query)),
        )
        return cors_json(result.status, result.body)

    @app.get("/api/v1/search/videos")
    async def v1_search_videos(request: Request) -> Any:
        """Return Client-owned v1 video search results."""
        path = request.url.path
        if response := _rate_limit_or_none(state, request, path):
            return response
        result = handle_video_search(state.engine_ingest_base, dict(parse_qs(request.url.query)))
        return cors_json(result.status, result.body)

    @app.get("/api/v1/search/channels")
    async def v1_search_channels(request: Request) -> Any:
        """Return Client-owned v1 channel search results."""
        path = request.url.path
        if response := _rate_limit_or_none(state, request, path):
            return response
        result = handle_channel_search(state.engine_ingest_base, dict(parse_qs(request.url.query)))
        return cors_json(result.status, result.body)

    @app.get("/api/v1/videos/{video_ref}")
    async def v1_video(video_ref: str, request: Request) -> Any:
        """Return Client-owned v1 video metadata."""
        path = "/api/v1/videos/{id}"
        if response := _rate_limit_or_none(state, request, path):
            return response
        result = handle_v1_video(state.engine_ingest_base, video_ref, dict(parse_qs(request.url.query)))
        return cors_json(result.status, result.body)

    @app.get("/api/v1/videos/{video_ref}/similar")
    async def v1_video_similar(video_ref: str, request: Request) -> Any:
        """Return Client-owned v1 similar video feed."""
        path = "/api/v1/videos/{id}/similar"
        if response := _rate_limit_or_none(state, request, path):
            return response
        result = handle_v1_similar(state.engine_ingest_base, video_ref, dict(parse_qs(request.url.query)))
        return cors_json(result.status, result.body)

    @app.get("/api/video")
    @app.get("/api/channels")
    async def proxy_get(request: Request) -> Any:
        """Proxy allowlisted Client read GET routes to Engine."""
        path = request.url.path
        if response := _rate_limit_or_none(state, request, path):
            return response
        query_result = sanitize_get_query(path, dict(parse_qs(request.url.query)))
        if isinstance(query_result, ServiceResult):
            return cors_json(query_result.status, query_result.body)
        result = proxy_engine_request(
            state.engine_ingest_base,
            "GET",
            path,
            sanitized_query=query_result,
            timeout_seconds=ENGINE_PROXY_TIMEOUT_SECONDS,
            max_body_bytes=ENGINE_PROXY_MAX_BODY_BYTES,
            retry_count=ENGINE_PROXY_RETRY_COUNT,
            retry_delay_seconds=ENGINE_PROXY_RETRY_DELAY_SECONDS,
        )
        return _proxy_response(result)

    @app.post("/recommendations")
    @app.post("/videos/similar")
    async def proxy_post(request: Request) -> Any:
        """Proxy allowlisted Client read POST routes to Engine."""
        path = request.url.path
        if response := _rate_limit_or_none(state, request, path):
            return response
        try:
            body = await read_json_body(request)
        except ValueError as exc:
            return cors_json(400, {"error": str(exc)})
        if not isinstance(body, dict):
            return cors_json(400, {"error": "Invalid JSON body"})
        max_likes = MAX_ENGINE_RECOMMENDATION_LIKES if path == "/recommendations" else MAX_CLIENT_LIKES
        sanitized = sanitize_post_request(
            path, dict(parse_qs(request.url.query)), body, max_likes
        )
        if isinstance(sanitized, ServiceResult):
            return cors_json(sanitized.status, sanitized.body)
        sanitized_query, sanitized_body = sanitized
        if path == "/recommendations":
            likes_count, likes_list, likes_omitted = summarize_proxy_likes(
                sanitized_body.get("likes")
            )
            logging.info(
                "client recommendations.incoming_likes likes_count=%s "
                "likes_omitted=%s user_id=%s mode=%s likes=%s",
                likes_count,
                likes_omitted,
                sanitized_body.get("user_id"),
                sanitized_body.get("mode"),
                likes_list,
            )
        result = proxy_engine_request(
            state.engine_ingest_base,
            "POST",
            path,
            sanitized_query=sanitized_query,
            body=sanitized_body,
            timeout_seconds=ENGINE_PROXY_TIMEOUT_SECONDS,
            max_body_bytes=ENGINE_PROXY_MAX_BODY_BYTES,
            retry_count=ENGINE_PROXY_RETRY_COUNT,
            retry_delay_seconds=ENGINE_PROXY_RETRY_DELAY_SECONDS,
        )
        return _proxy_response(result)

    # FastAPI returns its own 404 body otherwise, so the catch-all keeps the
    # legacy JSON shape for unknown routes.
    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def not_found(path: str) -> Any:
        """Return the legacy JSON 404 body for unknown Client routes."""
        return cors_json(404, {"error": "Not found"})

    return app
