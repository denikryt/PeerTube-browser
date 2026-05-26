# Framework Compatibility

This document records compatibility decisions made while replacing the active
stdlib HTTP adapters with FastAPI/uvicorn adapters. The purpose is to preserve
observable Client and Engine HTTP behavior while changing only the framework
boundary.

## server.py entrypoint paths remain stable

Decision: Existing `client/backend/server.py` and `engine/server/api/server.py` executable paths remain stable.

Reason: Installer scripts, smoke scripts, operational docs, and local commands may invoke those files directly.

Implementation action: Convert the files into FastAPI/uvicorn compatibility launchers without moving or deleting the paths.

Tests: `tests/framework/test_entrypoint_compatibility.py` and existing boundary/smoke checks.

Removal condition, if any: None in Stage 10.

## CORS and OPTIONS behavior is preserved

Decision: FastAPI adapters return the current permissive CORS headers and `204` preflight behavior.

Reason: Frontend and local reverse-proxy behavior depend on the existing CORS contract.

Implementation action: Add explicit `OPTIONS /{path:path}` handlers and adapter helpers instead of relying on FastAPI defaults.

Tests: `tests/framework/test_client_fastapi_contract.py` and `tests/framework/test_engine_fastapi_contract.py`.

Removal condition, if any: Only a future API/security plan can change CORS policy.

## Rate-limit keys are preserved

Decision: FastAPI adapters keep the current `client_ip:path` rate-limit keys.

Reason: Changing the key changes observable throttling behavior.

Implementation action: Resolve client IP from forwarded headers, real IP, and socket fallback, then call the same `RateLimiter` with the same key shape.

Tests: `tests/framework/test_client_fastapi_contract.py` and `tests/framework/test_engine_fastapi_contract.py`.

Removal condition, if any: Only a future rate-limit policy plan can change this behavior.

## Request-size and invalid JSON errors are preserved

Decision: Existing routes keep manual dict parsing and current `Invalid JSON body` errors instead of FastAPI/Pydantic validation errors.

Reason: Current clients and characterization tests expect explicit compatibility bodies and status codes.

Implementation action: Read raw request bytes in adapter helpers and pass dict payloads to the existing service or route parsing code.

Tests: Existing Client and Engine request-contract tests plus `tests/framework/test_client_fastapi_contract.py`.

Removal condition, if any: Dedicated public API schema plan.

## Client read proxy byte/status/content-type preservation is preserved

Decision: Client read proxy responses preserve upstream status, bytes, and content type.

Reason: The frontend and diagnostics consume Engine responses through the Client gateway; the framework migration must not reinterpret upstream payloads.

Implementation action: Return FastAPI `Response` objects from proxy results using the captured upstream bytes and content type.

Tests: `tests/framework/test_client_fastapi_contract.py` and existing Client proxy characterization tests.

Removal condition, if any: Dedicated gateway contract plan.

## /videos/{id}/similar path-id injection is preserved

Decision: FastAPI path handling injects `{id}` into the same `id` parameter used by the existing recommendation route path.

Reason: Existing recommendation code expects the path id to appear in route parameters.

Implementation action: The FastAPI route for `/videos/{video_id}/similar` delegates through the Stage 4 route adapter with the current path and parsed query params.

Tests: `tests/framework/test_engine_fastapi_contract.py` and `tests/engine_api/test_similar_route_characterization.py`.

Removal condition, if any: None in Stage 10.

## /internal/events/ingest mode gate is preserved

Decision: `ENGINE_INGEST_MODE != bridge` still returns the current `501` response body.

Reason: The mode gate is a project-specific internal compatibility contract between Client publishing and Engine ingest.

Implementation action: FastAPI delegates to the Stage 4 internal-events route adapter, which owns the gate.

Tests: `tests/framework/test_engine_fastapi_contract.py` and `tests/engine_api/test_engine_ingest_mode_characterization.py`.

Removal condition, if any: Dedicated ingest-mode plan.

## FAISS startup prerequisite is unchanged

Decision: Stage 10 does not lazy-load, fake, or isolate FAISS in the Engine entrypoint.

Reason: FAISS/index startup ownership is separate from HTTP framework migration and changing it could alter deployment failure modes.

Implementation action: Keep `engine/server/api/server.py` import/startup behavior and document the unchanged prerequisite if `--help` still fails in environments without FAISS.

Tests: `tests/framework/test_entrypoint_compatibility.py` accepts the known prerequisite failure.

Removal condition, if any: Dedicated Engine startup/dependency plan.

## Pydantic/OpenAPI schema redesign is deferred

Decision: Stage 10 does not introduce public Pydantic request/response schemas or OpenAPI redesign.

Reason: FastAPI/Pydantic default validation would change malformed-request status codes and response bodies.

Implementation action: Use dict/manual parsing at the FastAPI boundary and keep current service validation.

Tests: Existing malformed request tests and framework contract tests.

Removal condition, if any: Dedicated public API schema plan.
