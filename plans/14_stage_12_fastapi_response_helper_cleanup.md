# Stage 12: Remove Legacy Handler-Shaped HTTP Helpers

## Problem / Goal

Stage 10 migrated the active Client backend and Engine API HTTP services to FastAPI. Stage 11 removed the active stdlib HTTP server and handler classes, but it intentionally left a narrower compatibility layer that still looks like a `BaseHTTPRequestHandler` interface:

```text
client/backend/lib/http_utils.py
  - ResponseHandlerProtocol
  - rfile / wfile / headers protocol attributes
  - send_response / send_header / end_headers protocol methods
  - respond_json / respond_bytes / respond_options / read_json_body handler helpers

engine/server/api/http_utils.py
  - ResponseHandlerProtocol
  - rfile / wfile / headers protocol attributes
  - send_response / send_header / end_headers protocol methods
  - respond_json / respond_options / read_json_body handler helpers

engine/server/api/http_adapters.py
  - FastAPIHandlerAdapter
  - adapter_response
  - fake rfile/wfile response capture for route modules
```

That layer keeps the project working, but it is no longer the right ownership boundary. The active framework is FastAPI, so routes should return FastAPI `Response` objects or framework-neutral route result objects directly. Services should remain framework-neutral and must not become FastAPI-dependent. The goal of this stage is to finish the FastAPI HTTP-layer cleanup by removing handler-shaped response compatibility while preserving all route behavior.

This is a follow-up to the Stage 10/11 framework migration. It does not introduce a new product feature and does not change public API contracts. It removes leftover compatibility debt that Stage 11 explicitly allowed to remain.

Current behavior to preserve:

```text
Client frontend -> Client FastAPI app -> Client services/repositories -> Engine HTTP API
Client FastAPI app -> Engine read proxy responses preserve upstream status/body/content-type
Engine FastAPI app -> Engine routes/services -> Engine data/recommendation layers
```

Current leftover compatibility shape to remove:

```text
FastAPI request
  -> FastAPIHandlerAdapter
    -> handler-shaped route/service helper
      -> respond_json(handler, ...)
        -> fake send_response/send_header/wfile
          -> adapter_response(handler)
```

Target shape:

```text
FastAPI request
  -> FastAPI route adapter
    -> framework-neutral service or data helper
      -> FastAPI Response / route result built at route boundary
```


### Static cleanup policy

Stage 12 must not only remove the currently visible legacy names; it must also prevent the same fake-handler pattern from being reintroduced under a different name.

Forbidden after Stage 12 in production code and internal route/framework tests:

```text
ResponseHandlerProtocol
FastAPIHandlerAdapter
adapter_response
respond_json(handler, ...)
respond_bytes(handler, ...)
respond_options(handler)
read_json_body(handler)
rfile / wfile as project route-handler state
send_response / send_header / end_headers as project route-handler callbacks
any new object that emulates BaseHTTPRequestHandler under another name
```

Allowed after Stage 12:

```text
FastAPI Request/Response usage in app.py or route adapter modules
client/backend/http_adapters.py::read_json_body(request: Request)
engine/server/api/http_adapters.py helpers that accept raw bytes or FastAPI Request, not handler-like objects
framework-neutral RouteResult values returned by Engine route/service boundaries
test-local rfile/wfile only inside fake external HTTP servers that simulate network boundaries, not project route internals
```

The implementation must prefer deleting compatibility adapters over renaming them. A replacement adapter is only acceptable if it is FastAPI-native and does not expose handler-shaped fields or callbacks.

## Expected Behavior

After Stage 12:

- Active Client and Engine HTTP adapters are FastAPI-native.
- No production runtime code under `client/backend`, `engine/server/api`, or `tests` uses these legacy handler-shaped names:

```text
ResponseHandlerProtocol
FastAPIHandlerAdapter
adapter_response
rfile
wfile
send_response
send_header
end_headers
respond_json(handler, ...)
respond_bytes(handler, ...)
respond_options(handler)
read_json_body(handler)
```

- Client backend keeps the same executable entrypoint:

```text
python3 client/backend/server.py ...
```

- Engine API keeps the same executable entrypoint:

```text
python3 engine/server/api/server.py ...
```

- Client route behavior remains stable:

```text
GET  /api/health
GET  /api/user-profile
GET  /api/user-profile/likes
POST /api/user-action
POST /api/user-profile/reset
POST /api/user-profile/likes
POST /client/events/publish
GET  /api/video
GET  /api/channels
POST /recommendations
POST /videos/similar
OPTIONS /{path}
unknown route 404 behavior
rate-limit 429 behavior
invalid JSON 400 behavior
```

- Engine route behavior remains stable:

```text
GET  /api/health
GET  /api/channels
GET  /api/video
GET  /videos/{id}/similar
POST /recommendations
POST /videos/similar
POST /internal/videos/resolve
POST /internal/videos/metadata
POST /internal/events/ingest
OPTIONS /{path}
unknown route 404 behavior
rate-limit 429 behavior
invalid JSON 400 behavior
```

- Response bodies remain pretty-printed JSON where that is current behavior.
- CORS headers remain the same.
- Content types remain the same.
- Client read proxy still preserves upstream status, bytes, and content type.
- Recommendation rows, ordering, debug behavior, request-context cleanup, Client likes parsing, and fallback behavior remain unchanged.
- Engine `ENGINE_INGEST_MODE != bridge` still returns the current `501` response.
- Engine `server.py --help` keeps the current FAISS prerequisite behavior; this stage does not lazy-load or isolate FAISS.
- No Pydantic/OpenAPI public schema redesign is introduced.
- No service layer imports FastAPI types unless the service is explicitly an HTTP route adapter module.

Concrete preserved examples:

```text
POST /recommendations with too many likes
  -> status 400
  -> body contains current Too many likes payload
```

```text
GET /videos/{id}/similar
  -> path id is still injected into the same recommendation parameter path
```

```text
POST /internal/events/ingest when ENGINE_INGEST_MODE=off
  -> status 501
  -> body {"error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE", "mode": "off"}
```

```text
POST /api/user-action like through Client backend
  -> local Client profile write still occurs
  -> Engine resolve and ingest calls still occur through HTTP
  -> bridge partial-failure response shape remains unchanged
```

## Architecture

Stage 12 changes only the HTTP helper boundary after FastAPI migration. It must not move domain ownership between components.

### Target Client backend ownership

```text
client/backend/server.py
  -> CLI parsing, runtime construction, create_app(state), uvicorn launch

client/backend/app.py
  -> FastAPI route registration, request parsing, response construction

client/backend/http_adapters.py
  -> FastAPI-native CORS, JSON/bytes response helpers, client IP/rate-limit helpers, async request body parsing

client/backend/lib/http_utils.py
  -> non-HTTP utility helpers only, such as resolve_user_id and RateLimiter

client/backend/services/*
  -> framework-neutral user action, profile, Engine gateway, bridge publishing behavior

client/backend/repositories/*
  -> Client users DB persistence
```

Client services must not return FastAPI `Response` objects. They should keep returning existing plain result objects/tuples used by `app.py`.

### Target Engine API ownership

```text
engine/server/api/server.py
  -> CLI parsing, DB/index/runtime construction, create_app(state), uvicorn launch

engine/server/api/app.py
  -> FastAPI route registration, rate-limit gate, path/query/body adaptation, response construction

engine/server/api/http_adapters.py
  -> FastAPI-native CORS/JSON/options helpers and request-body parsing only

engine/server/api/http_utils.py
  -> non-HTTP utility helpers only, such as resolve_user_id and RateLimiter

engine/server/api/routes/*
  -> FastAPI-native route adapter functions that return Response objects or plain route result payloads consumed by app.py

engine/server/api/services/*
  -> framework-neutral orchestration and domain logic. Services must not depend on fake handler APIs or FastAPI types.

engine/server/api/services/recommendation_service.py
  -> must stop accepting handler-like objects. Parsing helpers should accept plain raw bytes, params, or decoded bodies; execution helpers should return RouteResult/plain payloads; no FastAPI imports are allowed in this service.

engine/server/api/handlers/video.py
engine/server/api/handlers/internal_client_reads.py
engine/server/api/handlers/internal_events.py
  -> either converted to framework-neutral service-style functions or replaced by route/service wrappers that return plain status/payload data.
```

### Route result boundary

Introduce a small Engine API route-result type if needed:

```python
@dataclass(frozen=True)
class RouteResult:
    status: int
    payload: dict[str, Any]
```

Rules:

- `RouteResult` is allowed because it is framework-neutral.
- `RouteResult` may contain only `status`, JSON-serializable `payload`, and optional internal fields required to preserve an existing response contract.
- `RouteResult` must not contain FastAPI `Request`, FastAPI `Response`, handler objects, file-like streams, or send callbacks.
- `RouteResult` must not become a public response schema or Pydantic model.
- FastAPI `Response` construction stays at the route/app boundary.
- Services can return `RouteResult` or plain Python data, but must not accept handler-like objects.

### Explicitly out of scope

Do not change:

```text
Client/Engine API route paths
public or internal response shapes
CORS policy
rate-limit key semantics
request-size limits
manual invalid JSON error contract
recommendation algorithm/config/output
video metadata dynamic overlay behavior
Engine data access SQL/schema
Client users DB schema
crawler code
frontend code
updater/jobs code
installer scripts
systemd/deployment runtime behavior
FAISS/index startup ownership
Pydantic/OpenAPI schemas
```

`AGENTS.md` is out of scope. Current project rules already cover this work.

## Touched Files

```text
Makefile
pyproject.toml
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/TESTING.md
docs/FRAMEWORK_COMPATIBILITY.md
docs/ENGINE_API_COMPATIBILITY.md
client/backend/app.py
client/backend/http_adapters.py
client/backend/lib/http_utils.py
client/backend/services/profile.py
client/backend/services/user_actions.py
client/backend/runtime.py
engine/server/api/app.py
engine/server/api/http_adapters.py
engine/server/api/http_utils.py
engine/server/api/handlers/internal_client_reads.py
engine/server/api/handlers/internal_events.py
engine/server/api/handlers/video.py
engine/server/api/routes/channels.py
engine/server/api/routes/health.py
engine/server/api/routes/internal_events.py
engine/server/api/routes/internal_videos.py
engine/server/api/routes/recommendations.py
engine/server/api/routes/videos.py
engine/server/api/services/channel_service.py
engine/server/api/services/recommendation_service.py
engine/server/api/services/video_service.py
engine/server/api/tests/test_recommendations_likes_limit.py
tests/client_backend/conftest.py
tests/client_backend/*.py
tests/engine_api/conftest.py
tests/engine_api/*.py
tests/framework/*.py
```

Allowed production-code edits are limited to removing handler-shaped compatibility and preserving existing behavior with FastAPI-native route boundaries.

Do not edit:

```text
AGENTS.md
client/frontend/*
engine/crawler/*
engine/server/data/*
engine/server/db/jobs/*
engine/server/db/migrations/*
install-service.sh
uninstall-service.sh
```

If a test fixture must change because it currently imitates `rfile`/`wfile`, replace it with FastAPI `TestClient`, a framework-neutral service fixture, or a `RouteResult` assertion fixture. Do not create a new fake handler abstraction.

## New Files

```text
plans/14_stage_12_fastapi_response_helper_cleanup.md
engine/server/api/route_results.py
tests/framework/test_no_legacy_handler_helpers.py
```

Optional only if it makes the implementation simpler and does not introduce FastAPI into services:

```text
engine/server/api/services/internal_video_service.py
engine/server/api/services/internal_event_service.py
```

Do not add new public API schema files or Pydantic models in this stage.

## Implementation Steps

### 1. Verify the pre-change baseline

Run from the current Stage 11 branch before production edits:

```bash
make test
make lint
python3 -m pytest tests/client_backend tests/engine_api tests/framework -q
python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit
python3 client/backend/server.py --help
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

Expected baseline:

- tests pass;
- `python3 engine/server/api/server.py --help` may still fail because FAISS is unavailable; do not change this in Stage 12.

### 2. Add a failing static guard for legacy handler-shaped helpers

Add `tests/framework/test_no_legacy_handler_helpers.py` before removing the legacy helpers.

The test must scan production and test source files under:

```text
client/backend
engine/server/api
tests/client_backend
tests/engine_api
tests/framework
```

It must fail if any of these strings remain outside explicitly allowed documentation/compatibility files:

```text
ResponseHandlerProtocol
FastAPIHandlerAdapter
adapter_response
send_response
send_header
end_headers
rfile
wfile
respond_json(handler
respond_bytes(handler
respond_options(handler
read_json_body(handler
```

Allowed files:

```text
docs/FRAMEWORK_COMPATIBILITY.md
docs/ENGINE_API_COMPATIBILITY.md
plans/14_stage_12_fastapi_response_helper_cleanup.md
```

This guard is intentionally strict. If a string remains in tests, migrate the test away from handler-shaped fixtures instead of broadening the allowlist.

### 2.1. Do not create a replacement fake-handler adapter

Before changing production code, document the forbidden pattern in the static guard test. The implementation must not replace `FastAPIHandlerAdapter` with another object that provides handler-shaped state or callbacks such as `rfile`, `wfile`, `send_response`, `send_header`, or `end_headers`.

Required action:

- If route code needs a transport-neutral boundary, use `RouteResult`.
- If route code needs HTTP response construction, build a FastAPI `Response` at the route/app boundary.
- If route code needs body parsing, pass raw bytes or decoded JSON into framework-neutral functions.
- Do not create a new compatibility object that captures response bytes and converts them back into FastAPI responses.

### 3. Shrink Client `lib/http_utils.py` to non-HTTP utilities

Change `client/backend/lib/http_utils.py` so it contains only:

```text
DEFAULT_USER_ID
resolve_user_id
RateLimiter
```

Remove from Client `lib/http_utils.py`:

```text
ResponseHandlerProtocol
_is_client_disconnect_error
_finish_response
respond_json
respond_bytes
respond_options
read_json_body
BinaryIO / Protocol imports
json import if unused
errno import if unused
```

Required action to preserve behavior:

- Keep `resolve_user_id` semantics exactly as-is.
- Keep `RateLimiter.allow()` semantics exactly as-is.
- Do not change `client/backend/http_adapters.py` response formatting unless a test proves current FastAPI route behavior needs a compatibility fix.
- Keep Client app routes importing body/response helpers from `client/backend/http_adapters.py`.

Tests that must remain green:

```bash
python3 -m pytest tests/client_backend tests/framework/test_client_fastapi_contract.py -q
```

### 4. Replace Engine handler-shaped response helpers with FastAPI-native helpers

Change `engine/server/api/http_adapters.py` into a FastAPI-native helper module.

Keep or add:

```text
CORS_HEADERS
OPTIONS_HEADERS
cors_json(status, payload)
cors_options()
read_json_body_bytes(raw: bytes, max_body_bytes=1_000_000)
```

Remove:

```text
FastAPIHandlerAdapter
adapter_response
fake rfile/wfile capture
send_response/send_header/end_headers compatibility
```

Change `engine/server/api/http_utils.py` so it contains only framework-neutral utilities:

```text
resolve_user_id
RateLimiter
```

Remove from Engine `http_utils.py`:

```text
ResponseHandlerProtocol
respond_json
respond_options
read_json_body
BinaryIO / Protocol imports
json import if unused
```

Required action to preserve behavior:

- `cors_json()` must keep `json.dumps(payload, indent=2)` formatting.
- `cors_json()` must keep `application/json; charset=utf-8` content type.
- `cors_json()` must keep current CORS headers.
- body parsing must continue to raise `ValueError("Invalid JSON body")` on invalid JSON, oversized body, non-object JSON where current routes require object payloads.
- Do not introduce FastAPI `HTTPException` for existing error paths unless tests prove it preserves status/body exactly. Preferred action: return `cors_json(status, payload)`.

### 5. Introduce a framework-neutral Engine route result where needed

Add `engine/server/api/route_results.py` with:

```python
@dataclass(frozen=True)
class RouteResult:
    status: int
    payload: dict[str, Any]
```

Rules:

- `RouteResult` must have a module docstring and class docstring.
- It must be used only to carry current status/payload behavior across route/service boundaries.
- It must not include headers, cookies, FastAPI types, Pydantic models, or response serialization logic.
- Serialization remains in `app.py` / FastAPI route adapters through `cors_json()`.

If a route can directly return `cors_json()` without making services FastAPI-dependent, `RouteResult` is not required for that route. Use it where it prevents domain/service functions from importing FastAPI.

### 6. Convert Engine route modules to return FastAPI-native responses or route results

Change route modules so they do not accept handler-like objects and do not call `respond_json(handler, ...)`.

Expected route signatures:

```python
def handle_health_route() -> RouteResult: ...
def handle_channels_route(server: Any, params: dict[str, list[str]]) -> RouteResult: ...
def handle_video_route(server: Any, params: dict[str, list[str]]) -> RouteResult: ...
def handle_internal_events_ingest_route(server: Any, body: dict[str, Any]) -> RouteResult: ...
def handle_internal_video_resolve_route(server: Any, body: dict[str, Any]) -> RouteResult: ...
def handle_internal_videos_metadata_route(server: Any, body: dict[str, Any]) -> RouteResult: ...
def handle_similar_post_route(server: Any, path: str, params: dict[str, list[str]], body: dict[str, Any]) -> RouteResult: ...
def handle_similar_get_route(server: Any, path: str, params: dict[str, list[str]]) -> RouteResult: ...
```

Allowed variation: names may differ if they are clear and documented, but they must not accept `handler`, `rfile`, `wfile`, or fake handler objects.

Required action by route:

- `routes/health.py`: return `RouteResult(200, {"ok": True, ...})` or equivalent current payload.
- `routes/channels.py`: call `parse_channel_query()` and `fetch_channel_rows()` exactly as today; return the same `generatedAt`, `total`, `rows` body.
- `routes/videos.py`: preserve delegation to current video metadata logic, but convert it to return status/payload instead of writing through handler.
- `routes/internal_events.py`: preserve the `ENGINE_INGEST_MODE` gate before ingest and return the exact existing `501` payload when disabled.
- `routes/internal_videos.py`: preserve internal resolve/metadata errors and rows.
- `routes/recommendations.py`: preserve `/videos/{id}/similar` path id extraction/injection and recommendation POST behavior.

### 7. Convert Engine handler modules that still own logic

Convert these modules away from handler mutation:

```text
engine/server/api/handlers/internal_client_reads.py
engine/server/api/handlers/internal_events.py
engine/server/api/handlers/video.py
```

Allowed paths:

1. Convert functions in place to accept already-parsed body/params and return `RouteResult`; or
2. Move logic into services and keep thin compatibility imports only if needed.

Preferred minimal path for this stage:

```text
internal_client_reads.py
  handle_internal_video_resolve(server, body) -> RouteResult
  handle_internal_videos_metadata(server, body) -> RouteResult

internal_events.py
  handle_internal_events_ingest(server, body) -> RouteResult

video.py
  handle_video_request(server, params) -> RouteResult
```

Required behavior preservation:

- Keep exact error payloads and statuses:

```text
{"error": "Invalid JSON body"}
{"error": "Missing video_id or uuid"}
{"error": "Video not found"}
{"error": "Missing entries"}
{"error": "Missing events"}
{"error": "Missing video id"}
```

- Keep DB lock usage around existing DB operations.
- Keep dynamic video metadata update behavior and logging.
- Keep metadata response shape for Client profile likes and frontend video page.
- Do not change SQL queries, error thresholds, dynamic metadata parsing, or popularity update formula.

### 8. Convert recommendation route/service boundary

`engine/server/api/services/recommendation_service.py` is the largest remaining handler-shaped area. Convert only the HTTP boundary parts required to remove fake handler compatibility.

Required changes:

- `handle_similar_request()` must accept parsed `body` for POST instead of reading from `handler.rfile`.
- `handle_similar()` and helper response functions must return `RouteResult` instead of calling `respond_json(handler, ...)`.
- `respond_rows()` should become a pure builder such as:

```python
def build_rows_response(...) -> RouteResult:
    ...
```

- Error paths must return the same status/payload currently produced by `respond_json()`.
- Request context setup/cleanup must remain identical.
- Client likes body-size validation must remain at the FastAPI route boundary using raw body length from `request.body()` before JSON parsing.
- `_recommendations_likes_payload_error()` behavior must not change.
- Debug disabled behavior must remain `403` with the same payload.

Do not change:

```text
stable row fields
INCLUDE_DYNAMIC_STATS behavior
candidate ordering
score/mixer logic
fallback random behavior
rerank behavior
debug attachment behavior
MAX_LIKES behavior
DEFAULT_CLIENT_LIKES_MAX behavior
DEFAULT_CLIENT_LIKES_BODY_LIMIT behavior
```

### 9. Update `engine/server/api/app.py` to call FastAPI-native routes

Remove all `FastAPIHandlerAdapter` usage from `engine/server/api/app.py`.

For each route:

1. Apply rate-limit gate exactly as today.
2. Parse raw body with `await request.body()` where needed.
3. Enforce body size before JSON parse for recommendations POST.
4. Parse JSON through the new FastAPI-native helper.
5. Call route/service functions with `state`, `params`, and `body`.
6. Convert `RouteResult` to `cors_json(result.status, result.payload)`.

The app must continue to return:

```text
OPTIONS -> 204 with CORS headers
unknown GET/POST -> 404 {"error": "Not found"}
rate limited -> 429 {"error": "Rate limit exceeded"}
```

### 10. Update tests away from fake handler fixtures

Remove handler-like fixtures from:

```text
tests/engine_api/conftest.py
engine/server/api/tests/test_recommendations_likes_limit.py
tests/engine_api/*
tests/framework/*
```

Required actions:

- Engine route tests should use FastAPI `TestClient` when verifying HTTP behavior.
- Service-level tests should assert `RouteResult.status` and `RouteResult.payload`.
- No test may create fake `.rfile`, `.wfile`, `.send_response`, `.send_header`, or `.end_headers` objects.
- Existing Client fake HTTP server in `tests/client_backend/conftest.py` is allowed to keep socket-level `rfile`/`wfile` only if it is a fake upstream Engine server, not a fake internal route handler. If the static guard includes tests/client_backend, allow this file only for the fake network boundary or rewrite the fake server to a simpler HTTP server library pattern without matching banned strings. Preferred action: allow only this fake network-boundary file with an explanatory comment in the static guard.

### 11. Update compatibility documentation

Update `docs/FRAMEWORK_COMPATIBILITY.md`:

- Add a section explaining that handler-shaped helper compatibility was removed.
- Record that active FastAPI routes now return FastAPI `Response` objects or route results directly.
- Record that `server.py` entrypoints remain compatibility contracts.
- Record that no public route/schema behavior changed.
- Do not document `ResponseHandlerProtocol`, `FastAPIHandlerAdapter`, or fake handler response capture as continuing compatibility decisions; they must be documented as removed.

Update `docs/ENGINE_API_COMPATIBILITY.md`:

- Replace references to handler-shaped route adapters with FastAPI-native route adapters.
- Keep existing Engine route compatibility decisions intact.
- Add removal note for `FastAPIHandlerAdapter` and `ResponseHandlerProtocol`.

Update `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`, and `docs/TESTING.md` only where they still describe active legacy handler-shaped helpers.

Each compatibility entry must include:

```text
Decision:
Reason:
Implementation action:
Tests:
Removal condition, if any:
```

### 12. Update lint/test command surfaces if needed

If new files are added, update:

```text
Makefile
pyproject.toml
```

Required action:

- Include `tests/framework/test_no_legacy_handler_helpers.py` in the normal `make test` path through existing pytest discovery.
- Include new Stage 12 maintained files in `make lint` only if the current lint policy requires explicit file lists.
- Do not add Node/frontend/crawler tests to `make test-fast`.

### 13. Final static verification

Run a source-only grep after implementation:

```bash
grep -R "ResponseHandlerProtocol\|FastAPIHandlerAdapter\|adapter_response\|send_response\|send_header\|end_headers\|respond_json(handler\|respond_bytes(handler\|respond_options(handler\|read_json_body(handler" \
  client/backend engine/server/api tests \
  --exclude-dir='__pycache__' \
  --exclude='*.pyc'
```

Expected result:

- no production matches;
- no internal route/service test matches;
- any allowed fake external HTTP server match must be documented in `tests/framework/test_no_legacy_handler_helpers.py` with a concrete reason and a removal condition.

Also run:

```bash
grep -R "\.rfile\|\.wfile" engine/server/api tests/engine_api tests/framework --exclude-dir='__pycache__'
```

Expected result: no matches.

## Acceptance Criteria

Stage 12 is complete only when all of the following are true:

- `ResponseHandlerProtocol`, `FastAPIHandlerAdapter`, and `adapter_response` are absent from production code and internal route/framework tests.
- No Engine route, Engine service, or Engine route test uses fake `rfile`/`wfile` objects or `send_response`/`send_header`/`end_headers` callbacks.
- `engine/server/api/services/recommendation_service.py` no longer accepts handler-like objects and does not import FastAPI.
- `engine/server/api/handlers/internal_client_reads.py`, `engine/server/api/handlers/internal_events.py`, and `engine/server/api/handlers/video.py` either return `RouteResult`/plain data or delegate to functions that do; they do not mutate handler objects.
- `client/backend/lib/http_utils.py` contains only non-response utilities.
- Static guard tests fail if a new handler-emulating adapter is introduced.
- Compatibility docs state that handler-shaped HTTP compatibility was removed, not preserved.
- Public route behavior remains covered by existing Client, Engine, and framework tests.

## Tests

Required checks after implementation:

```bash
make test
make lint
python3 -m pytest tests/framework -q
python3 -m pytest tests/engine_api -q
python3 -m pytest tests/client_backend -q
python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit
python3 client/backend/server.py --help
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

Known prerequisite-sensitive check:

```bash
python3 engine/server/api/server.py --help
```

Expected behavior:

- unchanged FAISS prerequisite failure is allowed;
- any different failure is a Stage 12 regression.

Required source checks:

```bash
grep -R "ResponseHandlerProtocol\|FastAPIHandlerAdapter\|adapter_response\|send_response\|send_header\|end_headers" client/backend engine/server/api tests --exclude-dir='__pycache__'

grep -R "respond_json(handler\|respond_bytes(handler\|respond_options(handler\|read_json_body(handler" client/backend engine/server/api tests --exclude-dir='__pycache__'
```

Expected result:

- no matches except explicitly allowed documentation/plans;
- no production code matches.

## Documentation Maintenance

Documentation updates are required in this stage because HTTP framework ownership changes again.

Read and update only relevant sections in:

```text
docs/FRAMEWORK_COMPATIBILITY.md
docs/ENGINE_API_COMPATIBILITY.md
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/TESTING.md
```

Do not edit unrelated compatibility documents:

```text
docs/RECOMMENDATION_COMPATIBILITY.md
docs/CRAWLER_COMPATIBILITY.md
docs/FRONTEND_COMPATIBILITY.md
docs/UPDATER_COMPATIBILITY.md
docs/SCHEMA_OWNERSHIP.md
```

Do not edit `AGENTS.md`.

## Regression and Blind-Spot Analysis

### Risk: route status/body changes while removing `respond_json(handler, ...)`

Action: introduce `RouteResult` and convert `RouteResult` to `cors_json()` with the same `json.dumps(..., indent=2)`, content type, and CORS headers. Keep route characterization tests and framework contract tests green.

### Risk: FastAPI/Pydantic default validation leaks into public contracts

Action: continue reading raw bytes manually and returning `cors_json(400, {"error": "Invalid JSON body"})` for current invalid-body cases. Do not add Pydantic request models or `HTTPException` for existing route validation paths.

### Risk: recommendation request body-size validation moves after JSON parsing

Action: in `app.py`, check raw body length before calling JSON parsing for recommendation POST routes. Keep tests for oversized body and malformed likes payloads.

### Risk: request-context cleanup changes during recommendation refactor

Action: keep `set_request_client_likes()` before recommendation execution and `clear_request_context()` in `finally` paths. Add or preserve tests that fail if context survives after recommendation errors.

### Risk: dynamic video metadata update behavior changes

Action: move only the response-writing boundary. Keep `fetch_video_row()`, `fetch_instance_video_dynamic()`, popularity recomputation, DB update SQL, and logging behavior unchanged. Existing video metadata characterization tests must remain green.

### Risk: internal video metadata/resolve error behavior changes

Action: convert `handle_internal_video_resolve()` and `handle_internal_videos_metadata()` to return `RouteResult` with the exact same status/payload decisions. Do not change `fetch_seed_embedding()` or `fetch_metadata_by_ids()` calls.

### Risk: internal events ingest dedup/signals behavior changes

Action: parse body before calling the ingest service, then keep the exact loop around `ingest_interaction_event()` and DB lock usage. Existing interaction ingest tests and `tests/repositories/test_engine_interaction_events.py` must remain green.

### Risk: tests pass by using a new fake handler abstraction

Action: add a strict static guard that rejects handler-shaped names in tests. Use FastAPI `TestClient` or `RouteResult` assertions instead.

### Risk: Client fake upstream Engine test server is mistaken for internal legacy handler compatibility

Action: the static guard may allow `tests/client_backend/conftest.py` only for the fake external network boundary. The allowlist entry must explain that this file simulates an upstream HTTP server, not project route internals.

### Risk: Client `lib/http_utils.py` still hides legacy response helpers

Action: shrink the file to `DEFAULT_USER_ID`, `resolve_user_id`, and `RateLimiter`; ensure all response/body helpers are imported from `client/backend/http_adapters.py` instead.

### Risk: Engine helper cleanup touches unrelated data/recommendation logic

Action: do not edit `engine/server/data/*`, `engine/server/api/recommendations/*`, or DB/schema files. If a behavior requires those edits, it is out of scope for Stage 12.

### Risk: docs imply all compatibility debt is gone

Action: document precisely that handler-shaped HTTP compatibility is removed. Do not claim that all compatibility shims in the project are gone; server.py entrypoint compatibility and other documented compatibility decisions remain.

## Compatibility Decisions To Record

Update `docs/FRAMEWORK_COMPATIBILITY.md` with these entries:

### Handler-shaped HTTP compatibility removed

Decision: `ResponseHandlerProtocol`, `FastAPIHandlerAdapter`, fake `rfile`/`wfile`, and fake `send_response`/`send_header`/`end_headers` compatibility are removed from production and internal route tests.

Reason: FastAPI is now the active HTTP adapter model. Keeping fake handler-shaped helpers after Stage 11 creates duplicate HTTP ownership and obscures route responsibilities.

Implementation action: Convert Engine routes and remaining helper modules to return FastAPI `Response` objects or framework-neutral `RouteResult` values.

Tests: `tests/framework/test_no_legacy_handler_helpers.py`, `tests/framework/*`, `tests/engine_api/*`, `tests/client_backend/*`.

Removal condition, if any: Complete in this stage.

### Services remain framework-neutral

Decision: Domain/service modules do not import FastAPI types as part of the cleanup.

Reason: FastAPI is the transport adapter, not the project domain model.

Implementation action: Use `RouteResult` or plain Python data for service/route boundaries; build FastAPI `Response` objects in app/route adapter modules.

Tests: static grep in `tests/framework/test_no_legacy_handler_helpers.py` plus existing service tests.

Removal condition, if any: None.

### server.py executable compatibility remains

Decision: `client/backend/server.py` and `engine/server/api/server.py` remain executable compatibility launchers.

Reason: Installers, docs, smoke checks, and developer commands may call these paths directly.

Implementation action: Do not rename or remove these files while cleaning up handler-shaped internals.

Tests: `tests/framework/test_entrypoint_compatibility.py`.

Removal condition, if any: None in this stage.

## Non-Negotiable Implementation Constraints

Constraint: Do not change route contracts.

Required action: If converting a route requires changing a status code, response key, JSON formatting, or CORS header, keep the old behavior and express it through `RouteResult`/`cors_json()` instead of changing the contract.

Constraint: Do not move FastAPI into services.

Required action: If a service would need `Request`, `Response`, `HTTPException`, or `fastapi.*`, introduce or reuse a framework-neutral result type and keep FastAPI imports in `app.py` or route adapter modules only.

Constraint: Do not edit DB/data/recommendation algorithm files.

Required action: Preserve function calls into existing data/recommendation modules. If logic movement would require changing those modules, leave that logic in its current module and only remove handler-shaped response writing around it.

Constraint: Do not edit AGENTS.md.

Required action: Current project rules already cover this plan. Keep rule changes out of Stage 12.

Constraint: Do not change FAISS/startup behavior.

Required action: Leave `engine/server/api/server.py --help` prerequisite behavior unchanged and record any known failure as unchanged.

Constraint: Do not add broad compatibility-document claims.

Required action: Document only the handler-shaped HTTP compatibility removed in Stage 12 and the compatibility decisions preserved by this cleanup.

## Open Questions

None for the current Stage 12 scope.
