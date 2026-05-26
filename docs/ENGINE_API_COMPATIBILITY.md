# Engine API Compatibility

## Purpose

This document records Engine API backward-compatibility decisions that are preserved or introduced during route and service refactors. It is not a public API reference; it explains compatibility constraints that future refactors must not accidentally remove.

## Stage 4 route split

Stage 4 split Engine route adapters and orchestration services out of `engine/server/api/handlers/similar.py` while preserving the existing stdlib HTTP runtime, route paths, response shapes, and startup behavior.

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

Reason: Client backend and Stage 0 tests depend on these request-contract failures remaining stable during route splitting.

Implementation action: `engine/server/api/services/recommendation_service.py` reuses the existing helper behavior moved from `handlers/similar.py`; Stage 4 does not introduce schema-model validation.

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

### SimilarHandler remaining adapter ownership

Decision: `SimilarHandler` keeps stdlib HTTP adapter responsibilities: access logging, CORS preflight, GET/POST dispatch, and rate-limit checks.

Reason: Stage 4 is not a framework migration; moving these concerns would affect request lifecycle behavior outside route extraction.

Implementation action: `engine/server/api/handlers/similar.py` delegates route behavior to `routes/*` but keeps `_get_client_ip()`, `_get_full_url()`, `_log_access_start()`, `do_OPTIONS()`, `do_GET()`, `do_POST()`, and `_rate_limit_check()`.

Tests: `tests/engine_api/test_engine_route_dispatch_characterization.py`.

Removal condition, if any: A future framework migration or handler-cleanup stage may move this behavior only after preserving CORS, logging, and rate-limit contracts.
