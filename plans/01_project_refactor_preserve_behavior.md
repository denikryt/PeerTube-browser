# Project Refactor While Preserving Behavior

## Problem / Goal

The project currently works and must remain working throughout the refactor. The goal is not to rewrite the product, change the recommendation behavior, or replace the current runtime flow. The goal is to turn the existing repository into a normal, readable, maintainable project with clear responsibilities, stable boundaries, and enough regression coverage to refactor safely.

Current working product flow:

```text
crawler -> SQLite datasets/indexes -> Engine API -> Client backend API -> Frontend
```

Current major problems visible in the codebase:

- Product code is mixed with old local planning/agent workflow infrastructure under `.agents/`, `dev/workflow_lib/`, `dev/map/`, and workflow tests.
- Runtime HTTP handlers are large and responsibility-heavy:
  - `client/backend/server.py` owns routing, request parsing, profile persistence calls, Engine proxying, bridge publishing, CORS, rate limiting, and process startup.
  - `engine/server/api/handlers/similar.py` owns routing, recommendation dispatch, request parsing, internal endpoints, channels, video lookup, debug response shaping, rate limiting, and fallback behavior.
- Database ownership is not sufficiently explicit. Runtime schema helpers, crawler schema, and job migration logic are distributed across `engine/crawler/schema.sql`, `engine/crawler/src/db.ts`, `engine/server/data/*`, and `engine/server/db/jobs/*`.
- The crawler has a large database module (`engine/crawler/src/db.ts`) and generated `engine/crawler/dist/*` files are committed.
- Frontend page files are large and mix API calls, state, DOM rendering, page behavior, and formatting.
- Tests exist, but too much test weight is attached to obsolete workflow infrastructure and smoke scripts. Product behavior needs more scenario/regression coverage before structural changes.
- Development tooling is incomplete at repository level: there is no central lint/test/typecheck entrypoint and no clear split between runtime, ML/job, crawler, frontend, and dev dependencies.

The target state is a repository where a developer can understand the product by reading a small set of documents and then navigate predictable modules:

```text
engine/
  api/ or server/api/          # Engine HTTP API and route wiring
  recommendations/             # recommendation domain logic
  data/                        # read repositories and SQLite access
  db/                          # migrations, jobs, build/update flow
  crawler/                     # PeerTube crawling subsystem

client/
  backend/                     # browser-facing API, profile store, Engine gateway
  frontend/                    # web UI

docs/                          # architecture, development, data build, deployment
plans/                         # implementation plans
scripts/ or Makefile           # standard local commands
```

## Expected Behavior

The refactor must preserve the currently working behavior unless a later stage-specific plan explicitly states and tests a behavior change.

Behavior that must remain stable:

- Frontend must continue to use the Client backend as its API gateway, not Engine directly.
- Client backend must continue to own user profile/write endpoints:
  - `GET /api/user-profile`
  - `GET /api/user-profile/likes`
  - `POST /api/user-action`
  - `POST /api/user-profile/reset`
  - `POST /client/events/publish`
- Engine must continue to own read/recommendation/internal endpoints:
  - `GET /api/health`
  - `GET /api/channels`
  - `GET /api/video`
  - `GET /videos/{id}/similar`
  - `POST /recommendations`
  - `POST /videos/similar`
  - `POST /internal/videos/resolve`
  - `POST /internal/videos/metadata`
  - `POST /internal/events/ingest`
- Client backend must continue to proxy read requests to Engine over HTTP instead of importing Engine modules or reading Engine DB files directly.
- Like actions must continue to update Client-owned local profile state and publish normalized events to Engine bridge ingest when bridge mode is enabled.
- Engine recommendation ranking must continue to use request-provided Client likes and bridge-ingested aggregate interaction signals.
- Existing smoke scripts must continue to pass while new tests are added around smaller behavior slices.
- Existing deployment and installer behavior must not change until a dedicated installer/deployment plan is written.

Concrete behavior examples that must be protected by tests before refactoring their paths:

```json
{
  "user_id": "local-user",
  "action": "like",
  "video": {
    "video_id": "123",
    "instance_domain": "example.org",
    "video_uuid": "uuid-123"
  }
}
```

Expected observable result:

- Client users DB contains or updates a `likes` row for `(local-user, 123, example.org)`.
- Client response keeps the current success shape, including bridge result fields where applicable.
- Engine bridge ingest records a deduplicated interaction event or reports a controlled bridge failure without corrupting Client profile state.

```json
{
  "likes": [
    {
      "video_id": "123",
      "instance_domain": "example.org",
      "video_uuid": "uuid-123"
    }
  ],
  "user_id": "local-user"
}
```

Expected observable result:

- Engine resolves likes through its internal video identity path.
- Recommendation response keeps the current shape with `generatedAt`, `total`, `count`, `seed`, and `rows`.
- Debug fields are only exposed through existing debug behavior.

## Architecture

The refactor should preserve the current product architecture, but make boundaries explicit and enforceable.

### Current runtime boundary

```text
Frontend
  -> Client backend HTTP API
      -> Client users DB
      -> Engine HTTP API gateway calls
      -> Engine internal bridge ingest
          -> Engine interaction events/signals
Engine API
  -> Engine SQLite datasets
  -> ANN/similarity/random/popularity caches
Crawler/jobs
  -> Build and update Engine datasets and derived artifacts
```

### Target responsibility split

#### Client backend

Responsible for:

- Browser-facing API routing.
- Local user/profile/likes persistence.
- Request normalization for user actions.
- Client-to-Engine read gateway.
- Client-to-Engine bridge event publishing.
- Client API error shaping.

Not responsible for:

- Engine DB reads.
- Recommendation ranking.
- ANN/cache access.
- Crawler/job orchestration.

Suggested module split, preserving current behavior first:

```text
client/backend/server.py                  # temporary composition entrypoint only
client/backend/app.py                     # server construction and route registration if stdlib server remains
client/backend/routes/health.py
client/backend/routes/profile.py
client/backend/routes/actions.py
client/backend/routes/proxy.py
client/backend/services/user_actions.py
client/backend/services/bridge_publisher.py
client/backend/services/engine_gateway.py
client/backend/repositories/users.py      # can initially wrap client/backend/lib/users_store.py
client/backend/schemas.py
client/backend/lib/http_utils.py
client/backend/lib/time_utils.py
```

#### Engine API

Responsible for:

- Read API routing.
- Recommendation request handling.
- Video/channel metadata reads.
- Internal Client->Engine contracts.
- Bridge event ingest and dedup.
- Runtime configuration loading.

Not responsible for:

- Browser profile persistence.
- Frontend-specific state.
- Crawler network traversal.
- Offline embedding/index build implementation.

Suggested module split, preserving current behavior first:

```text
engine/server/api/server.py               # temporary composition entrypoint only
engine/server/api/routes/health.py
engine/server/api/routes/channels.py
engine/server/api/routes/videos.py
engine/server/api/routes/recommendations.py
engine/server/api/routes/internal_videos.py
engine/server/api/routes/internal_events.py
engine/server/api/services/recommendation_service.py
engine/server/api/services/video_service.py
engine/server/api/services/channel_service.py
engine/server/api/schemas.py
engine/server/api/config.py
engine/server/api/recommendations/*       # keep, then gradually clarify
engine/server/data/*                      # keep as data access layer
```

A later stage-specific plan may decide whether to keep `http.server` temporarily or migrate to FastAPI. This general plan does not require a framework migration. Framework migration is a separate risk and must not be bundled with first-pass cleanup.

#### Recommendation domain

Responsible for:

- Candidate generation.
- Filtering and diversity caps.
- Scoring.
- Mixing.
- Debug metadata generation.

Target internal flow:

```text
RecommendationRequest
  -> RecommendationContext
  -> CandidateSource[]
  -> Candidate[]
  -> ScoredCandidate[]
  -> Mixed RecommendationResult
  -> HTTP response adapter
```

The HTTP handler should not own scoring/mixing details. It should parse request data, call a service, and serialize the existing response shape.

#### Crawler and data build

Responsible for:

- PeerTube instance/channel/video discovery.
- Raw crawl DB writes.
- Health checks and crawl progress.
- Data collection retries and failure recording.

Target internal split:

```text
engine/crawler/src/peertube/api-client.ts
engine/crawler/src/db/connection.ts
engine/crawler/src/db/repositories/instances.ts
engine/crawler/src/db/repositories/channels.ts
engine/crawler/src/db/repositories/videos.ts
engine/crawler/src/db/repositories/progress.ts
engine/crawler/src/crawl/instances.ts
engine/crawler/src/crawl/channels.ts
engine/crawler/src/crawl/videos.ts
engine/crawler/src/cli/*.ts
```

The current `engine/crawler/src/db.ts` should be split only after characterization tests exist for the DB behaviors it currently implements.

#### Frontend

Responsible for:

- Page state.
- API calls to Client backend only.
- Rendering video/channel/profile interactions.
- Local UI cache where needed.

Target internal split:

```text
client/frontend/src/api/*
client/frontend/src/state/*
client/frontend/src/components/*
client/frontend/src/pages/videos/*
client/frontend/src/pages/video-page/*
client/frontend/src/pages/channels/*
client/frontend/src/types/*
```

The frontend should not change its visible behavior during the first refactor stages. DOM structure can be preserved while code is split.

## Touched Files

Initial general-plan touch list. Each stage-specific plan must narrow this list before implementation.

```text
AGENTS.md
README.md
docs/DATA_BUILD.md
docs/DEPLOYMENT.md
docs/subtree-workflow.md
client/README.md
client/backend/server.py
client/backend/lib/engine_api_client.py
client/backend/lib/http_utils.py
client/backend/lib/users_store.py
client/frontend/README.md
client/frontend/package.json
client/frontend/src/data/api-base.ts
client/frontend/src/data/cache.ts
client/frontend/src/data/channels.ts
client/frontend/src/data/local-likes.ts
client/frontend/src/data/user-actions.ts
client/frontend/src/data/user-profile.ts
client/frontend/src/data/videos.ts
client/frontend/src/pages/channels/index.ts
client/frontend/src/pages/video-page/index.ts
client/frontend/src/pages/videos/index.ts
client/frontend/src/types/channels.ts
client/frontend/src/types/videos.ts
engine/crawler/README.md
engine/crawler/package.json
engine/crawler/schema.sql
engine/crawler/src/db.ts
engine/crawler/src/*.ts
engine/server/README.md
engine/server/requirements.txt
engine/server/api/server.py
engine/server/api/server_config.py
engine/server/api/handlers/internal_client_reads.py
engine/server/api/handlers/internal_events.py
engine/server/api/handlers/similar.py
engine/server/api/handlers/video.py
engine/server/api/recommendations/*.py
engine/server/data/*.py
engine/server/db/jobs/*.py
engine/server/db/jobs/docs/*.md
tests/check-client-engine-boundary.sh
tests/check-frontend-client-gateway.sh
tests/run-arch-split-smoke.sh
tests/run-installers-smoke.sh
tests/workflow/*.py
.agents/*
dev/*
```

## New Files

Potential new files across the whole refactor. Each stage-specific plan must state the exact subset it will create.

```text
plans/01_project_refactor_preserve_behavior.md
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/TESTING.md
docs/ROADMAP.md
pyproject.toml
.editorconfig
.pre-commit-config.yaml
Makefile
client/backend/app.py
client/backend/routes/__init__.py
client/backend/routes/health.py
client/backend/routes/profile.py
client/backend/routes/actions.py
client/backend/routes/proxy.py
client/backend/services/__init__.py
client/backend/services/user_actions.py
client/backend/services/bridge_publisher.py
client/backend/services/engine_gateway.py
client/backend/repositories/__init__.py
client/backend/repositories/users.py
client/backend/schemas.py
engine/server/api/routes/__init__.py
engine/server/api/routes/health.py
engine/server/api/routes/channels.py
engine/server/api/routes/videos.py
engine/server/api/routes/recommendations.py
engine/server/api/routes/internal_videos.py
engine/server/api/routes/internal_events.py
engine/server/api/services/__init__.py
engine/server/api/services/recommendation_service.py
engine/server/api/services/video_service.py
engine/server/api/services/channel_service.py
engine/server/api/schemas.py
engine/server/api/config.py
engine/server/api/recommendations/config.py
engine/server/api/recommendations/types.py
engine/server/config/recommendations.default.yaml
engine/server/config/recommendations.schema.json
engine/server/db/migrations/0001_initial.sql
engine/server/db/migrations/0002_interaction_events.sql
engine/server/db/migrate.py
engine/crawler/src/db/connection.ts
engine/crawler/src/db/repositories/instances.ts
engine/crawler/src/db/repositories/channels.ts
engine/crawler/src/db/repositories/videos.ts
engine/crawler/src/db/repositories/progress.ts
engine/crawler/src/peertube/api-client.ts
engine/crawler/src/crawl/instances.ts
engine/crawler/src/crawl/channels.ts
engine/crawler/src/crawl/videos.ts
client/frontend/src/api/client.ts
client/frontend/src/state/likes.ts
client/frontend/src/components/video-card.ts
client/frontend/src/components/like-button.ts
tests/client_backend/test_user_actions.py
tests/client_backend/test_engine_gateway.py
tests/engine_api/test_internal_events.py
tests/engine_api/test_recommendations_contract.py
tests/engine_api/test_video_metadata_contract.py
tests/recommendations/test_scoring.py
tests/recommendations/test_mixing.py
tests/crawler/test_repositories.ts
tests/frontend/*.test.ts
```

## Implementation Steps

### Stage 0: Freeze current behavior with characterization checks

Purpose: create safety rails before structural edits.

Changes:

- Run and document current baseline commands:
  - `python3 -m compileall client/backend engine/server`
  - existing Python tests under `engine/server/api/tests` and `engine/server/db/jobs/tests` where they can run locally.
  - `bash tests/check-client-engine-boundary.sh`
  - `bash tests/check-frontend-client-gateway.sh`
  - `bash tests/run-arch-split-smoke.sh` when local DB/index prerequisites are available.
  - `cd client/frontend && npm run build`
  - `cd engine/crawler && npm run build`
- Add a `docs/TESTING.md` page that states which tests are fast, which are smoke/integration, and which require DB/index artifacts.
- Add a root `Makefile` or equivalent command wrapper only after verifying existing commands. The first version should wrap current behavior, not invent a new workflow.

Behavior tests to add before refactor:

- Client user action scenario:
  - Given an empty Client users DB and a fake Engine bridge endpoint.
  - When `POST /api/user-action` receives a like payload.
  - Then the like exists in Client DB and the bridge payload contains normalized identity fields.
- Client proxy scenario:
  - Given a fake Engine read endpoint.
  - When frontend-equivalent request hits Client `/recommendations` or `/api/video`.
  - Then Client forwards to Engine and preserves expected response fields.
- Engine internal event ingest scenario:
  - Given an empty Engine interaction DB.
  - When the same event is ingested twice.
  - Then dedup prevents double counting and response remains deterministic.
- Engine recommendation contract scenario:
  - Given a minimal fixture DB/index substitute or fake candidate provider.
  - When recommendations are requested with likes.
  - Then response shape and limit behavior match current expectations.

Exit criteria:

- The baseline is documented.
- Fast tests exist for the highest-risk behavior paths.
- No production code structure changes have been made yet except test harness seams if absolutely necessary.

### Stage 1: Remove or archive non-product workflow infrastructure

Purpose: make the repository readable without changing product behavior.

Changes:

- Move obsolete agent/task-planning infrastructure out of the active project tree or delete it after confirmation in a stage-specific plan:
  - `.agents/`
  - `dev/workflow_lib/`
  - `dev/map/`
  - `dev/TASK_LIST.json`
  - `dev/TASK_EXECUTION_PIPELINE.json`
  - `dev/ISSUE_DEP_INDEX.json`
  - `dev/ISSUE_OVERLAPS.json`
  - `dev/FEATURE_PLANS.md`
  - `tests/workflow/`
- Preserve only human-readable project planning material that is still useful, rewritten into `docs/ROADMAP.md` if needed.
- Remove committed cache/build artifacts:
  - `__pycache__/`
  - `*.pyc`
  - `engine/crawler/dist/`
- Update `.gitignore` so removed generated files do not return.
- Update `README.md` to describe the product, not the old workflow machinery.

Compatibility risk:

- Some documentation or scripts may still reference old workflow files. The stage-specific plan must search for those references and either remove or replace them.
- If any command in current docs depends on `dev/workflow`, that command must be classified as obsolete before removal.

Exit criteria:

- Product smoke checks still pass.
- No runtime endpoint, crawler command, frontend build command, or installer command depends on removed workflow files.
- New contributors can read `README.md`, `docs/ARCHITECTURE.md`, and `docs/DEVELOPMENT.md` without encountering old agent workflow instructions.

### Stage 2: Establish repository-level development tooling

Purpose: make safe refactoring repeatable.

Changes:

- Add root-level command entrypoints:
  - `make test`
  - `make test-fast`
  - `make test-smoke`
  - `make lint`
  - `make typecheck`
  - `make build-frontend`
  - `make build-crawler`
- Add Python tooling in `pyproject.toml`:
  - pytest discovery for product tests.
  - ruff linting.
  - optional type checking after code layout stabilizes.
- Keep Node commands in existing package directories initially. Do not introduce workspaces until a dedicated frontend/crawler tooling plan exists.
- Split Python dependencies conceptually before changing install behavior:
  - API runtime dependencies.
  - ML/index-build dependencies.
  - Dev/test dependencies.
  - GPU-specific dependencies.

Compatibility risk:

- `engine/server/requirements.txt` currently includes CUDA/GPU-heavy dependencies. Splitting dependencies must not break existing deployment instructions. The first change should add optional files or extras while keeping the old file as compatibility alias if necessary.

Exit criteria:

- A developer can run one command for fast product tests.
- Existing documented deployment flow still works.
- Tooling changes are documented in `docs/DEVELOPMENT.md` and `docs/TESTING.md`.

### Stage 3: Split Client backend responsibilities without changing framework

Purpose: reduce `client/backend/server.py` while preserving all current endpoint behavior.

Recommended approach:

- Do not migrate frameworks in this stage.
- Keep `BaseHTTPRequestHandler` initially.
- Extract pure behavior and service functions behind the same route entrypoints.

Changes:

- Extract profile persistence access from direct handler code into a repository/service layer:
  - `client/backend/repositories/users.py`
  - `client/backend/services/user_actions.py`
- Extract Engine read proxy logic into:
  - `client/backend/services/engine_gateway.py`
- Extract bridge publish logic from `_publish_to_engine_bridge` and `_publish_event` into:
  - `client/backend/services/bridge_publisher.py`
- Keep `client/backend/lib/engine_api_client.py` as low-level HTTP client, but make higher-level service code own payload normalization and failure policy.
- Keep response shapes exactly the same.

Concrete preserved behavior:

- A failed bridge publish must not remove the local Client like after it was successfully recorded, unless current behavior already does so and a later behavior-change plan says otherwise.
- `bridge_ok` and `bridge_error` response fields must remain compatible with existing frontend/smoke expectations.
- Client gateway route allowlist must remain explicit and tested.

Tests:

- Add scenario tests around `POST /api/user-action`, `GET /api/user-profile/likes`, and Engine proxying using fake Engine HTTP endpoints.
- Assert DB state and HTTP response payloads, not only calls to mocks.
- Mock only network/time/random boundaries.

Exit criteria:

- `client/backend/server.py` is mostly routing/composition.
- Profile, proxy, and bridge behavior each has a clear module and tests.
- Boundary test still proves Client backend does not import Engine internals.

### Stage 4: Split Engine API routing and services without changing framework

Purpose: reduce `engine/server/api/handlers/similar.py` and make Engine runtime paths traceable.

Recommended approach:

- Do not migrate frameworks in this stage.
- Keep existing HTTP server entrypoint.
- Move route-specific logic into modules with stable function signatures.

Changes:

- Extract route handlers:
  - health route.
  - channels route.
  - video route.
  - recommendations/similar route.
  - internal video resolve/metadata routes.
  - internal event ingest route.
- Introduce services for behavior that is not HTTP-specific:
  - `recommendation_service.py`
  - `video_service.py`
  - `channel_service.py`
- Keep data access in `engine/server/data/*` and avoid introducing new DB access patterns inside route modules.
- Keep rate limiting, request ID creation, logging profile behavior, and debug response behavior compatible.

Concrete preserved behavior:

- `GET /videos/{id}/similar` must continue to set `id` into the same internal params path.
- `POST /recommendations` must continue to parse and resolve Client likes with the current max-size and body-size constraints.
- `/internal/events/ingest` must continue to return `501` when bridge ingest is disabled by `ENGINE_INGEST_MODE`.

Tests:

- Add Engine route scenario tests using an in-process server or handler harness where possible.
- Add contract tests for response shape and error shape.
- Add regression tests for like payload validation limits and invalid JSON handling.

Exit criteria:

- `engine/server/api/handlers/similar.py` is no longer a large mixed-responsibility module.
- Engine route modules are narrow enough to inspect quickly.
- Existing smoke scripts pass.

### Stage 5: Clarify recommendation pipeline internals

Purpose: make recommendation behavior easier to tune without accidental changes.

Changes:

- Introduce explicit recommendation types, initially as dataclasses or typed dictionaries:
  - `RecommendationRequest`
  - `RecommendationContext`
  - `Candidate`
  - `ScoredCandidate`
  - `RecommendationResult`
- Move recommendation configuration out of the large Python dict in `engine/server/api/server_config.py` into a validated configuration module and eventually a YAML/JSON file.
- Keep default config values identical at first.
- Add validation that catches duplicate or invalid generator fields, bad ratios, negative limits, and unknown layers.
- Separate debug metadata from candidate business fields where possible without changing external debug response shape.

Concrete preserved behavior:

- Existing profile names such as `home`, `guest_home`, and `upnext` must continue to resolve.
- Current generator names must remain compatible:
  - `random`
  - `popular`
  - `explore`
  - `exploit`
  - `fresh`
- Current output row fields must remain stable for frontend consumption.

Tests:

- Unit tests for scoring and mixing with deterministic candidate fixtures.
- Scenario tests for recommendation response shape.
- Regression tests for author/instance caps and layer soft caps.
- Config validation tests that fail on malformed ratios, unknown layers, and missing required generator settings.

Exit criteria:

- Recommendation code can be read by following request -> candidate source -> scoring -> mixing -> response.
- Tuning config is validated before serving traffic.
- No recommendation behavior change is introduced without a dedicated stage-specific plan and before/after tests.

### Stage 6: Centralize database schema and migration ownership

Purpose: make SQLite state safe to evolve.

Changes:

- Inventory all runtime-created tables and indexes across:
  - `engine/crawler/schema.sql`
  - `engine/crawler/src/db.ts`
  - `engine/server/data/*.py`
  - `engine/server/db/jobs/*.py`
  - `client/backend/lib/users_store.py`
- Decide explicit ownership:
  - Client users DB migrations belong under `client/backend/db` or `client/backend/repositories` migration helpers.
  - Engine dataset/caches/signals migrations belong under `engine/server/db/migrations`.
  - Crawler raw crawl DB schema belongs under `engine/crawler/schema.sql` plus migration helpers if needed.
- Create migration files only after a complete schema inventory.
- Keep runtime `ensure_*` helpers as compatibility wrappers until installer/data-build docs migrate to explicit migration commands.

Concrete schema behavior to preserve:

- Client `likes` primary key remains `(user_id, video_id, instance_domain)` unless a later plan changes identity semantics.
- Engine interaction ingest dedup remains event-id based.
- Existing data build outputs remain compatible with `docs/DATA_BUILD.md` paths.

Tests:

- Migration tests against empty SQLite DBs.
- Migration tests against minimal old-shape DB fixtures.
- Runtime tests proving handlers work after migrations and do not depend on hidden opportunistic schema creation.

Exit criteria:

- There is a documented source of truth for each DB.
- Runtime startup does not silently hide schema drift except where explicitly documented as compatibility behavior.
- Data build and deployment docs match the new migration flow.

### Stage 7: Split crawler database and crawl responsibilities

Purpose: make crawler code maintainable without changing crawl output.

Changes:

- Add characterization tests for high-risk `engine/crawler/src/db.ts` behaviors before splitting:
  - insert/upsert instance.
  - update health status.
  - store followers/following edges.
  - insert/upsert channel.
  - update video counts.
  - insert/upsert video metadata.
  - persist crawl progress and retry/error state.
- Split DB connection and repository functions from CLI/network traversal code.
- Keep existing npm command names stable:
  - `crawl:instances`
  - `crawl:instances:health`
  - `crawl:channels`
  - `crawl:channels:health`
  - `crawl:channels:videos-count`
  - `crawl:videos`
  - `crawl:videos:tags`
  - `crawl:videos:comments`
- Remove committed `dist/` files after build/test commands are reliable.

Compatibility risk:

- Crawler output DB shape is consumed by Engine jobs. Any schema or row-shape change must be coordinated with Stage 6 and protected by integration tests.

Tests:

- Repository tests with temporary SQLite DBs.
- CLI smoke tests with fake PeerTube API responses at network boundary.
- Regression tests for retry/error recording.

Exit criteria:

- `engine/crawler/src/db.ts` is split into narrow modules.
- Current npm commands still work.
- Engine data build jobs can consume crawler output without manual fixes.

### Stage 8: Refactor frontend page code into API/state/components

Purpose: make frontend readable and safer to change while preserving UI behavior.

Changes:

- Keep Vite and current HTML entrypoints initially.
- Extract API client modules that only call Client backend routes.
- Extract local likes/profile state handling.
- Extract reusable render components for video cards, like buttons, channel rows, and loading/error states.
- Split page controllers from rendering helpers.
- Preserve current CSS and DOM output where possible during first pass.

Concrete preserved behavior:

- Frontend must not introduce direct Engine API URLs or Engine internal routes.
- Like/unlike buttons must continue to update local UI state and Client backend state consistently.
- Video page and videos feed must continue to use the same route payloads.

Tests:

- Static boundary test remains: frontend cannot reference Engine API base/internal routes.
- Add frontend unit tests or DOM tests for like button state transition, feed rendering from rows, and API error display.
- Add build check in root tooling.

Exit criteria:

- Large page files are reduced to page composition/controller code.
- API calls, state, and rendering are separated.
- Frontend build and gateway boundary tests pass.

### Stage 9: Rationalize jobs, updater, and deployment docs

Purpose: keep operational behavior understandable and documented.

Changes:

- Split `engine/server/db/jobs/updater-worker.py` into orchestration, stage execution, lock/state handling, and command adapters.
- Preserve existing updater stage order:
  - crawl to staging.
  - embeddings.
  - merge to prod.
  - popularity.
  - ANN rebuild.
  - similarity precompute.
- Keep installer scripts behavior stable until a dedicated installer plan exists.
- Update `docs/DATA_BUILD.md`, `docs/DEPLOYMENT.md`, and `engine/server/db/jobs/docs/UPDATER_WORKER.md` only in sections whose documented responsibility is affected.

Tests:

- Existing updater smoke tests remain.
- Add focused tests for lock behavior, resume behavior, partial failure handling, and command sequencing.
- Use fake command runners instead of shelling out in unit tests.

Exit criteria:

- Updater code is split into narrow modules.
- Operational docs match real commands.
- Installer smoke tests still pass where environment supports them.

### Stage 10: Optional framework migration plan

Purpose: decide whether to migrate stdlib HTTP servers to FastAPI after behavior is protected and modules are separated.

This stage must not happen before Stages 0, 3, and 4.

Potential changes:

- Introduce FastAPI apps for Client and Engine.
- Keep route paths and response payloads compatible.
- Keep existing `server.py` entrypoints as compatibility wrappers during transition.
- Generate or document OpenAPI contracts after payload schemas are explicit.

Compatibility risk:

- CORS behavior, request size errors, invalid JSON errors, status codes, and rate limiting can change accidentally during framework migration.
- Existing installer scripts may assume direct `python server.py` execution.

Tests:

- Contract tests must compare old/new status codes and payload shapes before switching production entrypoints.
- Smoke tests must pass against new servers.

Exit criteria:

- Framework migration is behavior-preserving from the frontend and installer perspective.
- Old entrypoints are removed only after docs and installers are updated.

## Tests

Testing must follow behavior-first rules. Each stage-specific implementation plan must start with failing or missing behavior tests before production refactoring.

### Required test categories

#### Fast Python tests

```text
tests/client_backend/test_user_actions.py
tests/client_backend/test_engine_gateway.py
tests/engine_api/test_internal_events.py
tests/engine_api/test_recommendations_contract.py
tests/recommendations/test_scoring.py
tests/recommendations/test_mixing.py
```

Assertions should check observable effects:

- HTTP status codes.
- Response payload fields.
- SQLite rows.
- Dedup decisions.
- Retry state.
- Outbound bridge payloads captured by a fake HTTP server.

#### TypeScript/crawler tests

```text
tests/crawler/test_repositories.ts
```

Assertions should check SQLite state after repository actions.

#### Frontend tests

Add only after choosing a frontend test runner in a stage-specific plan. Focus on:

- API base enforcement.
- Like button state.
- Feed rendering from recommendation rows.
- Error display for failed Client API calls.

#### Boundary tests

Keep and expand:

```text
tests/check-client-engine-boundary.sh
tests/check-frontend-client-gateway.sh
```

These protect the most important architecture rule: frontend -> Client -> Engine, not frontend -> Engine and not Client -> Engine internals.

#### Smoke tests

Keep as integration/ops checks:

```text
tests/run-arch-split-smoke.sh
tests/run-installers-smoke.sh
```

Do not rely on smoke scripts as the only proof of correctness. They are too broad and environment-dependent to be the main refactor safety net.

### Test design rules for this project

- Prefer scenario tests over isolated tests for bridge/gateway behavior.
- Test concrete runtime actions in defined system states.
- Use temporary SQLite DBs for persistence assertions.
- Use fake HTTP servers for Engine/Client network boundaries.
- Mock only network, platform SDK edges, time, and random IDs.
- Every bug found during refactor gets a regression test before the fix.

## Documentation Maintenance

Documentation changes must be made with the code stage that affects them.

Relevant documentation responsibilities:

```text
README.md
  Product overview, component map, quick start, current architecture summary.

docs/ARCHITECTURE.md
  Stable architecture, ownership boundaries, runtime data flow, forbidden coupling.

docs/DEVELOPMENT.md
  Local setup, commands, dependency groups, code layout, common workflows.

docs/TESTING.md
  Test categories, how to run them, prerequisites, expected scope.

docs/DATA_BUILD.md
  Crawler, jobs, datasets, derived artifacts, migration/build flow.

docs/DEPLOYMENT.md
  systemd/service setup, production/dev contours, runtime paths.

docs/subtree-workflow.md
  Only subtree split/push workflow. Do not add general development notes here.

engine/server/db/jobs/docs/UPDATER_WORKER.md
  Updater worker behavior, lock/resume/failure semantics, stage order.
```

Before editing any document, read its purpose section or first paragraphs and update only the document whose responsibility covers the changed concept.

## Regression and Blind-Spot Analysis

High-risk regressions:

- Client accidentally starts importing Engine internals after code movement.
- Frontend accidentally calls Engine directly after API client refactor.
- Bridge ingest failures accidentally break local user action success semantics.
- Dedup or echo-prevention behavior changes during event ingest cleanup.
- Recommendation ranking output changes because generator order, caps, or config defaults move.
- Debug response shape changes and breaks diagnostics.
- Crawler DB output changes and breaks Engine jobs.
- Runtime opportunistic schema creation hides migration mistakes or changes DB shape silently.
- Installer scripts point at moved entrypoints and break production/dev service setup.
- Heavy ML/GPU dependency changes make deployment easier locally but break existing GPU build hosts.

Blind spots to investigate in stage-specific plans:

- Exact current bridge payload shape emitted by Client backend for every supported action.
- Exact Engine interaction event schema and dedup key behavior.
- Exact recommendation config values after resolving profile-specific defaults.
- Which smoke tests require real dataset/index files and which can run against fixtures.
- Whether `engine/server/db/users.db` references are fully obsolete or still used in some path.
- Whether ActivityPub mode has any working code path or is only a future-mode placeholder.
- Whether service installers assume generated crawler `dist/` files are present before `npm run build`.

Each stage-specific plan must state the expected conflicts and blind spots for that stage before production code changes begin.

## Compatibility and Protocol Notes

Current bridge behavior is a local Client->Engine HTTP contract, not a full ActivityPub implementation. Treat it as a project-specific gateway/ingest protocol unless a later plan explicitly implements generic ActivityPub behavior.

PeerTube crawler behavior is vendor/API-specific to PeerTube public endpoints such as instance following/followers, video channels, and video metadata APIs. Do not describe crawler-specific payload assumptions as generic federated-video behavior.

Recommendation mixing/scoring is project-specific product behavior. It should not be presented as a standard recommendation protocol.

Any future ActivityPub work must be planned separately and must explicitly distinguish:

- generic ActivityPub object/activity semantics;
- PeerTube-specific API or federation behavior;
- project-specific local bridge compatibility behavior.

## Open Questions

- Should obsolete workflow infrastructure be deleted outright or moved to `_archive/old-agent-workflow/` for historical reference before deletion?
- Should the first API cleanup keep `http.server` until the end, or should FastAPI migration happen after Client/Engine route modules are extracted?
- What is the minimum fixture dataset required to run recommendation contract tests without relying on the developer's local production DB/index files?
- Should root tooling use `Makefile`, `justfile`, npm workspaces, or a small Python task runner?
- Should dependency splitting preserve `engine/server/requirements.txt` as the compatibility install file while adding new narrower files?
- Which frontend test runner should be used: Vitest with jsdom, Playwright component/e2e tests, or only build/static tests at first?
- Should generated artifacts such as `engine/crawler/dist/` be removed immediately after confirming installers build the crawler, or only after deployment docs are updated?
- Are current `activitypub` mode branches active requirements or future placeholders?

