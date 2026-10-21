# Stage 10: FastAPI Migration With Compatibility Wrappers

## Problem / Goal

The project has already split the major product responsibilities while preserving behavior:

```text
Stage 3: Client backend behavior lives in services/repositories; server.py is the stdlib HTTP adapter.
Stage 4: Engine API behavior lives in routes/services; SimilarHandler is the stdlib HTTP adapter.
Stage 5: Recommendation internals/config/types are explicit without behavior changes.
Stage 6: DB schema ownership is documented and current-shape migration resources exist.
Stage 7: Crawler DB responsibilities are split while db.ts remains a compatibility facade.
Stage 8: Frontend page responsibilities are split while Client API calls remain stable.
Stage 9: Updater/job orchestration is split while updater-worker.py remains the executable entrypoint.
```

Stage 10 is the only stage where HTTP framework migration is in scope. The goal is to introduce FastAPI/uvicorn for both HTTP services while preserving existing route contracts, CLI entrypoint paths, installer-facing commands, CORS behavior, rate-limit behavior, request-size errors, invalid JSON errors, status codes, and response payloads.

This stage must not change product behavior. It must not rewrite recommendation logic, Client profile logic, Engine data access, crawler behavior, job orchestration, schema ownership, frontend API calls, or deployment topology.

The migration target is compatibility-first:

```text
python3 client/backend/server.py ...    # still works
python3 engine/server/api/server.py ... # still works, with the same FAISS/runtime prerequisites
Frontend -> Client backend              # unchanged
Client backend -> Engine HTTP API       # unchanged
```

## Expected Behavior

After Stage 10:

- `client/backend/server.py` remains the executable Client backend entrypoint.
- `engine/server/api/server.py` remains the executable Engine API entrypoint.
- Both entrypoints run FastAPI/uvicorn or delegate to FastAPI app factories while preserving their current CLI options.
- Frontend routes, localStorage behavior, and API payloads do not change.
- Client backend continues to talk to Engine over HTTP and does not import Engine internals.
- Engine startup still loads the same DB, similarity cache, random cache, ANN/FAISS index, recommendation strategy, flags, locks, and rate limiter.
- Existing Stage 0-9 tests remain green.
- Existing smoke/installer scripts may keep invoking the same `server.py` paths.

Client routes that must remain compatible:

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
```

Engine routes that must remain compatible:

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
```

Concrete compatibility examples:

```text
/videos/{id}/similar:
  FastAPI path handling must inject the path id into the same id parameter used today.

/internal/events/ingest:
  ENGINE_INGEST_MODE != bridge must still return the current 501 response body.

Client read proxy:
  Unknown query/body fields, upstream byte preservation, content type, status forwarding, and 502 failures must match current behavior.

Client /api/user-action:
  Local profile persistence and bridge partial-failure semantics must match current behavior.
```

## Architecture

Stage 10 changes only the HTTP framework adapter layer.

Target structure:

```text
client/backend/server.py          # compatibility CLI entrypoint, runs uvicorn/FastAPI
client/backend/app.py             # FastAPI app factory and route registration
client/backend/runtime.py         # Client runtime state currently carried by ClientBackendServer
client/backend/http_adapters.py   # response/body/client-ip compatibility helpers
client/backend/services/*         # unchanged behavior ownership
client/backend/repositories/*     # unchanged persistence ownership

engine/server/api/server.py       # compatibility CLI entrypoint, preserves startup wiring, runs uvicorn/FastAPI
engine/server/api/app.py          # FastAPI app factory and route registration
engine/server/api/runtime.py      # Engine runtime state currently carried by SimilarServer
engine/server/api/http_adapters.py# response/body/client-ip compatibility helpers
engine/server/api/routes/*        # unchanged route ownership where reusable
engine/server/api/services/*      # unchanged orchestration ownership
engine/server/data/*              # unchanged data ownership
```

### Client FastAPI responsibility

Responsible for:

- Current Client HTTP route registration.
- Translating FastAPI `Request` objects into existing service inputs.
- Applying current rate-limit keys.
- Preserving CORS, JSON errors, byte responses, and status codes.

Not responsible for:

- Engine DB reads.
- Recommendation ranking.
- Browser UI state.
- Crawler/job orchestration.
- New public schemas or OpenAPI redesign.

### Engine FastAPI responsibility

Responsible for:

- Current Engine HTTP route registration.
- Translating FastAPI requests into existing Engine route/service inputs.
- Preserving startup state and route contracts.
- Applying current rate-limit keys.

Not responsible for:

- Recommendation behavior changes.
- DB schema/data access changes.
- ANN/FAISS/index loading redesign.
- Client profile persistence.
- Crawler/job behavior.

### Remaining stdlib ownership after Stage 10

`BaseHTTPRequestHandler` adapters must not remain the active route owners after Stage 10. If retained, they must be moved to explicitly named temporary compatibility modules and used only for old-vs-new contract comparison or rollback documentation. The executable `server.py` paths remain, but they should become compatibility launchers rather than stdlib route handlers.

## Touched Files

```text
Makefile
README.md
client/README.md
client/backend/server.py
client/backend/schemas.py
client/backend/lib/http_utils.py
client/backend/services/bridge_publisher.py
client/backend/services/engine_gateway.py
client/backend/services/profile.py
client/backend/services/user_actions.py
docs/ARCHITECTURE.md
docs/DEPLOYMENT.md
docs/DEVELOPMENT.md
docs/TESTING.md
engine/server/README.md
engine/server/requirements-dev.txt
engine/server/requirements.txt
engine/server/api/server.py
engine/server/api/handlers/similar.py
engine/server/api/http_utils.py
engine/server/api/routes/channels.py
engine/server/api/routes/health.py
engine/server/api/routes/internal_events.py
engine/server/api/routes/internal_videos.py
engine/server/api/routes/recommendations.py
engine/server/api/routes/videos.py
engine/server/api/services/channel_service.py
engine/server/api/services/recommendation_service.py
engine/server/api/services/video_service.py
pyproject.toml
tests/client_backend/*.py
tests/engine_api/*.py
tests/contracts/*.py
tests/run-arch-split-smoke.sh
tests/run-installers-smoke.sh
```

Do not edit these areas in Stage 10 except documentation references that explicitly describe framework migration impact:

```text
AGENTS.md
client/frontend/src/*
engine/crawler/src/*
engine/crawler/schema.sql
engine/server/data/*
engine/server/db/jobs/*
engine/server/db/migrations/*
engine/server/api/recommendations/*
```

## New Files

```text
plans/12_stage_10_fastapi_migration.md
docs/FRAMEWORK_COMPATIBILITY.md
client/backend/app.py
client/backend/runtime.py
client/backend/http_adapters.py
engine/server/api/app.py
engine/server/api/runtime.py
engine/server/api/http_adapters.py
tests/framework/test_client_fastapi_contract.py
tests/framework/test_engine_fastapi_contract.py
tests/framework/test_entrypoint_compatibility.py
tests/framework/test_framework_compatibility_documentation.py
```

Optional temporary files only if old-vs-new comparison requires preserving the stdlib adapters during implementation:

```text
client/backend/legacy_http.py
engine/server/api/legacy_http.py
```

If these are created, `docs/FRAMEWORK_COMPATIBILITY.md` must mark them temporary and state the removal condition.

## Implementation Steps

### 1. Confirm baseline before framework changes

Run:

```bash
make test
make lint
python3 client/backend/server.py --help
python3 engine/server/api/server.py --help
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

Expected action:

- Record any pre-existing FAISS failure for `engine/server/api/server.py --help` as an unchanged runtime prerequisite.
- Do not lazy-load or isolate FAISS in Stage 10.

### 2. Add framework dependencies

Add:

```text
fastapi
uvicorn
httpx
```

Implementation action:

- Add the dependencies to `engine/server/requirements-dev.txt` for tests.
- Add `fastapi` and `uvicorn` to `engine/server/requirements.txt` if `server.py` entrypoints switch to uvicorn in this stage.
- Do not perform a broader dependency split in Stage 10.

### 3. Add Client runtime state

Create `client/backend/runtime.py` with a state object carrying the dependencies currently stored on `ClientBackendServer`:

```python
@dataclass
class ClientRuntimeState:
    user_db: sqlite3.Connection
    users: UsersRepository
    engine_ingest_base: str
    publish_mode: str
    rate_limiter: RateLimiter
```

Implementation action:

- Build it from the same DB connection, `UsersRepository`, publish-mode normalization, and `RateLimiter` constants currently used by `server.py`.
- Do not change Client default host/port, DB path, max-likes values, proxy timeouts, retries, or rate-limit constants.

### 4. Add Client FastAPI app

Create `client/backend/app.py` with:

```python
def create_app(state: ClientRuntimeState) -> FastAPI:
    ...
```

Routes must call existing services:

```text
/api/user-profile           -> services.profile.get_user_profile
/api/user-profile/likes     -> services.profile.get_profile_likes_metadata
/api/user-action            -> services.user_actions.handle_user_action
/api/user-profile/reset     -> services.profile.reset_user_profile
/api/user-profile/likes     -> services.profile.get_client_likes_metadata
/client/events/publish      -> services.bridge_publisher.publish_event
proxy read routes           -> services.engine_gateway.proxy_engine_request
```

Implementation action:

- Preserve current client-IP resolution order: `X-Forwarded-For`, `X-Real-IP`, client host fallback.
- Preserve current rate-limit key: `client_ip:path`.
- Preserve CORS headers and OPTIONS behavior.
- Preserve current read-json size limits and invalid JSON error bodies.
- Preserve upstream proxy bytes through FastAPI `Response` objects.
- Do not introduce Pydantic request/response models in Stage 10.

### 5. Add Engine runtime state

Create `engine/server/api/runtime.py` with an `EngineRuntimeState` object that carries the attributes currently stored on `SimilarServer`.

Minimum fields:

```text
db
similarity_db
random_cache_db
index
embeddings_dim
embeddings_count
default_limit
normalize_queries
refresh_similarity_cache
similarity_require_full_cache
similarity_allow_ann_on_cache_miss
similarity_search_limit
similarity_max_per_author
similarity_exclude_source_author
recommendation_strategy
related_personalization_deps
related_personalization_enabled
video_error_threshold
recommendations_debug_enabled
use_client_likes
rate_limiter
popularity_like_weight
enable_instance_ignore
enable_channel_blocklist
engine_ingest_mode
index_lock
db_lock
similarity_db_lock
random_cache_lock
```

Implementation action:

- Preserve the exact runtime attribute names used by `routes/*`, `services/*`, and `handlers/*` wrappers.
- Do not change Engine startup loading order or resource creation.

### 6. Add Engine FastAPI app

Create `engine/server/api/app.py` with:

```python
def create_app(state: EngineRuntimeState) -> FastAPI:
    ...
```

Routes must preserve current behavior:

```text
GET  /api/health                  -> same health payload
GET  /api/channels                -> same channel query parsing and response shape
GET  /api/video                   -> same video metadata handler behavior
GET  /videos/{id}/similar         -> same path-id injection and recommendation response
POST /recommendations             -> same request parsing, likes validation, debug gate, response shape
POST /videos/similar              -> same behavior as current route
POST /internal/videos/resolve     -> same internal resolve behavior
POST /internal/videos/metadata    -> same metadata batch behavior
POST /internal/events/ingest      -> same ingest-mode gate and ingest behavior
```

Implementation action:

- Preserve current Engine rate-limit behavior: `GET /api/*` rate-limited by exact path, `GET /videos/{id}/similar` rate-limited by the request path, and recommendation POST routes rate-limited by exact route path.
- Preserve request context cleanup behavior around recommendation execution.
- Preserve CORS and OPTIONS behavior.
- Preserve `debug=false`/debug-disabled behavior and status codes.
- Do not modify `engine/server/api/recommendations/*` or `engine/server/data/*` to make FastAPI easier.

### 7. Convert entrypoint wrappers without changing command paths

Update `client/backend/server.py` and `engine/server/api/server.py` so the existing file paths remain executable.

Implementation action:

- `parse_args()` behavior must remain compatible.
- `--help` output must still expose existing options.
- Client `server.py` must create `ClientRuntimeState`, create the FastAPI app, and run uvicorn on the requested host/port.
- Engine `server.py` must preserve its current startup flow, create `EngineRuntimeState`, create the FastAPI app, and run uvicorn on the requested host/port.
- Signal/lifecycle logging must remain equivalent enough for existing operational docs and smoke tests.
- Installer scripts must not be edited unless they fail because of the uvicorn transition; if edited, the edit must preserve command paths and be documented.

### 8. Add framework compatibility documentation

Create `docs/FRAMEWORK_COMPATIBILITY.md`.

Every Stage 10 compatibility decision must use this shape:

```text
Decision:
Reason:
Implementation action:
Tests:
Removal condition, if any:
```

Required entries:

```text
server.py entrypoint paths remain stable
CORS and OPTIONS behavior is preserved
rate-limit keys are preserved
request-size and invalid JSON errors are preserved
Client read proxy byte/status/content-type preservation is preserved
/videos/{id}/similar path-id injection is preserved
/internal/events/ingest mode gate is preserved
FAISS startup prerequisite is unchanged
Pydantic/OpenAPI schema redesign is deferred
```

### 9. Add tests before switching active entrypoints

Add `tests/framework` and include it in `pyproject.toml` pytest discovery.

Required tests:

```text
tests/framework/test_client_fastapi_contract.py
tests/framework/test_engine_fastapi_contract.py
tests/framework/test_entrypoint_compatibility.py
tests/framework/test_framework_compatibility_documentation.py
```

Client FastAPI tests must cover:

- `/api/health` payload.
- `/api/user-profile` payload and local DB effect.
- `/api/user-action` like behavior with fake Engine endpoints.
- bridge failure partial-failure behavior.
- `/api/user-profile/reset` behavior.
- Client read proxy GET/POST allowlist and failure behavior.
- CORS OPTIONS behavior.
- rate-limit behavior.

Engine FastAPI tests must cover:

- `/api/health` payload.
- `/api/channels` defaults and cap behavior.
- `/api/video` delegation behavior.
- `/videos/{id}/similar` path-id injection.
- `/recommendations` malformed/oversized likes behavior.
- `/internal/videos/resolve` and `/internal/videos/metadata` behavior.
- `/internal/events/ingest` disabled-mode 501 and enabled delegation.
- CORS OPTIONS behavior.
- rate-limit behavior.

Entry-point tests must cover:

- `python3 client/backend/server.py --help`.
- `python3 engine/server/api/server.py --help` expected behavior, including unchanged FAISS prerequisite if that import path still blocks help in the current environment.
- Existing `server.py` file paths remain present.

### 10. Update tooling and docs

Update `Makefile`:

```text
test-framework -> python3 -m pytest tests/framework -q
```

Add `tests/framework` to `pyproject.toml` testpaths.

Update docs:

```text
docs/ARCHITECTURE.md      -> HTTP framework ownership and unchanged component boundaries
docs/DEVELOPMENT.md       -> FastAPI/uvicorn local run notes
docs/TESTING.md           -> test-framework and framework prerequisites
docs/DEPLOYMENT.md        -> server.py path compatibility and uvicorn runtime note
README.md                 -> high-level note only if command examples mention server startup
client/README.md          -> Client backend startup note
engine/server/README.md   -> Engine API startup note
```

Do not edit `AGENTS.md` in Stage 10.

### 11. Verify final behavior

Run:

```bash
make test
make lint
make test-framework
python3 client/backend/server.py --help
python3 engine/server/api/server.py --help
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

Prerequisite-sensitive checks:

```bash
bash tests/run-arch-split-smoke.sh
bash tests/run-installers-smoke.sh --dry-run-only
```

Run them when the environment has required runtime artifacts and dependencies. If they fail because of missing FAISS/index/DB/systemd prerequisites, document that exactly in the final implementation summary.

## Tests

Stage 10 must use the existing Stage 0-9 test suite plus new FastAPI adapter tests.

Required always:

```bash
make test
make lint
make test-framework
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

Required new tests:

```text
tests/framework/test_client_fastapi_contract.py
tests/framework/test_engine_fastapi_contract.py
tests/framework/test_entrypoint_compatibility.py
tests/framework/test_framework_compatibility_documentation.py
```

Test design rules:

- Use FastAPI TestClient for ASGI route behavior.
- Use temporary SQLite DBs for Client profile state.
- Use fake Engine HTTP endpoints for Client gateway and bridge behavior.
- Use fake Engine runtime state objects for Engine route tests.
- Mock only network, time/random IDs, and heavyweight optional dependencies.
- Do not replace existing Stage 0-9 characterization tests.

## Documentation Maintenance

Before editing docs, read the first paragraph/purpose of the target document.

Documentation ownership:

```text
docs/FRAMEWORK_COMPATIBILITY.md
  Required Stage 10 compatibility decisions and removal conditions.

docs/ARCHITECTURE.md
  Component ownership and HTTP adapter/framework boundary.

docs/DEVELOPMENT.md
  Local FastAPI/uvicorn development commands and dependencies.

docs/TESTING.md
  Framework test target and prerequisite-sensitive checks.

docs/DEPLOYMENT.md
  Runtime command compatibility and uvicorn process note.

README.md, client/README.md, engine/server/README.md
  Only concise startup-command updates if existing examples become inaccurate.
```

Do not put framework-migration details into crawler, recommendation, schema, or updater compatibility documents unless Stage 10 directly changes those documented contracts. It should not.

## Compatibility Decisions Required

`docs/FRAMEWORK_COMPATIBILITY.md` must include these entries:

### `server.py` entrypoint paths remain stable

Decision: Keep existing executable paths as compatibility launchers.
Reason: Installer scripts, smoke scripts, and docs may invoke those files directly.
Implementation action: Convert internals to uvicorn/FastAPI without moving or deleting the file paths.
Tests: `test_entrypoint_compatibility.py`, installer dry-run smoke when available.
Removal condition: None in Stage 10.

### CORS and OPTIONS behavior is preserved

Decision: FastAPI must emit current CORS headers and preflight status behavior.
Reason: Frontend and reverse-proxy behavior depends on permissive local API headers.
Implementation action: Add explicit middleware/helper responses that match existing `respond_options` and response helpers.
Tests: Client and Engine framework contract tests for OPTIONS.
Removal condition: Only a future API/security plan can change CORS policy.

### Rate-limit keys are preserved

Decision: Keep existing `client_ip:path` rate-limit keys.
Reason: Changing keys changes observable throttling behavior.
Implementation action: Implement shared client-IP resolution and rate-limit dependency/helper in `http_adapters.py`.
Tests: Client and Engine rate-limit framework tests.
Removal condition: Only a future rate-limit policy plan can change this.

### Request-size and invalid JSON errors are preserved

Decision: FastAPI body parsing must not introduce new 422/Pydantic errors for existing routes.
Reason: Current clients and tests expect explicit 400/413-style compatibility bodies.
Implementation action: Read bytes manually where current handlers do, then call existing JSON parsing helpers or equivalent compatibility helpers.
Tests: recommendation request contract tests and Client proxy/action invalid JSON tests.
Removal condition: Only a future public API schema plan can change this.

### Pydantic/OpenAPI schema redesign is deferred

Decision: Do not introduce public Pydantic request/response schemas in Stage 10.
Reason: Pydantic would change default validation errors and OpenAPI-visible contracts.
Implementation action: Use dict/manual parsing at the FastAPI boundary and keep current service validation.
Tests: malformed request tests continue to assert old bodies/status codes.
Removal condition: Dedicated public API schema plan.

## Non-negotiable Implementation Constraints

Constraint: Framework migration must not change public route paths.
Required action: Register the same paths and methods listed in `Expected Behavior`; do not add redirects or renamed endpoints.

Constraint: Framework migration must not change response shapes or status codes.
Required action: Add FastAPI contract tests before replacing entrypoints and make app routes return explicit `JSONResponse`/`Response` objects with current bodies/statuses.

Constraint: Framework migration must not change Engine startup or FAISS loading.
Required action: Keep Engine startup resource creation in `server.py`; only wrap the created state in `EngineRuntimeState` before launching uvicorn.

Constraint: Framework migration must not change Client/Engine boundary.
Required action: Client FastAPI routes must use `services.engine_gateway` over HTTP and must not import Engine modules.

Constraint: Framework migration must not change Client profile DB behavior.
Required action: Reuse `UsersRepository` and profile/user-action services; assert SQLite effects with existing and new tests.

Constraint: Framework migration must not change recommendation behavior.
Required action: Reuse Stage 4 route/service behavior and Stage 5 recommendation internals without editing `engine/server/api/recommendations/*`.

Constraint: Framework migration must not change schema, crawler, jobs, or frontend internals.
Required action: Do not edit those directories except documentation references that mention the HTTP framework change.

Constraint: FastAPI default validation must not leak into current APIs.
Required action: Avoid route models for request bodies in Stage 10 and manually parse bytes to preserve current errors.

Constraint: Legacy stdlib code must not remain an undocumented second runtime.
Required action: Either remove it after FastAPI contracts pass or move it to temporary `legacy_http.py` files documented in `docs/FRAMEWORK_COMPATIBILITY.md` with a removal condition.

## Regression and Blind-Spot Analysis

Risk: FastAPI may return 422 validation errors instead of current JSON error bodies.
Action: Do not use Pydantic body models; parse request bytes manually and assert malformed body tests.

Risk: CORS headers may differ from current helper responses.
Action: Add explicit CORS compatibility middleware/helper and test OPTIONS plus normal responses.

Risk: Rate-limit behavior may change because FastAPI exposes client IP differently.
Action: Implement current forwarded-header resolution order and assert limiter keys in tests.

Risk: Proxy byte responses may become JSON-normalized.
Action: Return FastAPI `Response` with original bytes/content-type/status for `ProxyBytesResult`.

Risk: Engine route services still expect handler-like response helpers.
Action: Add FastAPI adapter helpers that call the same underlying services or expose small handler-compatible shims without changing service behavior.

Risk: `server.py --help` behavior may change when uvicorn is introduced.
Action: Keep existing `argparse` parsing and test help commands.

Risk: Installer scripts may assume direct `python server.py` execution.
Action: Preserve file paths and command-line flags; run installer dry-run smoke when prerequisites allow.

Risk: Engine FAISS import/startup remains heavy.
Action: Do not fix this in Stage 10; document unchanged prerequisite and test FastAPI app factories through fake runtime state.

Risk: OpenAPI output may imply stable public schemas that are not intentionally designed.
Action: Do not document generated OpenAPI as public contract in Stage 10; state schema redesign is deferred.

Blind spot: Exact stdlib-vs-FastAPI response header ordering may differ.
Action: Tests must assert semantic headers and bodies required by clients, not raw header order.

Blind spot: Full production smoke may require real DB/index artifacts not available locally.
Action: Keep smoke checks prerequisite-sensitive and document exact missing prerequisites in the implementation summary.

## Generic vs Project-Specific Behavior

Generic behavior:

- FastAPI is a Python ASGI framework.
- Uvicorn is an ASGI server.
- Framework migration should be protected by route contract tests before switching entrypoints.

Project-specific behavior:

- Frontend must call Client backend only.
- Client backend must call Engine over HTTP only.
- Engine owns recommendation, metadata, and internal ingest behavior.
- Existing `server.py` entrypoints are compatibility paths for docs, installers, and smoke scripts.
- Recommendation request/response behavior is a product contract, not a FastAPI schema redesign.
- FAISS startup requirements remain part of Engine runtime behavior in this stage.

## Open Questions

None for the current Stage 10 scope.
