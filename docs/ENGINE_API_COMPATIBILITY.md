# Engine API Compatibility

## Purpose

This document records Engine API backward-compatibility decisions that are preserved or introduced during route and service refactors. It is not a public API reference; it explains compatibility constraints that future refactors must not accidentally remove.

## Engine API route split

The Engine API route split moved Engine route adapters and orchestration services out of `engine/server/api/handlers/similar.py` while preserving the then-active HTTP runtime, route paths, response shapes, and startup behavior. The later stdlib HTTP cleanup removed the transitional stdlib adapter; the route compatibility decisions below remain binding for the FastAPI adapter.

### `/videos/{id}/similar` path-id injection

Decision: `/videos/{id}/similar` keeps path-id injection into the same internal similar-request path.

Reason: Client/frontend behavior and existing smoke checks expect path-based similar lookup to behave like query/body-based similar lookup.

Implementation action: `engine/server/api/routes/recommendations.py` extracts the path id and adds it to the existing `id` query parameter before calling `services/recommendation_service.py`.

Tests: `tests/engine_api/test_similar_route_characterization.py`.

Removal condition, if any: Only a later public route compatibility plan may replace this alias, and it must preserve or explicitly migrate all callers.

### Internal event ingest mode gate

Decision: `/internal/events/ingest` keeps the `ENGINE_INGEST_MODE` gate and current `501` response when bridge ingest is disabled.

Reason: Existing deployments can disable bridge ingest without changing route availability or causing Client calls to hit ingestion internals unexpectedly.

Implementation action: `engine/server/api/routes/internal_events.py` checks `server.engine_ingest_mode` before delegating to the existing ingest handler.

Tests: `tests/engine_api/test_engine_ingest_mode_characterization.py` and `tests/engine_api/test_internal_events_ingest_characterization.py`.

Removal condition, if any: Only a dedicated ingest-mode plan may remove or replace this gate.

### Recommendation request validation

Decision: recommendation request validation keeps current body-size, likes-count, malformed-likes, debug-disabled, and invalid-JSON behavior.

Reason: Client backend and behavior-freeze tests depend on these request-contract failures remaining stable during route splitting.

Implementation action: `engine/server/api/services/recommendation_service.py` owns the helper behavior directly; the Engine API route split does not introduce schema-model validation.

Tests: `tests/engine_api/test_recommendations_request_contract.py`, `tests/engine_api/test_similar_route_characterization.py`, and `tests/engine_api/test_engine_route_dispatch_characterization.py`.

Removal condition, if any: A later schema/contract plan may replace this validation only after adding before/after contract tests and documenting affected Client behavior.

### Dynamic video metadata overlay

Decision: dynamic video metadata overlay remains owned by `handlers/video.py` through a thin route/service wrapper without changing response shape.

Reason: The frontend video page depends on current DB fallback and dynamic PeerTube metadata override behavior.

Implementation action: `engine/server/api/routes/videos.py` delegates to `engine/server/api/services/video_service.py`, which delegates to `handlers/video.py`.

Tests: `tests/engine_api/test_video_metadata_characterization.py`.

Removal condition, if any: Dynamic metadata ownership can move only in a later video-service plan that preserves the current response shape and frontend behavior.

### Channel query parsing compatibility

Decision: `/api/channels` keeps current query parsing defaults and caps while moving parsing to an Engine API service.

Reason: Channel listing clients depend on `limit`, `offset`, follower/video filters, sort, and direction being interpreted as they were before route extraction.

Implementation action: `engine/server/api/services/channel_service.py` owns current parameter normalization and `routes/channels.py` preserves the current response payload shape.

Tests: `tests/engine_api/test_channels_route_characterization.py`.

Removal condition, if any: A later channel API plan may change query semantics only with explicit contract tests and documentation updates.

### Transitional Engine handler removed

Decision: The transitional stdlib Engine handler from the route split was removed during the stdlib HTTP cleanup; active route ownership now lives in FastAPI app registration and `routes/*`.

Reason: After the FastAPI migration introduced FastAPI adapters, keeping a second handler dispatch path would create duplicate ownership and drift risk.

Implementation action: The transitional `engine/server/api/handlers/similar.py` helper re-export shim has been removed. CORS, rate-limit, unknown-route, and path-id behavior remain covered by FastAPI route tests and direct `services/recommendation_service.py` imports.

Tests: `tests/engine_api/test_engine_route_dispatch_characterization.py`, `tests/engine_api/test_similar_route_characterization.py`, and `tests/framework/test_engine_fastapi_contract.py`.

Removal condition, if any: Already removed. New helper imports must use `engine/server/api/services/recommendation_service.py` directly.

### Handler-shaped response helper removed

Decision: Engine API route helpers no longer use handler-shaped response capture or fake route-handler objects.

Reason: The FastAPI response-helper cleanup completes the FastAPI HTTP-layer cleanup. Route behavior remains unchanged, but HTTP response construction now belongs to FastAPI route adapters instead of compatibility helper objects.

Implementation action: Engine route and handler helper modules return framework-neutral `RouteResult` values. `engine/server/api/app.py` converts those results to the current JSON/CORS response contract.

Tests: `tests/framework/test_no_legacy_handler_helpers.py`, `tests/engine_api/*`, `tests/framework/*`, and `engine/server/api/tests/test_recommendations_likes_limit.py`.

Removal condition, if any: Completed by the FastAPI response-helper cleanup.


## Internal Discovery Providers

Engine exposes internal `/internal/discovery/fresh`, `/internal/discovery/popular`, and `/internal/discovery/random` providers plus `/internal/video-facets` for the Client backend. These are not browser-facing public API v1 routes; public Discovery/Search contracts live in the Client backend. Fresh/Popular/Random accept the shared `language/category/tag/instance` filters and apply serving eligibility before page cut. Fresh reads canonical `videos` in publication order; Popular/Trending reads persisted `videos.popularity` order. Tag selection uses prepared `video_tags` rather than request-time `json_each(tags_json)`, and `/internal/video-facets` reads only the prepared singleton snapshot. Facet counts summarize canonical metadata rows with no `invalid_reason`; they intentionally do not promise exact counts after runtime error-threshold, instance-denylist, or channel-moderation filtering. Missing/corrupt/incompatible prepared facets return controlled `video_facets_unavailable` instead of rebuilding on demand.

The existing `/recommendations` route remains the recommendation computation boundary and accepts optional Home video filters for the finite Discovery bridge. Filtering happens at the final resolved canonical-row boundary, so filtered Recommended may underfill rather than refilling the legacy candidate batch. Similar/up-next routes do not inherit Home filters.

Random cursors are bound to the persisted artifact `build_id`. A replaced generation returns machine-readable `stale_cursor`; missing/incompatible random artifacts return `random_provider_unavailable` without runtime rebuilding or unstable random-pagination fallback.
