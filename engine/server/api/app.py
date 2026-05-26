"""FastAPI app factory for the Engine API.

Stage 10 changes only the HTTP adapter. The app delegates to the route modules
introduced in Stage 4, using a small handler adapter so current parsing,
response, request-context, and debug behavior stay intact.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from http_adapters import FastAPIHandlerAdapter, adapter_response, cors_json, cors_options
from routes.channels import handle_channels
from routes.health import handle_health
from routes.internal_events import handle_internal_events_ingest_route
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

SIMILAR_POST_ROUTES = {"/recommendations", "/videos/similar"}


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
    """Create the Engine FastAPI app using existing route/service modules."""
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.state.runtime = state

    @app.options("/{path:path}")
    async def options_any(path: str) -> Any:
        """Serve the current Engine CORS preflight response."""
        return cors_options()

    @app.get("/api/health")
    async def health(request: Request) -> Any:
        """Return Engine health through the existing route module."""
        if response := _rate_limit_or_none(request, state, "/api/health"):
            return response
        handler = FastAPIHandlerAdapter(request, state)
        handle_health(handler, state)
        return adapter_response(handler)

    @app.get("/api/channels")
    async def channels(request: Request) -> Any:
        """Return Engine channel rows through existing query parsing."""
        if response := _rate_limit_or_none(request, state, "/api/channels"):
            return response
        handler = FastAPIHandlerAdapter(request, state)
        handle_channels(handler, state, dict(parse_qs(request.url.query)))
        return adapter_response(handler)

    @app.get("/api/video")
    async def video(request: Request) -> Any:
        """Return Engine video metadata through the existing video route."""
        if response := _rate_limit_or_none(request, state, "/api/video"):
            return response
        handler = FastAPIHandlerAdapter(request, state)
        handle_video_route(handler, state, dict(parse_qs(request.url.query)))
        return adapter_response(handler)

    @app.get("/videos/{video_id}/similar")
    async def similar_by_path(video_id: str, request: Request) -> Any:
        """Handle path-id similar routes with the current id injection behavior."""
        path = request.url.path
        if response := _rate_limit_or_none(request, state, path):
            return response
        handler = FastAPIHandlerAdapter(request, state)
        params = dict(parse_qs(request.url.query))
        params.setdefault("id", [video_id])
        handle_similar_get(handler, state, path, params)
        return adapter_response(handler)

    @app.post("/recommendations")
    @app.post("/videos/similar")
    async def similar_post(request: Request) -> Any:
        """Handle recommendation POST routes through the existing route module."""
        path = request.url.path
        if response := _rate_limit_or_none(request, state, path):
            return response
        body = await request.body()
        handler = FastAPIHandlerAdapter(request, state, body)
        handle_similar_post(handler, state, path, dict(parse_qs(request.url.query)))
        return adapter_response(handler)

    @app.post("/internal/videos/resolve")
    async def internal_video_resolve(request: Request) -> Any:
        """Resolve internal video identity through the existing route module."""
        body = await request.body()
        handler = FastAPIHandlerAdapter(request, state, body)
        handle_internal_video_resolve_route(handler, state)
        return adapter_response(handler)

    @app.post("/internal/videos/metadata")
    async def internal_videos_metadata(request: Request) -> Any:
        """Return internal batch metadata through the existing route module."""
        body = await request.body()
        handler = FastAPIHandlerAdapter(request, state, body)
        handle_internal_videos_metadata_route(handler, state)
        return adapter_response(handler)

    @app.post("/internal/events/ingest")
    async def internal_events_ingest(request: Request) -> Any:
        """Ingest bridge events while preserving the current ingest-mode gate."""
        body = await request.body()
        handler = FastAPIHandlerAdapter(request, state, body)
        handle_internal_events_ingest_route(handler, state)
        return adapter_response(handler)

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def not_found(path: str) -> Any:
        """Return the legacy JSON 404 body for unknown Engine routes."""
        return cors_json(404, {"error": "Not found"})

    return app
