# Stage 0: Freeze Current Behavior Before Refactoring

## Problem / Goal

The project currently works and the refactor must preserve that working behavior. Stage 0 exists to create a reliable safety net before any structural cleanup, module splitting, dependency reorganization, or workflow removal happens.

This stage must not make product architecture changes. It should document the current baseline, add focused characterization tests around the highest-risk behavior paths, and expose current command prerequisites clearly enough that later refactor stages can run the same checks repeatedly.

Current high-risk behavior paths found in the real codebase:

- Frontend reads must stay behind the Client backend gateway. The existing guard is `tests/check-frontend-client-gateway.sh`.
- Client backend must not import Engine modules or read Engine DB files. The existing guard is `tests/check-client-engine-boundary.sh`.
- Client backend owns profile and write routes in `client/backend/server.py`:
  - `GET /api/health`
  - `GET /api/user-profile`
  - `GET /api/user-profile/likes`
  - `POST /api/user-action`
  - `POST /api/user-profile/reset`
  - `POST /api/user-profile/likes`
  - `POST /client/events/publish`
- Client backend proxies read routes from browser-facing Client API to Engine HTTP API:
  - `GET /api/video`
  - `GET /api/channels`
  - `POST /recommendations`
  - `POST /videos/similar`
- Engine API owns read, recommendation, and internal ingest behavior mostly through `engine/server/api/handlers/similar.py` and helper handlers:
  - `GET /api/health`
  - `GET /api/channels`
  - `GET /api/video`
  - `GET /videos/{id}/similar`
  - `POST /recommendations`
  - `POST /videos/similar`
  - `POST /internal/videos/resolve`
  - `POST /internal/videos/metadata`
  - `POST /internal/events/ingest`
- Interaction event ingest and dedup live in `engine/server/data/interaction_events.py` and are already partly covered by `engine/server/db/jobs/tests/test-interaction-events.py`.
- Recommendation scoring, filtering, mixing, personalization, and fallback feed behavior are product-critical and live across `engine/server/api/recommendations/*`, `engine/server/api/handlers/similar.py`, and `engine/server/data/*`.
- Similarity candidate resolution is product-critical because it connects cached similarity rows or ANN results to metadata rows, source exclusion, author caps, moderation filters, and final response candidates.
- Video metadata resolution is product-critical because the video page depends on the current merge between stored DB metadata and live/dynamic PeerTube instance metadata.
- Crawler/database compatibility is product-critical because Engine read paths assume the SQLite schema produced by `engine/crawler/schema.sql` and crawler/update jobs.
- Random, recent, and popular fallback feeds are product-critical because new users or empty-profile users can still receive a useful feed when personalized candidates are unavailable.
- The full split smoke script `tests/run-arch-split-smoke.sh` starts Engine on `7072`, Client on `7272`, verifies gateway boundaries, sends a Client like action, verifies profile likes, and checks that Engine does not open `engine/server/db/users.db`.
- Existing Python import/runtime checks are partially blocked by missing optional runtime dependencies. `python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit` currently exits with `faiss is required. Install faiss-cpu in your Python environment.` because importing `engine/server/api/server.py` requires `faiss`.
- Node builds currently require installing local dependencies first. `client/frontend npm run build` fails without `vite`; `engine/crawler npm run build` fails without `engine/crawler/node_modules/typescript/bin/tsc`.

Observed local baseline while preparing this plan:

```text
python3 -m compileall client/backend engine/server
# PASS

python3 engine/server/db/jobs/tests/test-interaction-events.py
# PASS

bash tests/check-client-engine-boundary.sh
# PASS

bash tests/check-frontend-client-gateway.sh
# PASS

python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit
# FAIL in current environment: faiss is required

cd client/frontend && npm run build
# FAIL in current environment: vite is not installed

cd engine/crawler && npm run build
# FAIL in current environment: TypeScript is not installed in node_modules
```

The failed commands are environment/dependency baseline findings, not behavior regressions by themselves. Stage 0 must document them and separate fast checks that can run in a clean Python environment from checks that require optional ML/Node dependencies.

## Expected Behavior

After Stage 0:

- No production behavior is intentionally changed.
- Existing boundary checks still pass.
- Existing interaction ingest idempotency behavior still passes.
- Missing local dependencies are reported clearly instead of being confused with product failures.
- The project has a documented fast test baseline and a documented smoke/integration baseline.
- Later refactor stages can use Stage 0 tests as regression guards before moving code.
- Characterization tests describe current behavior even where the implementation is not yet clean.
- Tests assert observable effects: HTTP responses, SQLite rows, forwarded payloads, response shapes, and visible gateway constraints.

Behavior that must be frozen before later stages:

```text
frontend -> client backend -> engine api
```

The frontend must not call Engine directly.

```text
client backend /api/user-action like
  -> resolves video identity through Engine /internal/videos/resolve
  -> records Client-owned like in users DB
  -> publishes normalized Like event to Engine /internal/events/ingest
  -> returns current success/failure shape
```

The Client profile update and Engine bridge publish are both part of the current behavior.

```text
engine recommendation core
  -> scores candidates using current similarity/freshness/popularity/layer formulas
  -> filters and deduplicates candidates according to current caps and exclusions
  -> mixes exploit/explore/fallback candidates according to current configuration
  -> exposes debug metadata only where current behavior does so
```

The recommendation output is the central product behavior and must be characterized before moving recommendation modules or route handlers.

```text
engine similarity candidate pipeline
  -> resolves seed video identity
  -> reads similarity candidates from cache when available
  -> falls back through the current ANN/computation path when cache is unavailable
  -> resolves metadata rows
  -> applies seed/source-author/per-author/limit filtering according to current behavior
```

Similarity behavior must be protected separately from the HTTP response contract because it is easy to break during repository/module splitting while route-level tests still return HTTP 200.

```text
engine video metadata behavior
  -> looks up videos by current id/uuid/host rules
  -> applies current error-threshold/moderation filtering
  -> merges dynamic instance metadata over stored DB fallback fields
  -> keeps the response shape expected by the frontend video page
```

Video page behavior must remain stable while `engine/server/api/handlers/video.py` and related data functions are reorganized.

```text
engine /internal/events/ingest
  -> accepts one event or {"events": [...]}
  -> normalizes event fields
  -> inserts raw event idempotently by event_id
  -> updates interaction_signals only for non-duplicates
  -> returns ok/count/ingested/duplicates/results
```

Deduplication and signal aggregation must remain stable.

```text
client read proxy
  -> accepts only allowlisted route/query/body fields
  -> forwards to Engine over HTTP
  -> preserves upstream response body/content-type/status where possible
  -> returns controlled 400/502 errors for invalid input or unavailable Engine
```

The proxy is a boundary contract and must be protected before splitting `client/backend/server.py`.

```text
engine crawler/database schema compatibility
  -> schema.sql creates the tables and columns used by Engine read paths
  -> update jobs preserve the columns consumed by recommendations and video metadata
  -> fallback feed queries still find random/recent/popular videos from the current schema
```

Schema compatibility is a product behavior contract even when no HTTP route is involved.

## Architecture

Stage 0 adds tests and documentation around the current architecture without changing the architecture.

Current runtime architecture to protect:

```text
client/frontend/src/*
  -> Client backend public/gateway routes
      -> client/backend/lib/users_store.py
      -> client/backend/lib/engine_api_client.py
      -> Engine HTTP API
          -> engine/server/api/handlers/*
          -> engine/server/data/*
          -> SQLite datasets and interaction tables
```

Stage 0 test architecture:

```text
tests/contracts/
  -> static boundary checks and public route contract checks

tests/client_backend/
  -> Client backend characterization tests using temporary SQLite and fake Engine HTTP server

tests/engine_api/
  -> Engine internal ingest, video metadata, and recommendation/API response-shape characterization tests

tests/recommendations/
  -> deterministic scoring, filtering, mixing, and profile/fallback behavior tests

tests/engine_data/
  -> similarity candidate, random/recent/popular feed, and schema compatibility tests

tests/repositories/
  -> persistence tests against temporary SQLite databases

tests/smoke/
  -> wrappers or documentation for existing full-contour smoke scripts
```

No framework migration happens in Stage 0. `http.server` remains the runtime framework for both Client and Engine.

No module split happens in Stage 0. Large files such as `client/backend/server.py`, `engine/server/api/handlers/similar.py`, and `engine/crawler/src/db.ts` are only tested and documented here.

## Touched Files

```text
AGENTS.md
README.md
docs/DATA_BUILD.md
docs/DEPLOYMENT.md
client/README.md
client/backend/server.py
client/backend/lib/engine_api_client.py
client/backend/lib/http_utils.py
client/backend/lib/users_store.py
client/frontend/README.md
client/frontend/package.json
engine/crawler/README.md
engine/crawler/package.json
engine/server/README.md
engine/server/api/handlers/internal_client_reads.py
engine/server/api/handlers/internal_events.py
engine/server/api/handlers/similar.py
engine/server/api/handlers/video.py
engine/server/api/http_utils.py
engine/server/api/server.py
engine/server/api/server_config.py
engine/server/data/interaction_events.py
engine/server/data/videos.py
engine/server/data/channels.py
engine/server/db/jobs/tests/test-interaction-events.py
tests/check-client-engine-boundary.sh
tests/check-frontend-client-gateway.sh
tests/run-arch-split-smoke.sh
```

Stage 0 should only edit a small subset of these files. The rest are listed because the plan was based on their current behavior and because new tests will target their contracts.

Allowed production-code edits in Stage 0:

```text
client/backend/server.py
engine/server/api/handlers/similar.py
engine/server/api/server.py
```

Only if a test seam is impossible otherwise, and only with no behavior change. Example allowed seam: allow dependency injection of an already-existing server attribute in tests. Example forbidden edit: moving route handling into new modules during Stage 0.

## New Files

```text
plans/02_stage_0_behavior_freeze.md
docs/TESTING.md
tests/contracts/test_current_boundary_scripts.py
tests/client_backend/conftest.py
tests/client_backend/test_user_action_like_characterization.py
tests/client_backend/test_read_proxy_characterization.py
tests/client_backend/test_profile_likes_characterization.py
tests/engine_api/conftest.py
tests/engine_api/test_internal_events_ingest_characterization.py
tests/engine_api/test_recommendations_request_contract.py
tests/engine_api/test_video_metadata_characterization.py
tests/recommendations/test_scoring_characterization.py
tests/recommendations/test_filters_characterization.py
tests/recommendations/test_mixer_characterization.py
tests/recommendations/test_profile_characterization.py
tests/engine_data/test_similarity_candidates_characterization.py
tests/engine_data/test_random_recent_popular_characterization.py
tests/engine_data/test_schema_compatibility_snapshot.py
tests/repositories/test_client_users_store.py
tests/repositories/test_engine_interaction_events.py
```

Optional if Stage 0 introduces a root command wrapper:

```text
Makefile
```

Do not add a broad `pyproject.toml`, ruff setup, pre-commit setup, dependency split, or package reorganization in Stage 0 unless a later implementation-specific Stage 0 sub-plan explicitly scopes that as a documentation-only or command-wrapper task. Repository-wide tooling belongs mainly to Stage 2.

## Implementation Steps

### 1. Record the baseline before adding tests

Run the existing checks and record the exact result in `docs/TESTING.md`.

Commands:

```bash
python3 -m compileall client/backend engine/server
python3 engine/server/db/jobs/tests/test-interaction-events.py
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit
cd client/frontend && npm run build
cd engine/crawler && npm run build
```

Document results in groups:

```text
Fast checks that currently pass without optional dependencies
Checks blocked by missing Python optional dependencies
Checks blocked by missing Node dependencies
Smoke checks requiring runtime DB/index artifacts
```

Do not hide current failures. The purpose is to distinguish missing dependency/precondition failures from behavior failures.

### 2. Create `docs/TESTING.md`

The document must state its purpose at the top:

```text
This document defines how to verify current PeerTube Browser behavior before and during refactoring. It separates fast regression checks from dependency-heavy builds and full-contour smoke checks.
```

Include these sections:

```text
Fast baseline
Python behavior tests
Contract and boundary checks
Node build checks
Full-contour smoke checks
Known local prerequisites
How to interpret failures
```

Concrete content to include:

```text
Fast baseline:
- python3 -m compileall client/backend engine/server
- python3 engine/server/db/jobs/tests/test-interaction-events.py
- bash tests/check-client-engine-boundary.sh
- bash tests/check-frontend-client-gateway.sh

Dependency-heavy checks:
- engine server API tests may import faiss through engine/server/api/server.py
- frontend build requires npm install in client/frontend
- crawler build requires npm install in engine/crawler

Smoke checks:
- tests/run-arch-split-smoke.sh starts Engine and Client locally
- it requires Engine runtime dependencies and usable DB/index/cache inputs
```

Do not document imagined commands that do not exist yet as if they are already available.

### 3. Add contract tests for existing shell boundary scripts

Add `tests/contracts/test_current_boundary_scripts.py` to run the two current shell checks from pytest/unittest.

Responsibilities:

- Run `bash tests/check-client-engine-boundary.sh`.
- Run `bash tests/check-frontend-client-gateway.sh`.
- Fail with captured stdout/stderr if either script fails.

Example assertion shape:

```python
result = subprocess.run([...], cwd=ROOT, text=True, capture_output=True)
assert result.returncode == 0, result.stdout + result.stderr
assert "PASS" in result.stdout
```

This does not replace the shell scripts. It makes them visible to the Python test baseline.

Expected behavior:

- Client backend remains free of direct Engine imports and Engine DB coupling.
- Frontend remains free of direct Engine API base/internal route usage.

### 4. Add repository tests for Client-owned users DB

Add `tests/repositories/test_client_users_store.py`.

Use temporary in-memory SQLite or a temporary DB file. Import only `client/backend/lib/users_store.py`, not `client/backend/server.py`.

Test cases:

#### 4.1 Schema creation

Given:

```text
empty SQLite connection
```

When:

```python
ensure_user_schema(conn)
```

Then:

```sql
SELECT name FROM sqlite_master WHERE type='table'
```

contains:

```text
users
likes
```

and index `likes_user_updated_idx` exists.

#### 4.2 Like insert and update is idempotent by primary key

Given:

```text
schema exists
user_id = "local-user"
video = {"video_id": "123", "video_uuid": "uuid-123", "instance_domain": "example.org"}
```

When:

```python
record_like(conn, "local-user", "like", video, max_likes=100)
record_like(conn, "local-user", "like", video, max_likes=100)
```

Then:

```sql
SELECT COUNT(*) FROM likes WHERE user_id='local-user'
```

is `1`.

#### 4.3 Recent likes ordering and cap

Given three likes with controlled `updated_at` values. If controlling time requires patching `client.backend.lib.users_store.now_ms`, patch only the time boundary.

When:

```python
fetch_recent_likes(conn, "local-user", limit=2)
```

Then:

- two rows are returned;
- rows are newest first;
- fields are `video_id`, `video_uuid`, `instance_domain`, `updated_at`.

#### 4.4 Remove like

Given one stored like.

When:

```python
remove_like(conn, "local-user", "123", "example.org")
```

Then:

```sql
SELECT COUNT(*) FROM likes
```

is `0`.

### 5. Add repository tests for Engine interaction event behavior

Add `tests/repositories/test_engine_interaction_events.py`.

This can initially duplicate and extend `engine/server/db/jobs/tests/test-interaction-events.py`, but it should be a normal test module under `tests/` so the future fast test command has one product-test tree.

Test cases:

#### 5.1 Duplicate event does not double-count

Given:

```json
{
  "event_id": "evt-like-1",
  "event_type": "Like",
  "actor_id": "user-1",
  "object": {
    "video_uuid": "uuid-1",
    "instance_domain": "example.org",
    "canonical_url": "https://example.org/videos/watch/uuid-1"
  },
  "published_at": 1739700000000,
  "source_instance": "example.org",
  "raw_payload": {"source": "test"}
}
```

When the same payload is ingested twice.

Then:

- first result has `duplicate: false`;
- second result has `duplicate: true`;
- `interaction_raw_events` has one row;
- `interaction_signals.likes_count` is `1`.

#### 5.2 UndoLike cannot create negative likes

Given no existing Like event for a video.

When an `UndoLike` event is ingested.

Then:

- `likes_count` remains `0`;
- `undo_likes_count` is `1`;
- `signal_score` remains `0.0` because the update uses `MAX(0.0, ...)`.

#### 5.3 Invalid payloads raise current errors

Examples:

```text
missing event_id -> ValueError("Missing event_id")
unsupported event_type -> ValueError("Unsupported event_type")
missing object -> ValueError("Missing object")
missing object.video_uuid -> ValueError("Missing object.video_uuid")
missing object.instance_domain -> ValueError("Missing object.instance_domain")
```

These exact messages are current behavior and should be characterized before refactor.

### 6. Add Client backend user-action characterization test

Add `tests/client_backend/test_user_action_like_characterization.py`.

Use a fake Engine HTTP server instead of mocking internal calls. The fake server must implement:

```text
POST /internal/videos/resolve
POST /internal/events/ingest
```

The Client backend test should start `ClientBackendServer` on an ephemeral port using:

```python
ClientBackendServer(
    ("127.0.0.1", 0),
    ClientBackendHandler,
    user_db,
    fake_engine_base_url,
    "bridge",
    RateLimiter(...),
)
```

Use a temporary SQLite connection and call `ensure_user_schema(user_db)`.

Fake Engine `/internal/videos/resolve` response:

```json
{
  "video": {
    "video_id": "123",
    "video_uuid": "uuid-123",
    "instance_domain": "example.org",
    "video_url": "https://example.org/w/uuid-123"
  }
}
```

Client action request:

```json
{
  "action": "like",
  "uuid": "uuid-123",
  "host": "example.org",
  "user_id": "local-user"
}
```

Expected response:

```json
{
  "ok": true,
  "bridge_ok": true,
  "bridge_error": null,
  "user_id": "local-user"
}
```

Do not assert exact `updatedAt` except that it exists and is an integer.

Expected SQLite effect:

```sql
SELECT video_id, video_uuid, instance_domain
FROM likes
WHERE user_id = 'local-user'
```

returns:

```text
123, uuid-123, example.org
```

Expected fake Engine received ingest payload shape:

```json
{
  "event_id": "client-...",
  "event_type": "Like",
  "actor_id": "local-user",
  "object": {
    "video_uuid": "uuid-123",
    "instance_domain": "example.org",
    "canonical_url": "https://example.org/w/uuid-123"
  },
  "source_instance": "example.org",
  "raw_payload": {
    "action": "like",
    "uuid": "uuid-123",
    "host": "example.org",
    "user_id": "local-user"
  }
}
```

Do not assert exact `event_id` or `published_at` values; assert prefix/type only.

Also add a characterization for Engine ingest failure:

Given fake Engine resolve succeeds and fake Engine ingest returns `500`.

When Client receives the same like action.

Then current behavior is:

- like is already written to Client DB;
- response status is `502`;
- response has `ok: false`, `bridge_ok: false`, and a non-empty `bridge_error`.

This test protects the current partial-failure behavior. If a later stage wants to change it, that later plan must explicitly say so.

### 7. Add Client backend proxy characterization test

Add `tests/client_backend/test_read_proxy_characterization.py`.

Use a fake Engine HTTP server that records the request and returns known JSON.

Test cases:

#### 7.1 GET `/api/video` forwards allowlisted query params

Given fake Engine response:

```json
{"video": {"video_id": "123", "title": "Example"}}
```

When Client receives:

```text
GET /api/video?id=123&host=example.org&unknown=x
```

Current behavior should be checked carefully during implementation:

- if unknown query params are ignored, assert ignored;
- if unknown query params are rejected, assert the current error.

The implementation plan must run the test against current code before accepting the assertion.

Expected preserved fields if forwarded:

```text
id=123
host=example.org
```

#### 7.2 POST `/recommendations` allows only known body keys

Given fake Engine returns:

```json
{"generatedAt": 1, "total": 0, "count": 0, "seed": null, "rows": []}
```

When Client receives:

```json
{"likes": [{"uuid": "uuid-1", "host": "example.org"}], "user_id": "local-user", "mode": "home"}
```

Then:

- response status is `200`;
- response body is the fake Engine body;
- fake Engine receives `POST /recommendations`;
- forwarded body keeps only `likes`, `user_id`, and `mode`;
- likes are sanitized to `{ "uuid": "uuid-1", "host": "example.org" }`.

#### 7.3 POST `/recommendations` rejects unknown body field

When Client receives:

```json
{"likes": [], "unexpected": true}
```

Then current behavior is:

```json
{"error": "Unknown body field: unexpected"}
```

with status `400`.

### 8. Add profile likes characterization test

Add `tests/client_backend/test_profile_likes_characterization.py`.

Use fake Engine `/internal/videos/metadata`.

Given:

- Client users DB contains a like for `local-user`.
- Fake Engine metadata returns a row with current metadata fields.

When:

```text
GET /api/user-profile/likes?user_id=local-user
```

Then:

- Client calls fake Engine `/internal/videos/metadata` with stored entries;
- response status is `200`;
- response contains `user_id`, `likes`, `updatedAt`;
- `likes` is the Engine metadata response rows, not raw DB rows.

This protects the current split: Client stores lightweight identity; Engine provides display metadata.

### 9. Add Engine internal ingest handler characterization test

Add `tests/engine_api/test_internal_events_ingest_characterization.py`.

Prefer testing the real handler path if practical. The handler currently depends on a `handler` object with request body methods, response methods from `http_utils`, and a `server` object with `db` and `db_lock`.

Acceptable Stage 0 approaches:

1. Start a minimal `ThreadingHTTPServer` using `SimilarHandler` only if Engine can be constructed without requiring FAISS/index artifacts. Current `engine/server/api/server.py` imports `faiss` at module import time, so this may not be practical in a clean environment.
2. Call `handle_internal_events_ingest(handler, server)` with a realistic handler test double that exercises `read_json_body` and captures `respond_json` output.

The preferred first implementation is option 2, because it avoids FAISS and keeps the test fast.

Test cases:

#### 9.1 Single event ingest response shape

Given a handler body containing one valid event.

When:

```python
handle_internal_events_ingest(handler, server)
```

Then response is status `200`:

```json
{
  "ok": true,
  "count": 1,
  "ingested": 1,
  "duplicates": 0,
  "results": [
    {"ok": true, "duplicate": false, "event_id": "evt-1", "event_type": "Like"}
  ]
}
```

#### 9.2 Batch event ingest with duplicate

Given body:

```json
{"events": [event, event]}
```

Then response is status `200` with:

```text
count = 2
ingested = 1
duplicates = 1
```

#### 9.3 Empty events are rejected

Given body:

```json
{"events": []}
```

Then response is status `400`:

```json
{"error": "Missing events"}
```

### 10. Add recommendation request contract characterization

Add `tests/engine_api/test_recommendations_request_contract.py`.

This should avoid importing `engine/server/api/server.py` until FAISS is optional or available. Test the request parsing helpers directly from `engine/server/api/handlers/similar.py` where possible.

Existing risk:

- `engine.server.api.tests.test_recommendations_likes_limit` imports `handlers.similar` and currently fails in this environment through a `faiss` import path. The Stage 0 implementation must identify the exact import path and avoid or isolate it.

Initial test scope:

- `_recommendations_likes_payload_error` returns the current 400 payload for oversized likes.
- `_parse_client_likes` accepts `{"likes": [{"uuid": "...", "host": "..."}]}` and normalizes to `video_uuid`/`instance_domain` entries if that is current behavior in `similar.py`.
- invalid likes item returns the current error reason and index.

Do not rewrite recommendation logic in Stage 0. If importing `similar.py` requires optional FAISS indirectly, add a narrow import-seam plan before editing production code.

### 11. Add recommendation core characterization tests

Add deterministic tests under `tests/recommendations/` before moving recommendation modules or changing route handlers. These tests should import the smallest available modules directly and use fixed input data, fixed current time, and fixed random seeds where the current code allows it.

Recommended files:

```text
tests/recommendations/test_scoring_characterization.py
tests/recommendations/test_filters_characterization.py
tests/recommendations/test_mixer_characterization.py
tests/recommendations/test_profile_characterization.py
```

These tests are more important than broad handler-level tests because the project can keep returning HTTP 200 while feed quality silently changes.

#### 11.1 Scoring behavior

Given candidates with controlled values:

```json
{
  "video_id": "v1",
  "video_uuid": "uuid-1",
  "instance_domain": "example.org",
  "similarity_score": 1.2,
  "published_at": "2024-01-01T00:00:00Z",
  "views": 1000,
  "likes": 10,
  "dislikes": 1
}
```

When the current scoring function is called with fixed `now` and the current exploit/home settings.

Then characterize the current behavior for:

- similarity score clamping or normalization;
- freshness decay;
- popularity contribution;
- layer weight contribution;
- final score ordering;
- debug fields currently added by the scoring path.

If the exact formula is not intended as a long-term public contract, still assert a small number of stable representative outputs so later refactors preserve current behavior until a later stage intentionally changes it.

#### 11.2 Filtering behavior

Given candidates that include:

- duplicate video IDs;
- already-liked videos;
- hidden or excluded videos if current code supports them;
- too many videos from the same author/channel/instance;
- candidates over the current error threshold or moderation exclusion if filtering is applied at this layer.

When the current filtering functions run.

Then assert:

- duplicates are removed according to the current key rules;
- liked/hidden/seen exclusions match current behavior;
- per-author/per-channel/per-instance caps match current behavior;
- candidate order is preserved where the current filter preserves order.

#### 11.3 Mixer behavior

Given fake exploit, explore, and fallback candidate pools with known IDs and scores.

When the current mixer produces a result with a fixed limit and fixed configuration.

Then assert:

- output count respects `limit`;
- current exploit/explore/fallback distribution is preserved;
- duplicate candidate IDs do not appear twice if current code deduplicates them;
- debug rank/bucket/layer fields match current behavior when debug mode is active;
- empty exploit or empty explore inputs fall back according to current behavior.

#### 11.4 Profile/request behavior used by recommendations

Given current client likes payloads and current stored interaction profile rows.

When profile parsing or profile construction runs.

Then assert:

- current likes limit behavior;
- current mapping from `{uuid, host}` to internal fields;
- current guest/new-user fallback profile behavior;
- current handling of malformed likes items.

### 12. Add Engine recommendation HTTP response-shape characterization

Extend `tests/engine_api/test_recommendations_request_contract.py` beyond parser-only coverage if the Engine handler can be exercised without FAISS/index artifacts. If a direct route test is blocked by FAISS imports, record that as a Stage 0 blocker and add the direct service-level tests from step 11 first.

Target route behavior:

```text
POST /recommendations
```

Given a test server or handler seam with deterministic candidate providers.

When a request is sent with:

```json
{
  "user_id": "local-user",
  "mode": "home",
  "likes": [{"uuid": "uuid-1", "host": "example.org"}],
  "limit": 10,
  "debug": false
}
```

Then assert the current response shape:

- top-level fields currently returned by the route;
- `rows` item shape expected by the frontend;
- absence of debug-only fields when `debug=false` if that is current behavior;
- current count/total/generatedAt/profile/strategy fields where present.

Also add a debug-mode characterization:

```json
{"debug": true}
```

Then assert the current debug fields and no more. Do not invent a preferred future debug shape in Stage 0.

### 13. Add similarity candidate pipeline characterization

Add `tests/engine_data/test_similarity_candidates_characterization.py`.

Target module:

```text
engine/server/data/similarity_candidates.py
```

Use temporary SQLite and fakes for ANN/index computation where needed. Do not call the real FAISS index in this stage unless the current environment already supports it.

Test cases:

#### 13.1 Cache path preserves candidate identity and score

Given:

- a seed video row;
- similarity cache rows for the seed;
- metadata rows for candidate videos;
- one candidate equal to the seed;
- multiple candidates by the same author/channel.

When the current similarity candidate function runs with a fixed limit.

Then assert:

- the seed video is excluded if current behavior excludes it;
- candidate metadata is resolved from current DB fields;
- cached similarity score is preserved or mapped according to current behavior;
- per-author/per-channel caps match current behavior;
- result limit is respected.

#### 13.2 Source-author exclusion

Given a seed video and candidates from the same source author plus other authors.

When current config says to exclude the source author.

Then same-author candidates are excluded according to current behavior.

If source-author exclusion is currently optional or config-dependent, assert both current config states.

#### 13.3 Fallback path when cache is missing

Given no cache rows and a fake ANN/computation function that returns known IDs/scores.

When the candidate function runs.

Then assert:

- the fallback function is used only after cache miss;
- returned IDs are resolved through metadata;
- missing metadata rows are skipped according to current behavior;
- final candidates still pass the same limit/cap/exclusion rules.

### 14. Add video metadata characterization

Add `tests/engine_api/test_video_metadata_characterization.py`.

Target module:

```text
engine/server/api/handlers/video.py
```

Test direct helper functions first. If route-level testing is practical without importing `engine/server/api/server.py`, add a handler-level test using a realistic handler test double.

Test cases:

#### 14.1 Lookup by id/uuid/host

Given a temporary SQLite DB with video rows containing both local numeric/string IDs and UUIDs.

When the current lookup helper is called with:

```text
id=123
id=uuid-123
host=example.org
```

Then assert the current row selection behavior, including host disambiguation.

#### 14.2 Error-threshold and moderation filtering

Given video rows with normal and over-threshold error counts, plus moderation fields if the current query uses them.

When the lookup/fetch helper runs.

Then assert which rows are currently visible and which are suppressed.

#### 14.3 Dynamic metadata merge

Given:

- stored DB metadata with title, channel, thumbnails, views, likes, tags, category, nsfw fields;
- fake dynamic PeerTube metadata with only a subset of those fields.

When the current merge function or handler runs.

Then assert:

- dynamic fields override DB fields where current behavior does that;
- DB fields remain fallbacks when dynamic fields are missing;
- URL normalization for thumbnails/avatars uses the current rules;
- response shape remains compatible with `client/frontend/src/pages/video-page/index.ts`.

### 15. Add random/recent/popular fallback feed characterization

Add `tests/engine_data/test_random_recent_popular_characterization.py`.

Target modules may include:

```text
engine/server/data/random_videos.py
engine/server/data/random_cache.py
engine/server/data/popularity.py
engine/server/data/videos.py
```

Use temporary SQLite with a minimal set of videos, channels, and instances matching the current schema.

Test cases:

#### 15.1 Recent videos

Given videos with controlled publish times.

When the current recent/fallback query runs.

Then assert:

- newest-first ordering;
- limit behavior;
- current exclusion of error/moderated/unusable rows.

#### 15.2 Popular videos

Given videos with controlled views, likes, dislikes, and publish times.

When the current popularity query or score function runs.

Then assert:

- current ordering;
- current score formula for representative rows if exposed as a function;
- tie behavior only if it is deterministic today.

#### 15.3 Random videos

Given a fixed DB and a patchable random boundary if available.

When the current random query runs.

Then assert:

- it returns only usable video rows;
- it respects `limit`;
- it does not return duplicate IDs in one response if current behavior guarantees that.

Do not over-constrain random order unless the current implementation provides a seedable seam.

### 16. Add crawler/Engine schema compatibility snapshot

Add `tests/engine_data/test_schema_compatibility_snapshot.py`.

This is a cheap, high-value test that protects the contract between `engine/crawler/schema.sql` and Engine read paths.

Given:

```text
engine/crawler/schema.sql
```

When it is applied to a temporary SQLite database.

Then assert key tables exist, including the current names found in the schema for:

- videos;
- channels;
- instances;
- crawl/progress state;
- interaction/signal/cache tables if they are created by this schema rather than by runtime ensure functions.

Also assert key columns consumed by Engine data modules exist. At minimum verify the actual current column names used by Engine queries for:

```text
video identity
video UUID
instance/domain/host
channel/author identity
canonical/video URL
published timestamp
views/likes/dislikes or popularity inputs
error count / availability fields
moderation or visibility fields if used by current queries
thumbnail/avatar/display metadata fields used by frontend rows
```

The implementation must derive the exact column assertions from real current SQL and Engine query code. Do not assert ideal future column names.

### 17. Optionally add a minimal root command wrapper

A root `Makefile` is allowed only if it wraps already-verified commands and does not pretend that dependency-heavy commands are always available.

Initial targets:

```makefile
.PHONY: test-fast test-boundaries test-python-compile test-node-builds smoke-arch

test-fast:
	python3 -m compileall client/backend engine/server
	python3 engine/server/db/jobs/tests/test-interaction-events.py
	bash tests/check-client-engine-boundary.sh
	bash tests/check-frontend-client-gateway.sh

test-boundaries:
	bash tests/check-client-engine-boundary.sh
	bash tests/check-frontend-client-gateway.sh

test-node-builds:
	cd client/frontend && npm run build
	cd engine/crawler && npm run build

smoke-arch:
	bash tests/run-arch-split-smoke.sh
```

If this Makefile is added, `docs/TESTING.md` must mark `test-node-builds` and `smoke-arch` as prerequisite-dependent.

Do not add `make test` as an all-encompassing command yet unless it is explicit about prerequisites. A misleading default target would make Stage 0 less reliable.

### 18. Stop conditions

Stop and update this plan before implementation continues if any of these are discovered:

- Client `/api/user-action` current behavior differs from the expected response/DB/payload behavior above.
- Client proxy currently treats unknown query params differently than assumed.
- Existing smoke script requires undocumented DB/index artifacts that are not available locally.
- Importing `handlers.similar` cannot be isolated from FAISS without production-code changes.
- Adding fake HTTP server tests requires changing production routing logic.
- Any test would need to assert behavior that contradicts current README boundary contracts.

## Tests

Stage 0 is itself a test-safety stage. The implementation must add tests before production refactoring.

### Fast baseline tests

```bash
python3 -m compileall client/backend engine/server
python3 engine/server/db/jobs/tests/test-interaction-events.py
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

These currently pass in the inspected environment and should remain green.

### New Stage 0 tests

```bash
python3 -m pytest tests/contracts
python3 -m pytest tests/repositories
python3 -m pytest tests/client_backend
python3 -m pytest tests/engine_api
python3 -m pytest tests/recommendations
python3 -m pytest tests/engine_data
```

If pytest is not available yet, Stage 0 may use `unittest` temporarily, but the test files should be written so Stage 2 can include them in a normal pytest run without rewriting them.

### Dependency-heavy checks

```bash
python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit
cd client/frontend && npm run build
cd engine/crawler && npm run build
```

Current known blockers:

- `faiss` is required by Engine server import path.
- `client/frontend/node_modules` is missing.
- `engine/crawler/node_modules` is missing.

These checks should be documented, not silently skipped.

### Full-contour smoke

```bash
bash tests/run-arch-split-smoke.sh
```

Use this when the environment has Engine runtime dependencies and usable data/index artifacts. This script is not a replacement for the fast characterization tests because it is heavier and has more prerequisites.

## Regression and Blind-Spot Analysis

### Stage 0 implementation findings

- The original Stage 0 expectation said an `UndoLike` without a prior `Like` should not make counts negative. The real current implementation inserts the first `UndoLike` row with `likes_count = -1`, `undo_likes_count = 1`, and `signal_score = -1.0`. Stage 0 characterization tests freeze this actual behavior instead of changing production code. A later behavior-change plan should decide whether to clamp first `UndoLike` inserts.
- The Client read proxy currently rejects unknown query parameters before forwarding to Engine. Stage 0 tests assert the current `400 {"error": "Unknown query parameter: ..."}` behavior.
- The scoring/ranking tests assert current explore/exploit ordering produced by the existing ratio mixer rather than the initially assumed explore-first order.

### Regressions Stage 0 must catch

- Frontend begins calling Engine directly.
- Client backend imports Engine modules or reads Engine DB directly.
- Client like action stops writing local profile state.
- Client like action publishes malformed Engine ingest payloads.
- Client bridge failure silently loses the local like or returns a misleading success.
- Client read proxy stops preserving Engine response body/status.
- Client read proxy accepts unexpected body fields that later become accidental API surface.
- Engine event ingest double-counts duplicate `event_id` values.
- `UndoLike` behavior changes accidentally. Current first `UndoLike` behavior is negative counts/signal; this is now characterized as current behavior, not endorsed as desired behavior.
- Engine ingest response shape changes before route refactor begins.
- Recommendation scoring, filtering, or mixing changes unintentionally.
- Similarity candidates lose seed exclusion, source-author exclusion, caps, scores, or metadata mapping.
- Video metadata lookup/merge behavior changes and breaks the frontend video page.
- Random/recent/popular fallback feeds become empty, unstable, or include unusable rows.
- Crawler schema drifts away from the columns consumed by Engine data modules.

### Blind spots that remain after Stage 0

- Recommendation quality metrics are not fully characterized yet. Stage 5 needs deeper deterministic service tests and, if useful, offline evaluation fixtures.
- Crawler network behavior is not fully covered yet. Stage 7 needs fake PeerTube API integration tests and DB repository tests.
- Incremental refresh job behavior is only lightly covered by schema/fallback checks. Stage 7 needs job-level tests for updater-worker and merge-staging-db.
- Frontend visual behavior is not deeply covered yet. Stage 8 needs browser/component smoke tests.
- Installer/systemd behavior is not deeply covered by Stage 0. Stage 9 needs installer/deployment-specific testing.
- FAISS/index loading behavior is not made fast or optional in Stage 0. A later Engine API plan must decide how to isolate index-heavy runtime dependencies.

## Generic vs Project-Specific Behavior

Generic behavior:

- Characterization tests should freeze observable behavior before refactoring internals.
- Contract tests should protect component boundaries.
- Temporary SQLite databases are appropriate for persistence tests.
- Fake HTTP servers are appropriate for external HTTP boundaries.
- Optional dependency failures should be separated from product behavior failures.

Project-specific behavior:

- Frontend must use Client backend as the only gateway to Engine read routes.
- Client backend owns user profile and write routes.
- Engine owns recommendation, metadata, and internal ingest routes.
- Client like action writes Client DB first, then publishes a normalized bridge event to Engine.
- Engine interaction event ingest uses `event_id` idempotency and updates `interaction_signals`.
- Engine recommendation behavior is a product contract: scoring, filtering, mixing, fallback, and debug output must not change accidentally.
- Engine similarity candidate behavior is a product contract: cache lookup, fallback computation, metadata resolution, exclusions, and caps must remain stable.
- Engine video metadata behavior is a product contract: DB lookup, dynamic metadata overlay, and frontend row shape must remain stable.
- Engine crawler schema compatibility is a product contract between TypeScript crawler/update jobs and Python Engine read paths.
- The current full-contour smoke ports are Engine `7072` and Client `7272`.

## Expected Conflicts and Compatibility Risks

- The current Engine API test import path is coupled to `faiss`. Stage 0 tests should avoid broad Engine server imports unless the environment has FAISS installed.
- The current Client backend handler is a large `BaseHTTPRequestHandler` class. Testing it through HTTP may require careful thread lifecycle cleanup to avoid port leaks.
- `client/backend/server.py` uses a shared SQLite connection with `check_same_thread=False`. Tests must close server and DB resources explicitly.
- `RateLimiter` may affect HTTP scenario tests if the same path/IP is hit repeatedly. Use generous limits in test server instances.
- `updatedAt`, `event_id`, and `published_at` are dynamic. Tests must assert type/prefix/shape, not exact values.
- `tests/run-arch-split-smoke.sh` may fail for environment reasons unrelated to product behavior. Stage 0 must document prerequisites before treating it as mandatory.
- Adding a Makefile too early could create a false impression of stable repository tooling. Keep it minimal or defer to Stage 2.
- Recommendation modules may be hard to import without optional FAISS/index dependencies. Prefer narrow module imports and fake candidate providers; if impossible, record the import seam as a Stage 0 blocker.
- Some recommendation behavior may depend on current wall-clock time or random order. Tests must freeze time/random only at existing boundaries and avoid asserting random order unless it is deterministic today.
- Schema snapshot tests can become brittle if they assert idealized names. They must assert only current tables/columns actually consumed by Engine code.

## Open Questions

- Should Stage 0 add a root `Makefile` now, or should command wrapping wait for Stage 2 after tests are in place?
- Should recommendation request contract tests patch around FAISS import in Stage 0, or should they wait until Stage 4/5 introduces a proper Engine API import seam?
- Which recommendation functions are stable enough to assert exact numeric outputs, and which should be asserted through ordering/invariants only?
- Should schema compatibility tests assert all Engine-consumed columns or only the minimum high-risk set during Stage 0?
- Should random/recent/popular fallback tests live under `tests/engine_data` or under `tests/recommendations` if they are invoked mainly through the recommendation route?
- Should `docs/TESTING.md` be the only documentation file changed in Stage 0, or should `README.md` also get a short “Current verification commands” section?
- Should new tests use pytest immediately, or should they use only stdlib `unittest` until `pyproject.toml` is added in Stage 2?
