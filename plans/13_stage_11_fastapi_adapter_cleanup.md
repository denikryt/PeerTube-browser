# Stage 11: Finalize FastAPI Adapter Ownership

## Problem / Goal

Stage 10 migrated the active Client backend and Engine API HTTP services to
FastAPI while preserving the existing `server.py` executable paths and route
contracts. That migration intentionally left some stdlib HTTP compatibility code
in place so the framework cutover could be behavior-preserving.

The current post-Stage-10 state still contains inactive stdlib HTTP adapter
ownership in the codebase:

```text
client/backend/server.py
  - still defines ClientBackendServer(ThreadingHTTPServer)
  - still defines ClientBackendHandler(BaseHTTPRequestHandler)
  - still imports stdlib response helpers used only by that legacy adapter

engine/server/api/server.py
  - still defines SimilarServer(ThreadingHTTPServer)
  - still imports SimilarHandler

engine/server/api/handlers/similar.py
  - still defines SimilarHandler(BaseHTTPRequestHandler)
  - still owns legacy GET/POST/OPTIONS dispatch for Engine route tests

tests/client_backend/conftest.py
  - still starts ClientBackendServer + ClientBackendHandler

tests/engine_api/*
  - still exercise SimilarHandler directly
```

Stage 11 finalizes FastAPI adapter ownership by removing inactive stdlib server
classes and moving remaining tests to FastAPI app factories or route/service
harnesses. The project must have one active HTTP adapter model after this stage:
FastAPI app factories plus compatibility launcher `server.py` entrypoints.

This stage must not change product behavior. It must not change route paths,
status codes, response bodies, request validation, CORS headers, rate-limit keys,
Engine startup prerequisites, Client/Engine boundaries, recommendation behavior,
DB/schema behavior, crawler behavior, frontend behavior, updater/job behavior, or
installer-facing entrypoint paths.

## Expected Behavior

After Stage 11:

- `python3 client/backend/server.py ...` remains the Client backend executable entrypoint.
- `python3 engine/server/api/server.py ...` remains the Engine API executable entrypoint.
- Both entrypoints run FastAPI/uvicorn app factories.
- No active `ThreadingHTTPServer`, `BaseHTTPRequestHandler`, `ClientBackendHandler`, `ClientBackendServer`, `SimilarHandler`, or `SimilarServer` remains in production runtime code.
- Existing Client routes keep the same behavior:

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

- Existing Engine routes keep the same behavior:

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

- Stage 0-10 tests remain green.
- Tests that previously depended on stdlib handlers are rewritten to use FastAPI
  app factories, `TestClient`, or narrow route/service harnesses.
- `docs/FRAMEWORK_COMPATIBILITY.md` records the compatibility decision that
  stdlib HTTP adapters were removed while `server.py` executable paths were kept.

Concrete preserved behavior examples:

```text
Client /api/user-action:
  local profile write, Engine resolve call, Engine ingest publish, and bridge
  partial-failure status/body remain unchanged.
```

```text
Engine /videos/{id}/similar:
  path id injection, recommendation request parsing, debug-disabled 403,
  malformed likes errors, and response row shape remain unchanged.
```

```text
Engine /internal/events/ingest:
  ENGINE_INGEST_MODE != bridge still returns the current 501 payload.
```

## Architecture

Stage 11 changes only HTTP adapter cleanup and test ownership after the Stage 10
FastAPI migration.

Target ownership after Stage 11:

```text
client/backend/server.py
  -> CLI parsing, DB/runtime construction, FastAPI app creation, uvicorn launch

client/backend/app.py
  -> Client FastAPI route registration and request adaptation

client/backend/runtime.py
  -> Client runtime state

client/backend/http_adapters.py
  -> FastAPI response/body/CORS/rate-limit compatibility helpers

client/backend/services/*
  -> Client profile/write/proxy/bridge behavior

client/backend/repositories/*
  -> Client users DB persistence

engine/server/api/server.py
  -> CLI parsing, DB/index/runtime construction, FastAPI app creation, uvicorn launch

engine/server/api/app.py
  -> Engine FastAPI route registration and request adaptation

engine/server/api/runtime.py
  -> Engine runtime state

engine/server/api/http_adapters.py
  -> FastAPI route/service compatibility helpers

engine/server/api/routes/*
  -> Engine route behavior introduced in Stage 4

engine/server/api/services/*
  -> Engine route orchestration introduced in Stage 4/5
```

### Explicitly retained compatibility

The executable paths are compatibility contracts and must remain:

```text
client/backend/server.py
engine/server/api/server.py
```

The FastAPI apps may continue to use lightweight compatibility helpers that
preserve response bytes, CORS, client IP, request body limits, and status codes.
Those helpers must be named as FastAPI compatibility helpers, not stdlib HTTP
servers or handlers.

### Explicitly removed ownership

After Stage 11, production runtime code must not define or instantiate:

```text
ThreadingHTTPServer
BaseHTTPRequestHandler
ClientBackendServer
ClientBackendHandler
SimilarServer
SimilarHandler
```

If a tiny compatibility import shim is needed for old helper import paths, it
must not subclass `BaseHTTPRequestHandler`, must not dispatch routes, and must be
documented in `docs/FRAMEWORK_COMPATIBILITY.md` with a removal condition.

## Touched Files

```text
Makefile
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/TESTING.md
docs/FRAMEWORK_COMPATIBILITY.md
client/backend/server.py
client/backend/app.py
client/backend/http_adapters.py
client/backend/lib/http_utils.py
client/backend/runtime.py
client/backend/schemas.py
engine/server/api/server.py
engine/server/api/app.py
engine/server/api/http_adapters.py
engine/server/api/http_utils.py
engine/server/api/handlers/similar.py
engine/server/api/routes/channels.py
engine/server/api/routes/health.py
engine/server/api/routes/internal_events.py
engine/server/api/routes/internal_videos.py
engine/server/api/routes/recommendations.py
engine/server/api/routes/videos.py
engine/server/api/services/recommendation_service.py
pyproject.toml
tests/client_backend/conftest.py
tests/client_backend/*.py
tests/engine_api/conftest.py
tests/engine_api/*.py
tests/framework/*.py
```

Do not edit these areas in Stage 11 except documentation references that
explicitly describe the HTTP adapter cleanup:

```text
AGENTS.md
client/frontend/src/*
engine/crawler/src/*
engine/crawler/schema.sql
engine/server/data/*
engine/server/db/jobs/*
engine/server/db/migrations/*
engine/server/api/recommendations/*
client/backend/services/*
client/backend/repositories/*
```

## New Files

```text
plans/13_stage_11_fastapi_adapter_cleanup.md
```

Optional only if needed to remove legacy stdlib typing/imports without changing
behavior:

```text
client/backend/rate_limit.py
client/backend/user_identity.py
engine/server/api/rate_limit.py
engine/server/api/response_protocol.py
```

If optional files are added, they must be internal compatibility/refinement files
only. They must not change public API behavior or introduce new framework policy.

## Implementation Steps

### 1. Confirm baseline before removing legacy adapters

Run:

```bash
make test
make lint
python3 -m pytest tests/framework -q
python3 client/backend/server.py --help
python3 engine/server/api/server.py --help
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

Implementation action:

- Record the known Engine `server.py --help` FAISS prerequisite as unchanged if it still fails in the local environment.
- Do not change Engine FAISS/import/startup behavior to make this command pass.
- Do not continue if `make test`, `make lint`, or boundary checks fail before Stage 11 edits.

### 2. Migrate Client backend tests away from `ClientBackendServer` and `ClientBackendHandler`

Current files to inspect first:

```text
tests/client_backend/conftest.py
tests/client_backend/test_user_action_like_characterization.py
tests/client_backend/test_client_publish_event_characterization.py
tests/client_backend/test_profile_likes_characterization.py
tests/client_backend/test_read_proxy_characterization.py
tests/client_backend/test_read_proxy_failure_characterization.py
tests/client_backend/test_user_profile_characterization.py
tests/client_backend/test_user_profile_reset_characterization.py
```

Required implementation:

- Replace the threaded stdlib Client backend fixture with a FastAPI `TestClient`
  fixture created from `client/backend/app.py::create_app`.
- Build `ClientRuntimeState` directly in the fixture with:
  - temporary SQLite users DB;
  - `UsersRepository`;
  - fake Engine base URL;
  - configured publish mode;
  - generous `RateLimiter`.
- Keep fake Engine HTTP servers where tests verify real network gateway behavior.
- Preserve test assertions for:
  - local DB likes/profile state;
  - Engine resolve/metadata/ingest fake-server payloads;
  - bridge failure status/body;
  - proxy status/content-type/body preservation;
  - unknown query/body field errors;
  - profile reset behavior.

Do not weaken scenario tests to service-only tests. These are Client HTTP
behavior tests and must still exercise FastAPI route adapters.

### 3. Remove legacy Client stdlib adapter code from `client/backend/server.py`

Required implementation:

- Remove imports used only by the legacy stdlib adapter:
  - `BaseHTTPRequestHandler`;
  - `ThreadingHTTPServer`;
  - `urlparse`, `parse_qs` if no longer used by launcher code;
  - stdlib response helpers used only by the legacy handler.
- Delete `ClientBackendServer`.
- Delete `ClientBackendHandler`.
- Keep:
  - constants used for runtime construction;
  - `_emit_client_log`;
  - `parse_args`;
  - `connect_db`;
  - `main`;
  - uvicorn launch.
- Ensure `main` continues to build `ClientRuntimeState` and call `create_app(state)`.

Expected post-change responsibility:

```text
client/backend/server.py = CLI + runtime construction + uvicorn launcher only
```

### 4. Migrate Engine API tests away from `SimilarHandler`

Current files to inspect first:

```text
tests/engine_api/conftest.py
tests/engine_api/test_engine_route_dispatch_characterization.py
tests/engine_api/test_channels_route_characterization.py
tests/engine_api/test_internal_video_routes_characterization.py
tests/engine_api/test_engine_ingest_mode_characterization.py
tests/engine_api/test_similar_route_characterization.py
```

Required implementation:

- Replace direct `SimilarHandler.do_GET/do_POST/do_OPTIONS` tests with FastAPI
  `TestClient` calls against `engine/server/api/app.py::create_app` where route
  behavior is HTTP-observable.
- Build `EngineRuntimeState` test fixtures with temporary SQLite DBs, fake index
  objects, fake recommendation strategy, and fake runtime deps as Stage 10
  framework tests already do.
- For behavior that is route-internal and not useful through HTTP, use the
  existing route/service functions directly with `FastAPIHandlerAdapter`, not
  `SimilarHandler`.
- Preserve assertions for:
  - unknown route 404 body;
  - CORS `OPTIONS` behavior;
  - rate-limit status/body and key shape;
  - `/api/channels` defaults and caps;
  - internal video resolve/metadata payloads;
  - internal ingest mode gate;
  - `/videos/{id}/similar` path-id injection;
  - debug-disabled response;
  - oversized/malformed recommendation body errors;
  - request-context cleanup after recommendation exceptions.

Do not delete coverage. If an old `SimilarHandler` test cannot be translated to
FastAPI/TestClient, translate it to a route/service harness with
`FastAPIHandlerAdapter` and keep the same assertion.

### 5. Remove `SimilarHandler` and `SimilarServer` production ownership

Required implementation:

- Delete `SimilarServer` from `engine/server/api/server.py`.
- Remove `SimilarHandler` imports from `engine/server/api/server.py`.
- Delete the `SimilarHandler(BaseHTTPRequestHandler)` class from
  `engine/server/api/handlers/similar.py`.
- Keep `engine/server/api/handlers/similar.py` only if needed as a compatibility
  re-export module for historically imported helper names.
- If `handlers/similar.py` remains:
  - it must not import `BaseHTTPRequestHandler`;
  - it must not define route dispatch methods;
  - it must have a module docstring explaining that active Engine routing lives
    in `engine/server/api/app.py` and `engine/server/api/routes/*`;
  - `docs/FRAMEWORK_COMPATIBILITY.md` must include the removal condition.

Expected post-change responsibility:

```text
engine/server/api/server.py = CLI + runtime construction + uvicorn launcher only
engine/server/api/app.py = FastAPI route registration
engine/server/api/routes/* = route behavior
```

### 6. Remove or retarget stdlib HTTP helper ownership

Required implementation:

- Replace `BaseHTTPRequestHandler` type annotations in helper modules with
  structural protocols or FastAPI adapter types where those helpers are still
  needed.
- Do not change JSON indentation, CORS headers, status codes, or body reading
  limits while doing this.
- If `client/backend/lib/http_utils.py` only needs `RateLimiter` and
  `resolve_user_id` after legacy deletion, either:
  - keep the file with only those non-stdlib helpers; or
  - move them to optional new files (`rate_limit.py`, `user_identity.py`) and
    leave compatibility re-exports.
- If `engine/server/api/http_utils.py` remains for route/service compatibility,
  it must depend on a protocol/interface, not `BaseHTTPRequestHandler`.

Do not rewrite Engine route modules into new return types in Stage 11. That
would be a separate public route-service contract refactor.

### 7. Update framework compatibility documentation

Update:

```text
docs/FRAMEWORK_COMPATIBILITY.md
```

Add entries with this structure:

```text
Decision:
Reason:
Implementation action:
Tests:
Removal condition, if any:
```

Required entries:

```text
Stdlib Client backend adapter removed; server.py path preserved.
Stdlib Engine SimilarHandler removed; FastAPI route ownership preserved.
BaseHTTPRequestHandler tests migrated to FastAPI/TestClient or route harnesses.
Any remaining helper compatibility shim is temporary and has a removal condition.
```

Do not add a new compatibility document for Stage 11. Framework compatibility is
already owned by `docs/FRAMEWORK_COMPATIBILITY.md`.

### 8. Update architecture/development/testing docs

Update only sections whose stated responsibility covers the changed concept.

Required documentation updates:

```text
docs/ARCHITECTURE.md
  - Client and Engine HTTP adapter ownership now FastAPI-only.
  - server.py files are compatibility launchers, not stdlib HTTP servers.

docs/DEVELOPMENT.md
  - Local server commands remain the same.
  - FastAPI/uvicorn is now the only active HTTP framework.

docs/TESTING.md
  - Client/Engine HTTP tests use FastAPI/TestClient or route harnesses.
  - Legacy BaseHTTPRequestHandler tests are no longer part of the test model.

README.md or component READMEs
  - update only if they still describe stdlib HTTP servers as active runtime.
```

Do not edit `AGENTS.md`; current project rules already cover this stage.

### 9. Update lint/test surfaces only for changed files

Required implementation:

- If `pyproject.toml` or `Makefile` needs updates, limit them to Stage 11 test
  paths or changed maintained surface.
- Do not make frontend, crawler, DB, updater, or unrelated lint surfaces stricter
  in Stage 11.

### 10. Final verification

Run:

```bash
make test
make lint
python3 -m pytest tests/client_backend tests/engine_api tests/framework -q
python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit
python3 client/backend/server.py --help
python3 engine/server/api/server.py --help
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

Expected local result:

- All tests and boundary checks pass.
- `client/backend/server.py --help` passes.
- `engine/server/api/server.py --help` may still fail with the unchanged FAISS
  prerequisite. If it does, verify the error text is still the known prerequisite
  and document it in the final implementation summary.

Also run static verification:

```bash
grep -R "class .*BaseHTTPRequestHandler\|ThreadingHTTPServer\|ClientBackendHandler\|ClientBackendServer\|SimilarHandler\|SimilarServer" client/backend engine/server/api tests
```

Expected result:

- No active production runtime definitions remain.
- Documentation references are allowed only if they describe historical Stage 10
  compatibility or Stage 11 removal decisions.
- Test references are allowed only when asserting absence/removal, not when
  executing legacy adapters.

## Tests

Stage 11 must keep existing behavior tests and migrate legacy-handler tests
instead of deleting coverage.

Required checks:

```bash
make test
make lint
python3 -m pytest tests/client_backend tests/engine_api tests/framework -q
python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

Required coverage after migration:

- Client HTTP scenario tests still exercise FastAPI routes.
- Engine route characterization tests still exercise FastAPI routes or route
  functions with FastAPI-compatible adapters.
- Framework tests still cover CORS, rate-limit keys, invalid JSON/request-size
  behavior, entrypoint paths, and compatibility documentation.
- Boundary tests still prove frontend -> Client -> Engine and no Client direct
  Engine imports/DB reads.

No new product behavior tests are required unless removing legacy adapters
exposes an uncovered branch. If that happens, add the missing characterization
test before deleting the corresponding legacy code.

## Documentation Maintenance

Documentation updates are required because Stage 11 changes framework ownership
from transitional dual-adapter state to FastAPI-only active adapter ownership.

Required docs:

```text
docs/FRAMEWORK_COMPATIBILITY.md
  Records the stdlib adapter removal and remaining server.py compatibility paths.

docs/ARCHITECTURE.md
  Describes FastAPI app factories as the active HTTP adapter layer.

docs/DEVELOPMENT.md
  Describes local commands and active framework model.

docs/TESTING.md
  Describes FastAPI/TestClient route tests and no legacy handler tests.
```

Optional docs only if they contain stale active-stdlib wording:

```text
README.md
client/README.md
engine/server/README.md
docs/DEPLOYMENT.md
```

Do not update unrelated docs.

## Regression and Blind-Spot Analysis

### Risk: removing `ClientBackendHandler` changes Client HTTP behavior

Action: migrate all Client backend characterization tests to FastAPI
`TestClient` before deleting `ClientBackendHandler`; keep assertions on DB state,
fake Engine payloads, status codes, content type, and response bodies unchanged.

### Risk: removing `SimilarHandler` loses Engine route dispatch coverage

Action: translate each existing `SimilarHandler.do_GET/do_POST/do_OPTIONS` test to
FastAPI `TestClient` or `FastAPIHandlerAdapter` route/service harness before
removing `SimilarHandler`; do not delete a test until its replacement passes.

### Risk: FastAPI default 404/422/error behavior leaks into contracts

Action: keep explicit catch-all routes and manual body parsing; after legacy
removal run malformed request and unknown route tests through FastAPI routes.

### Risk: rate-limit client IP/key behavior changes when legacy handlers vanish

Action: keep `rate_limit_key` and Engine `_rate_limit_or_none` behavior intact;
assert `X-Forwarded-For`, `X-Real-IP`, and socket/client fallback behavior in
framework tests if those paths are touched.

### Risk: `server.py` entrypoint compatibility breaks while removing old classes

Action: keep `parse_args`, runtime construction, `create_app(state)`, and
`uvicorn.run(...)` in the existing files; run entrypoint compatibility tests and
`client/backend/server.py --help` after edits.

### Risk: Engine FAISS startup failure mode changes accidentally

Action: do not lazy-load FAISS, move FAISS imports, or change Engine startup
ordering in Stage 11; entrypoint tests must keep accepting only the known FAISS
prerequisite failure for environments without FAISS.

### Risk: helper cleanup turns into route/service return-type redesign

Action: only replace stdlib handler type annotations with protocols or adapter
interfaces. Do not rewrite Engine routes/services to return new response objects
in Stage 11.

### Risk: compatibility shims become permanent undocumented debt

Action: any remaining import shim must be documented in
`docs/FRAMEWORK_COMPATIBILITY.md` with an explicit removal condition and covered
by tests that prove it is not an active route owner.

### Risk: unrelated surfaces become stricter and create noisy failures

Action: limit lint/test configuration changes to Stage 11 files and existing
framework/client/engine API tests. Do not broaden lint/typecheck to frontend,
crawler, DB, or updater in this stage.

## Compatibility and Protocol Notes

This is project-specific HTTP framework compatibility work. It is not a generic
FastAPI API redesign and does not change public Client/Engine route protocols.

FastAPI is now the active HTTP adapter. The compatibility requirement is that
existing project clients observe the same status codes, response bodies, CORS
headers, body-size handling, invalid JSON errors, rate-limit behavior, and
entrypoint paths that existed before the cleanup.

No PeerTube API behavior, ActivityPub/federation behavior, recommendation
protocol behavior, crawler schema behavior, or deployment topology is changed in
Stage 11.

## Non-Negotiable Implementation Constraints

Constraint: `server.py` executable paths must stay.
Required action: remove legacy server classes but keep `parse_args`, runtime
construction, FastAPI app creation, and uvicorn launch in the same files.

Constraint: no active stdlib HTTP route adapters may remain.
Required action: remove `BaseHTTPRequestHandler` subclasses and
`ThreadingHTTPServer` subclasses from production runtime code; migrate tests
first.

Constraint: no public schema redesign.
Required action: keep manual dict/body parsing and compatibility responses; do
not introduce Pydantic request/response models in this stage.

Constraint: no Engine startup/dependency redesign.
Required action: leave FAISS import behavior and runtime initialization order as
it is after Stage 10.

Constraint: no service/domain behavior changes.
Required action: do not edit Client services/repositories, Engine data access,
recommendation internals, crawler, frontend, DB migrations, or updater jobs
except for import-path adjustments strictly required by adapter cleanup.

Constraint: no undocumented backward compatibility decisions.
Required action: record every retained or removed framework compatibility shim
in `docs/FRAMEWORK_COMPATIBILITY.md`.

## Open Questions

None for the current Stage 11 scope.
