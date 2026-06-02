"""FastAPI app factory for the Engine API.

The app owns HTTP adaptation: CORS responses, body parsing, rate limiting, and
conversion from framework-neutral ``RouteResult`` values to FastAPI responses.
Engine services stay free of FastAPI and legacy handler-shaped abstractions.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from http_adapters import cors_json, cors_options, read_json_body_bytes, read_request_body
from route_results import RouteResult
from routes.channels import handle_channels
from routes.health import handle_health
from routes.internal_discovery import handle_internal_discovery_route
from routes.internal_events import handle_internal_events_ingest_route
from routes.internal_search import handle_internal_search_videos_route
from routes.internal_videos import (
    handle_internal_video_resolve_route,
    handle_internal_videos_metadata_route,
)
from routes.recommendations import (
    handle_similar_get,
    handle_similar_post,
)
from routes.videos import handle_video_route
from runtime import EngineRuntimeState
from server_config import DEFAULT_CLIENT_LIKES_BODY_LIMIT

SIMILAR_POST_ROUTES = {"/recommendations", "/videos/similar"}


def _route_response(result: RouteResult):
    """Serialize a framework-neutral route result through the Engine JSON contract."""
    return cors_json(result.status, result.payload)


def _rate_limit_or_none(request: Request, state: EngineRuntimeState, path: str):
    """Apply the current Engine rate-limit key before route execution."""
    limiter = getattr(state, "rate_limiter", None)
    if limiter is None:
        return None
    ip = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    if not ip:
        ip = request.headers.get("X-Real-IP", "").strip()
    if not ip and request.client:
        ip = request.client.host
    if not ip:
        ip = "unknown"
    if not limiter.allow(f"{ip}:{path}"):
        return cors_json(429, {"error": "Rate limit exceeded"})
    return None


def create_app(state: EngineRuntimeState) -> FastAPI:
    """Create the Engine FastAPI app using route-result boundaries."""
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.state.runtime = state

    @app.options("/{path:path}")
    async def options_any(path: str) -> Any:
        """Serve the current Engine CORS preflight response."""
        return cors_options()

    @app.get("/api/health")
    async def health(request: Request) -> Any:
        """Return Engine health through the route-result module."""
        if response := _rate_limit_or_none(request, state, "/api/health"):
            return response
        return _route_response(handle_health(state))

    @app.get("/api/channels")
    async def channels(request: Request) -> Any:
        """Return Engine channel rows through current query parsing."""
        if response := _rate_limit_or_none(request, state, "/api/channels"):
            return response
        return _route_response(handle_channels(state, dict(parse_qs(request.url.query))))

    @app.get("/api/video")
    async def video(request: Request) -> Any:
        """Return Engine video metadata through the current video route."""
        if response := _rate_limit_or_none(request, state, "/api/video"):
            return response
        return _route_response(handle_video_route(state, dict(parse_qs(request.url.query))))

    @app.get("/videos/{video_id}/similar")
    async def similar_by_path(video_id: str, request: Request) -> Any:
        """Handle path-id similar routes with the current id injection behavior."""
        path = request.url.path
        if response := _rate_limit_or_none(request, state, path):
            return response
        params = dict(parse_qs(request.url.query))
        params.setdefault("id", [video_id])
        return _route_response(handle_similar_get(state, path, params))

    @app.post("/recommendations")
    @app.post("/videos/similar")
    async def similar_post(request: Request) -> Any:
        """Handle recommendation POST routes through parsed-body route results."""
        path = request.url.path
        if response := _rate_limit_or_none(request, state, path):
            return response
        raw_body = await read_request_body(request)
        declared_size = int(request.headers.get("content-length") or len(raw_body) or 0)
        if max(len(raw_body), declared_size) > DEFAULT_CLIENT_LIKES_BODY_LIMIT:
            return cors_json(400, {"error": "Invalid JSON body"})
        try:
            body = read_json_body_bytes(raw_body, DEFAULT_CLIENT_LIKES_BODY_LIMIT)
        except ValueError as exc:
            return cors_json(400, {"error": str(exc)})
        return _route_response(
            handle_similar_post(state, path, dict(parse_qs(request.url.query)), body)
        )

    @app.post("/internal/videos/resolve")
    async def internal_video_resolve(request: Request) -> Any:
        """Resolve internal video identity through parsed JSON body data."""
        raw_body = await read_request_body(request)
        try:
            body = read_json_body_bytes(raw_body)
        except ValueError as exc:
            return cors_json(400, {"error": str(exc)})
        return _route_response(handle_internal_video_resolve_route(state, body))

    @app.post("/internal/videos/metadata")
    async def internal_videos_metadata(request: Request) -> Any:
        """Return internal batch metadata through parsed JSON body data."""
        raw_body = await read_request_body(request)
        try:
            body = read_json_body_bytes(raw_body)
        except ValueError as exc:
            return cors_json(400, {"error": str(exc)})
        return _route_response(handle_internal_videos_metadata_route(state, body))

    @app.get("/internal/discovery/fresh")
    async def internal_discovery_fresh(request: Request) -> Any:
        """Return internal fresh discovery provider rows for Client backend."""
        if response := _rate_limit_or_none(request, state, "/internal/discovery/fresh"):
            return response
        return _route_response(
            handle_internal_discovery_route(state, "fresh", dict(parse_qs(request.url.query)))
        )

    @app.get("/internal/discovery/popular")
    async def internal_discovery_popular(request: Request) -> Any:
        """Return internal popular discovery provider rows for Client backend."""
        if response := _rate_limit_or_none(request, state, "/internal/discovery/popular"):
            return response
        return _route_response(
            handle_internal_discovery_route(state, "popular", dict(parse_qs(request.url.query)))
        )

    @app.get("/internal/search/videos")
    async def internal_search_videos(request: Request) -> Any:
        """Return internal video-search provider rows for Client backend."""
        if response := _rate_limit_or_none(request, state, "/internal/search/videos"):
            return response
        return _route_response(handle_internal_search_videos_route(state, dict(parse_qs(request.url.query))))

    @app.post("/internal/events/ingest")
    async def internal_events_ingest(request: Request) -> Any:
        """Ingest bridge events while preserving the current ingest-mode gate."""
        raw_body = await read_request_body(request)
        try:
            body = read_json_body_bytes(raw_body)
        except ValueError as exc:
            return cors_json(400, {"error": str(exc)})
        return _route_response(handle_internal_events_ingest_route(state, body))

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def not_found(path: str) -> Any:
        """Return the legacy JSON 404 body for unknown Engine routes."""
        return cors_json(404, {"error": "Not found"})

    return app
