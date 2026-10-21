# Stage 4: Split Engine API Routing and Services Without Changing Framework

## Problem / Goal

The Engine API currently works, but the HTTP surface is concentrated in a small set of large modules. The highest-risk file is `engine/server/api/handlers/similar.py`, which currently owns route dispatch, request parsing, rate-limit checks, health responses, channel listing, video route delegation, Client likes parsing, Client likes DB resolution, recommendation/similar execution, random fallback handling, response shaping, debug toggles, internal video route delegation, and internal event ingest routing.

Stage 4 must make the Engine API runtime paths traceable without changing the runtime framework or product behavior. This stage must keep the current `http.server` entrypoint, current route paths, current status codes, current response payloads, current recommendation behavior, current data access modules, current FAISS/index loading behavior, current rate-limit behavior, and current debug behavior.

Current Engine API responsibilities found in real code:

```text
engine/server/api/server.py
  parse_args()
  set_nprobe()
  SimilarServer
  main()
  DB/cache/index startup wiring
  recommendation strategy construction
  rate limiter construction
  signal/lifecycle logging

engine/server/api/handlers/similar.py
  SimilarHandler
  do_OPTIONS()
  do_GET()
  do_POST()
  _rate_limit_check()
  _handle_similar_request()
  _fetch_random_rows()
  _respond_rows()
  _handle_random()
  _handle_home()
  _handle_seed_with_embedding()
  _handle_vector_search()
  _handle_similar()
  stable_video_row()
  stable_video_rows()
  maybe_attach_debug()
  _parse_client_likes()
  _recommendations_likes_payload_error()
  _resolve_client_likes()
  _parse_int()
  _parse_bool()
  _parse_non_negative_int()
  _make_request_id()
  _extract_video_id_from_similar_path()

engine/server/api/handlers/video.py
  video DB lookup
  PeerTube dynamic metadata fetch
  asset normalization
  dynamic-over-DB response merge
  /api/video response writing

engine/server/api/handlers/internal_client_reads.py
  /internal/videos/resolve
  /internal/videos/metadata

engine/server/api/handlers/internal_events.py
  /internal/events/ingest
```

Existing lower-level modules must remain the data/domain boundaries for this stage:

```text
engine/server/data/*
engine/server/api/recommendations/*
engine/server/api/http_utils.py
engine/server/api/request_context.py
engine/server/api/server_config.py
```

The desired result after Stage 4:

```text
engine/server/api/server.py
  command-line parsing
  process lifecycle
  SimilarServer state holder
  DB/cache/index startup wiring
  recommendation strategy construction

engine/server/api/handlers/similar.py
  SimilarHandler only
  request logging
  do_OPTIONS / do_GET / do_POST route dispatch
  rate-limit gate
  calls into route modules

engine/server/api/routes/health.py
  /api/health response

engine/server/api/routes/channels.py
  /api/channels query parsing and response

engine/server/api/routes/videos.py
  /api/video route adapter around current video handler

engine/server/api/routes/internal_videos.py
  /internal/videos/resolve and /internal/videos/metadata route adapters

engine/server/api/routes/internal_events.py
  /internal/events/ingest route adapter, including ingest-mode 501 behavior

engine/server/api/routes/recommendations.py
  /recommendations, /videos/similar, and /videos/{id}/similar route adapter

engine/server/api/services/recommendation_service.py
  current similar/recommendation/random/vector request execution moved out of SimilarHandler

engine/server/api/services/channel_service.py
  current channel query parsing and fetch orchestration, if useful after route extraction

engine/server/api/services/video_service.py
  current video endpoint orchestration, if needed as a wrapper around handlers/video.py
```

This stage is a behavior-preserving refactor. If implementation discovers a current Engine behavior bug, do not fix it in Stage 4. Add or update a regression test and plan the behavior change separately.

## Expected Behavior

All current Engine API behavior must remain stable.

### Public and internal routes must remain unchanged

```text
OPTIONS *
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

Unknown routes must still return status `404` with:

```json
{"error": "Not found"}
```

### Server startup and runtime state must remain unchanged

`engine/server/api/server.py` must continue to:

- parse the current CLI options;
- keep `--dev`, `--host`, `--port`, `--random-cache-refresh`, and `--no-random-cache-refresh` semantics;
- connect the same DB/cache/index files from `server_config.py` defaults;
- load FAISS in the same startup path;
- configure `nprobe` in the same way;
- create `SimilarServer` with the same attributes used by handlers/routes/services;
- build the current recommendation strategy through `build_recommendation_strategy()`;
- configure random cache, moderation schema, interaction event schema, channel/video indexes, logging profile, and rate limiter in the same startup order unless a later plan changes startup behavior.

Stage 4 may move route logic out of `SimilarHandler`, but it must not move or redesign startup ownership.

### Health behavior must remain unchanged

`GET /api/health` must continue to return status `200` with:

```json
{
  "ok": true,
  "total": 123,
  "embeddingDim": 384
}
```

The values come from `server.embeddings_count` and `server.embeddings_dim`.

### Channel listing behavior must remain unchanged

`GET /api/channels` must continue to:

- apply the current rate-limit behavior for `/api/*` paths;
- parse `limit` through the current positive-int semantics;
- default invalid or non-positive `limit` to `100`;
- cap `limit` at `500`;
- parse `offset`, `minFollowers`, `minVideos`, and `maxVideos` with current helper semantics;
- pass `q`, `instance`, `sort`, and `dir` through current defaults;
- call `fetch_channels()` under `server.db_lock`;
- return status `200` with:

```json
{
  "generatedAt": 1739700000000,
  "total": 2,
  "rows": []
}
```

Only the timestamp is dynamic.

### Video metadata behavior must remain unchanged

`GET /api/video` must continue to delegate to the current video metadata behavior:

- missing video id returns status `400` with `{"error": "Missing video id"}`;
- missing row returns status `404` with `{"error": "Video not found"}`;
- lookup by id/uuid/host remains current;
- error-threshold filtering remains current;
- dynamic PeerTube metadata still overlays DB fallback fields;
- frontend-facing response fields remain current.

Stage 4 may add a route adapter or service wrapper, but it must not redesign `handlers/video.py` response shape or dynamic metadata policy.

### Internal video read behavior must remain unchanged

`POST /internal/videos/resolve` must continue to:

- read JSON through `read_json_body()`;
- return status `400` on invalid JSON;
- require `video_id` or `uuid`;
- call `fetch_seed_embedding()` under `server.db_lock`;
- return status `404` when no seed is found;
- return the current `ok/video` shape.

`POST /internal/videos/metadata` must continue to:

- require an `entries` list;
- skip invalid entries;
- deduplicate `(video_id, instance_domain)` entries;
- call `fetch_metadata_by_ids()` under `server.db_lock`;
- return `{"ok": true, "count": 0, "rows": []}` for no valid entries;
- preserve row ordering according to the current valid-entry order.

### Internal event ingest behavior must remain unchanged

`POST /internal/events/ingest` must continue to check `server.engine_ingest_mode` before calling the ingest handler.

When `engine_ingest_mode != "bridge"`, it must return status `501` with:

```json
{
  "error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE",
  "mode": "..."
}
```

When bridge mode is enabled, it must continue to delegate to `handle_internal_events_ingest()` and preserve existing response/status behavior for single events, batch events, duplicate events, invalid JSON, and empty batches.

### Recommendation and similar behavior must remain unchanged

`POST /recommendations`, `POST /videos/similar`, and `GET /videos/{id}/similar` must continue to use the current similar/recommendation execution path.

Concrete behavior that must remain stable:

- `GET /videos/{id}/similar` extracts `{id}` and sets it as the same internal `id` parameter before entering the similar path.
- Similar/recommendation POST routes still apply the current rate-limit behavior.
- Request bodies larger than `DEFAULT_CLIENT_LIKES_BODY_LIMIT` still return status `400` with `{"error": "Invalid JSON body"}`.
- Invalid JSON still returns status `400` with the current error string from `read_json_body()`.
- `/recommendations` still enforces `DEFAULT_CLIENT_LIKES_MAX` and malformed likes item errors through `_recommendations_likes_payload_error()` behavior.
- Client likes parsing still accepts only `{uuid, host}` entries and resolves them to Engine `video_id`, `video_uuid`, and `instance_domain` rows through the current DB query.
- `set_request_client_likes()` and `clear_request_context()` behavior remains current, including cleanup on errors.
- Debug requests still return status `403` with `{"error": "Debug mode is disabled"}` when debug is requested and `server.recommendations_debug_enabled` is false.
- Random feed, home feed, seed-with-embedding, vector search, serving moderation filtering, stable row projection, and debug metadata attachment remain current.
- `POST /recommendations` response shape remains:

```json
{
  "generatedAt": 1739700000000,
  "total": 100,
  "count": 10,
  "seed": null,
  "rows": []
}
```

Only dynamic values may vary.

### Request logging and rate limiting must remain unchanged

`SimilarHandler` must continue to own:

- `_get_client_ip()`;
- `_get_full_url()`;
- `_log_access_start()`;
- `log_message()`;
- `do_OPTIONS()`;
- route-level rate-limit checks using `server.rate_limiter` and the same `{ip}:{path}` key.

This is intentional remaining ownership after Stage 4. A future route/framework stage may revisit it; Stage 4 must not.

## Architecture

Stage 4 preserves the component boundary:

```text
Client backend -> Engine HTTP API -> Engine data/recommendation modules -> SQLite/index/cache
```

The Client backend must continue to call Engine over HTTP. Engine route extraction must not introduce new Client imports, Client DB reads, or frontend coupling.

### Current Engine API boundary

```text
engine/server/api/server.py
  -> SimilarServer runtime state
  -> SimilarHandler
      -> handlers/video.py
      -> handlers/internal_client_reads.py
      -> handlers/internal_events.py
      -> data/*
      -> recommendations/*
      -> http_utils.py
      -> request_context.py
```

### Target Stage 4 boundary

```text
engine/server/api/server.py
  -> SimilarServer runtime state
  -> SimilarHandler
      -> routes/*
          -> services/* where useful
          -> existing handlers/video.py and internal handlers where behavior already exists
          -> data/*
          -> recommendations/*
          -> http_utils.py
          -> request_context.py
```

### Required responsibility split

`server.py` remains responsible for:

```text
CLI parsing
runtime dependency loading
DB/cache/index connection
schema/index/cache startup helpers
recommendation strategy construction
SimilarServer state holder
signal/lifecycle handling
serve_forever()
```

`handlers/similar.py` remains responsible for:

```text
SimilarHandler class
request/access logging
CORS preflight dispatch
GET/POST route dispatch
rate-limit gate
calling route modules
```

`routes/*` become responsible for:

```text
route-specific request parsing
route-specific validation
route-specific status and response selection
calling existing data/domain handlers or services
```

`services/*` become responsible for:

```text
non-trivial Engine API behavior moved out of SimilarHandler
recommendation/similar execution orchestration
small pure or semi-pure helpers that are not HTTP dispatch
```

`engine/server/data/*` remains responsible for:

```text
SQLite reads/writes and data access helpers
```

`engine/server/api/recommendations/*` remains responsible for:

```text
recommendation candidate generation, filtering, scoring, mixing, and debug helpers
```

### Explicitly deferred work

Stage 4 must not do these tasks:

```text
FastAPI or any framework migration
OpenAPI or Pydantic schema introduction
recommendation algorithm redesign
recommendation config extraction or validation redesign
FAISS import/startup isolation
SQLite migration ownership changes
crawler/job changes
frontend changes
Client backend changes
public response shape normalization
broad lint or formatting cleanup
```

These are not gaps between stages. They are intentionally assigned to later stages:

```text
Stage 5: recommendation pipeline internals and config clarity
Stage 6: database schema/migration ownership
Stage 7: crawler split
Stage 8: frontend split
Stage 9: jobs/updater/deployment docs
Stage 10: optional framework migration
```

## Touched Files

```text
AGENTS.md
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/TESTING.md
engine/server/api/handlers/similar.py
engine/server/api/handlers/video.py
engine/server/api/handlers/internal_client_reads.py
engine/server/api/handlers/internal_events.py
engine/server/api/http_utils.py
engine/server/api/request_context.py
engine/server/api/server.py
engine/server/api/server_config.py
engine/server/api/recommendations/builder.py
engine/server/api/recommendations/debug.py
engine/server/api/recommendations/filters.py
engine/server/api/recommendations/mixer.py
engine/server/api/recommendations/profile.py
engine/server/api/recommendations/scoring.py
engine/server/data/channels.py
engine/server/data/embeddings.py
engine/server/data/metadata.py
engine/server/data/random_videos.py
engine/server/data/serving_moderation.py
engine/server/data/similarity_candidates.py
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
Makefile
pyproject.toml
plans/06_stage_4_engine_api_split.md
```

Stage 4 should only edit a subset of these files. Files are listed because the plan is based on their current behavior or because tests/docs/tooling may need to reference them. Do not edit `engine/server/data/*` or `engine/server/api/recommendations/*` unless a narrow import seam or behavior-preserving call move is impossible otherwise.

## New Files

```text
plans/06_stage_4_engine_api_split.md
engine/server/api/routes/__init__.py
engine/server/api/routes/health.py
engine/server/api/routes/channels.py
engine/server/api/routes/videos.py
engine/server/api/routes/internal_videos.py
engine/server/api/routes/internal_events.py
engine/server/api/routes/recommendations.py
engine/server/api/services/__init__.py
engine/server/api/services/recommendation_service.py
engine/server/api/services/channel_service.py
engine/server/api/services/video_service.py
tests/engine_api/test_engine_route_dispatch_characterization.py
tests/engine_api/test_channels_route_characterization.py
tests/engine_api/test_internal_video_routes_characterization.py
tests/engine_api/test_engine_ingest_mode_characterization.py
tests/engine_api/test_similar_route_characterization.py
docs/ENGINE_API_COMPATIBILITY.md
```

`channel_service.py` and `video_service.py` may remain thin wrappers if route extraction shows that the current behavior is already cleanly owned by `data.channels` or `handlers.video`. They must still have clear docstrings explaining their limited Stage 4 role. Do not create empty placeholder modules.

`docs/ENGINE_API_COMPATIBILITY.md` is required in Stage 4. It records the backward-compatibility decisions that the implementation actually preserves or introduces while splitting Engine routes. If Stage 4 adds no compatibility shims and only preserves existing contracts mechanically, the document must say that explicitly and list the preserved route-contract decisions.

## Implementation Steps

### 1. Re-run the current baseline before changing Engine code

Run:

```bash
make test
make lint
python3 client/backend/server.py --help
python3 engine/server/api/server.py --help
```

Expected:

- `make test` passes with the current Stage 3 suite.
- `make lint` passes for the current maintained surface.
- `client/backend/server.py --help` passes.
- `engine/server/api/server.py --help` may be blocked by missing `faiss`, because `server.py` imports `faiss` at module import time. If it is blocked, document that as the current known FAISS startup prerequisite rather than changing startup behavior in Stage 4.

Do not proceed with production refactor if the fast regression suite is already failing.

### 2. Add route-dispatch characterization tests before moving route logic

Add `tests/engine_api/test_engine_route_dispatch_characterization.py`.

Use a handler harness that imports `handlers.similar` with a fake `data.ann` module when FAISS is unavailable, mirroring the existing `tests/engine_api/test_recommendations_request_contract.py` approach. The harness may instantiate `SimilarHandler` through `object.__new__()` and provide the minimal fields/methods needed by `respond_json()`:

```text
path
command
headers
client_address
server
rfile
wfile
send_response()
send_header()
end_headers()
```

Test cases:

#### 2.1 GET unknown route

Given a handler with `path=/missing` and minimal server attributes.

When `do_GET()` runs.

Then response is status `404`:

```json
{"error": "Not found"}
```

#### 2.2 POST unknown route

Given `path=/missing`.

When `do_POST()` runs.

Then response is status `404`:

```json
{"error": "Not found"}
```

#### 2.3 OPTIONS route

Given any path.

When `do_OPTIONS()` runs.

Then the response preserves the current CORS preflight behavior from `respond_options()`.

#### 2.4 Rate limit behavior

Given a fake server with a rate limiter that rejects a key.

When `GET /api/health` or `GET /videos/123/similar` runs.

Then response is status `429` with:

```json
{"error": "Rate limit exceeded"}
```

This protects the route-level rate-limit gate before route extraction.

### 3. Add health and channel route characterization tests

Add `tests/engine_api/test_channels_route_characterization.py`.

Test cases:

#### 3.1 Health response

Given server attributes:

```text
embeddings_count = 42
embeddings_dim = 384
```

When `GET /api/health` runs through `SimilarHandler.do_GET()` or the extracted health route.

Then response is status `200` with:

```json
{"ok": true, "total": 42, "embeddingDim": 384}
```

#### 3.2 Channels query defaults and caps

Patch or fake `fetch_channels()` at the boundary used by the route.

Given:

```text
GET /api/channels?limit=9999&offset=bad&maxVideos=-1&q=abc&instance=example.org&sort=videos&dir=asc
```

When the route runs.

Then the fake `fetch_channels()` sees:

```text
limit = 500
offset = 0
query = "abc"
instance = "example.org"
max_videos = None
sort = "videos"
direction = "asc"
```

And response preserves:

```json
{"generatedAt": <int>, "total": <fake total>, "rows": <fake rows>}
```

#### 3.3 Invalid or missing limit defaults to 100

Given `limit=bad` or `limit=0`.

Then `fetch_channels()` sees `limit=100`.

### 4. Add internal video and ingest-mode characterization tests

Add `tests/engine_api/test_internal_video_routes_characterization.py`.

Cover the route adapter level, not only the existing helper functions:

- `POST /internal/videos/resolve` delegates to the current resolver and preserves status/body for missing identity and successful identity.
- `POST /internal/videos/metadata` delegates to the current metadata handler and preserves status/body for missing `entries`, empty valid entries, and valid rows.

Add `tests/engine_api/test_engine_ingest_mode_characterization.py`.

Test cases:

#### 4.1 Ingest disabled returns current 501 shape

Given:

```text
server.engine_ingest_mode = "activitypub"
path = /internal/events/ingest
```

When `do_POST()` runs.

Then response is status `501`:

```json
{
  "error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE",
  "mode": "activitypub"
}
```

#### 4.2 Ingest enabled delegates to current ingest handler

Given:

```text
server.engine_ingest_mode = "bridge"
```

When a valid event is posted to `/internal/events/ingest`.

Then the existing ingest response shape is preserved. This can reuse the same event fixture as `test_internal_events_ingest_characterization.py`.

### 5. Add similar/recommendation route characterization tests for uncovered behavior

Add `tests/engine_api/test_similar_route_characterization.py`.

These tests must protect behavior that Stage 0 did not fully cover before moving `_handle_similar_request()` and `_handle_similar()` out of `SimilarHandler`.

Required test cases:

#### 5.1 `/videos/{id}/similar` injects the path id

Patch the current similar execution boundary so no FAISS/index search is required.

Given:

```text
GET /videos/abc123/similar?limit=5
```

When route dispatch runs.

Then the similar execution receives params containing:

```python
{"id": ["abc123"], "limit": ["5"]}
```

This must be tested before extracting the `/videos/{id}/similar` route adapter.

#### 5.2 Debug disabled returns current 403

Given:

```text
GET /videos/abc123/similar?debug=1
server.recommendations_debug_enabled = False
```

When the similar route runs.

Then response is status `403`:

```json
{"error": "Debug mode is disabled"}
```

#### 5.3 Oversized POST body returns current Invalid JSON body error

Given:

```text
POST /recommendations
content-length > DEFAULT_CLIENT_LIKES_BODY_LIMIT
```

When the route runs.

Then response is status `400`:

```json
{"error": "Invalid JSON body"}
```

#### 5.4 Invalid recommendations likes payload still returns current validation error

Given malformed `likes` entries.

When `POST /recommendations` runs.

Then status/body match `_recommendations_likes_payload_error()` current behavior.

#### 5.5 Request context is cleared after recommendation errors

Given a POST route that sets request client likes and then triggers a controlled error.

When the route exits.

Then request context is cleared. If current request-context module does not expose a direct assertion-friendly getter, use an existing indirect behavior or keep this as a service-level test after extraction.

### 6. Create route modules and move route-specific behavior

Create:

```text
engine/server/api/routes/__init__.py
engine/server/api/routes/health.py
engine/server/api/routes/channels.py
engine/server/api/routes/videos.py
engine/server/api/routes/internal_videos.py
engine/server/api/routes/internal_events.py
engine/server/api/routes/recommendations.py
```

Route module responsibilities:

#### health.py

Move the `/api/health` response construction out of `SimilarHandler.do_GET()` into:

```python
def handle_health(handler: Any, server: Any) -> bool:
    ...
```

#### channels.py

Move `/api/channels` query parsing and `fetch_channels()` call into:

```python
def handle_channels(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    ...
```

Keep current `_parse_int()` and `_parse_non_negative_int()` semantics either by moving parse helpers to a shared utility module or importing them from a service/helper module. Do not duplicate behavior with subtly different parsing.

#### videos.py

Create a thin route adapter:

```python
def handle_video(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    return handle_video_request(handler, server, params)
```

Do not redesign `handlers/video.py` in Stage 4.

#### internal_videos.py

Create adapters around existing functions:

```python
def handle_internal_video_resolve_route(handler: Any, server: Any) -> bool:
    return handle_internal_video_resolve(handler, server)

def handle_internal_videos_metadata_route(handler: Any, server: Any) -> bool:
    return handle_internal_videos_metadata(handler, server)
```

Do not move DB logic out of `handlers/internal_client_reads.py` unless a narrow test requires it.

#### internal_events.py

Move the `engine_ingest_mode` gate out of `SimilarHandler.do_POST()` into a route adapter:

```python
def handle_internal_events_ingest_route(handler: Any, server: Any) -> bool:
    if getattr(server, "engine_ingest_mode", "bridge") != "bridge":
        respond_json(...)
        return True
    return handle_internal_events_ingest(handler, server)
```

#### recommendations.py

Move POST route parsing, `/videos/{id}/similar` path-id handling, and similar/recommendation route dispatch out of `SimilarHandler` into route-level functions.

Suggested route functions:

```python
def handle_similar_post(handler: Any, server: Any, method: str = "POST") -> bool:
    ...

def handle_similar_get(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    ...

def extract_video_id_from_similar_path(path: str) -> str | None:
    ...
```

Keep function names implementation-specific if clearer, but keep the route/service boundary explicit.

### 7. Create Engine API service modules for moved non-dispatch behavior

Create:

```text
engine/server/api/services/__init__.py
engine/server/api/services/recommendation_service.py
engine/server/api/services/channel_service.py
engine/server/api/services/video_service.py
```

Required behavior movement:

#### recommendation_service.py

Move non-dispatch recommendation helpers out of `SimilarHandler`:

```text
stable_video_row()
stable_video_rows()
maybe_attach_debug()
_parse_client_likes()
_recommendations_likes_payload_error()
_resolve_client_likes()
fetch_random_rows_from_server()
respond_rows() or build_rows_response_payload()
handle_random/home/seed/vector/similar execution functions
parse bool/int helpers if they are recommendation-route specific
```

Acceptable Stage 4 options:

- Keep response writing in the route module and expose service functions that return payload/status tuples.
- Or keep a thin service that accepts `handler` and `server` while moving the large behavior out of `SimilarHandler`.

Prefer the first option when it can be done without semantic churn. Use the second option if preserving behavior exactly is safer. In either case, `SimilarHandler` must no longer contain the large `_handle_*` recommendation methods.

Do not change the recommendation algorithm, candidate sources, scoring, mixing, fallback, debug metadata, or row fields.

#### channel_service.py

If `/api/channels` route parsing remains more than trivial, move query parsing into a small service:

```python
@dataclass(frozen=True)
class ChannelQuery:
    ...

def parse_channel_query(params: dict[str, list[str]]) -> ChannelQuery:
    ...
```

If the route module is already clear, `channel_service.py` can be omitted from implementation despite being listed as a candidate new file. Do not create an empty module.

#### video_service.py

Only create this module if the implementation needs a thin service wrapper for video route behavior. Otherwise, leave video behavior in `handlers/video.py` and keep `routes/videos.py` as the adapter. Do not create an empty module.

### 8. Reduce `SimilarHandler` to routing/composition

After route/service extraction, `SimilarHandler` should retain:

```text
_get_client_ip()
_get_full_url()
_log_access_start()
log_message()
do_OPTIONS()
do_GET()
do_POST()
_rate_limit_check()
```

It may also retain tiny compatibility helpers only if moving them would increase risk. It must not retain:

```text
channel query parsing
health response construction
internal ingest mode response construction
Client likes payload validation
Client likes DB resolution
random/home/seed/vector recommendation execution
stable row projection/debug attach logic
/videos/{id}/similar path-id extraction logic
```

If implementation cannot move one of these items without changing behavior, do not move that item in Stage 4. Leave it in `SimilarHandler`, add a comment explaining the retained compatibility responsibility if the code is non-obvious, and keep the relevant route/service boundary tests green. Do not invent a new extraction strategy during implementation.

### 9. Update docs for internal Engine API structure

Read the purpose section before editing each document.

Update `docs/ARCHITECTURE.md` Engine API section to state that:

```text
engine/server/api/handlers/similar.py is now the stdlib HTTP adapter and route dispatcher.
engine/server/api/routes/ owns Engine route-specific request/response adapters.
engine/server/api/services/ owns Engine API orchestration that is not pure data access or recommendation domain logic.
engine/server/data/ remains data access.
engine/server/api/recommendations/ remains recommendation domain logic.
```

Update `docs/DEVELOPMENT.md` Main Areas to include:

```text
engine/server/api/routes
engine/server/api/services
```

Update `docs/TESTING.md` Python behavior tests or linting section only if Stage 4 changes the maintained lint surface or adds new Engine route tests.

Do not edit unrelated docs.

### 10. Update tooling surface only if needed

If new Engine route/service modules are added, update `Makefile` `lint` target to include the new maintained Engine API surface:

```text
engine/server/api/routes
engine/server/api/services
```

Do not broaden lint to all legacy Engine API code unless the implementation explicitly cleans it. Lint should remain narrow and maintained-surface only.

### 11. Run verification

Required checks:

```bash
make test
make lint
```

Also run targeted checks while developing:

```bash
python3 -m pytest tests/engine_api -q
python3 -m pytest tests/recommendations tests/engine_data -q
python3 -m compileall engine/server/api engine/server/data
```

Run server CLI help only if the environment has FAISS or if server import is still expected to fail because of the known FAISS prerequisite:

```bash
python3 engine/server/api/server.py --help
```

If it fails because `faiss` is missing, record it as an unchanged known prerequisite. Do not solve FAISS startup isolation in Stage 4.

### 12. Non-negotiable implementation constraints

Stage 4 must be executable without changing this plan during implementation. The following cases are not open-ended stop conditions; each has a concrete required action. If the required action cannot be followed, the implementation is out of Stage 4 scope and must stop without modifying the affected production path.

#### 12.1 Recommendation extraction cannot change output behavior

Constraint:

```text
Moving recommendation execution out of SimilarHandler must not change output rows, debug fields, candidate ordering, fallback behavior, total/count/seed semantics, or error behavior.
```

Required action:

```text
Move only behavior that can be transferred mechanically with existing tests green. If a specific recommendation helper cannot be moved without changing behavior, leave that helper in SimilarHandler for Stage 4 and route through it from routes/recommendations.py. Add a short compatibility comment if the retained helper is non-obvious. Do not redesign recommendation execution; Stage 5 owns that work.
```

#### 12.2 Route tests must not require production routing changes

Constraint:

```text
Route characterization tests must not force changes to production routing semantics.
```

Required action:

```text
Use a handler harness, fake server object, fake rfile/wfile, and existing response helpers. If a route cannot be tested through SimilarHandler without changing production semantics, test the extracted route function directly after adding the route module, and keep at least one dispatch-level test for unknown routes, OPTIONS, and rate limiting.
```

#### 12.3 FAISS isolation is out of scope

Constraint:

```text
Stage 4 must not introduce FAISS import/startup isolation or change server.py startup dependency loading.
```

Required action:

```text
For tests, inject fake optional modules at the test import boundary, as Stage 0 tests already do. Do not edit server.py to make FAISS optional. If an Engine route module import would require FAISS only because it imports server.py, change the route module import path so it imports the narrow handler/service/data modules instead of server.py.
```

#### 12.4 No new public schema layer

Constraint:

```text
Extracted routes must not introduce new public request/response schemas, Pydantic models, OpenAPI objects, or validation policies.
```

Required action:

```text
Keep current dict/list payload handling and existing helper validation. Internal dataclasses are allowed only for private service boundaries when they do not alter accepted input, rejected input, status codes, or response shape.
```

#### 12.5 No Client/frontend coupling

Constraint:

```text
Engine route or service modules must not import Client backend code, frontend code, or Client-owned storage.
```

Required action:

```text
Keep all Client-to-Engine communication as HTTP contract behavior. If an extracted Engine service appears to need Client code, pass the already-received request payload or server state into the Engine service instead. Preserve the existing boundary tests.
```

#### 12.6 No data access SQL changes

Constraint:

```text
Channel, video, internal-video, recommendation, and event route extraction must not require SQL changes.
```

Required action:

```text
Continue calling existing engine/server/data/* functions and existing handlers that already own DB behavior. If a route extraction seems to require SQL modification, leave that DB behavior in its current data/handler module and add only a route adapter around it. Stage 6 owns schema and migration work.
```

#### 12.7 No server startup rewiring

Constraint:

```text
server.py startup wiring, CLI behavior, runtime state creation, FAISS/index loading, cache initialization, and signal handling must remain unchanged.
```

Required action:

```text
Route modules receive the existing server object and use its current attributes. Do not move construction of DB connections, indexes, recommendation strategy, rate limiter, random cache, moderation schema, interaction schema, or logging profile. If a route needs new state, derive it from current server attributes or keep the behavior in SimilarHandler.
```

#### 12.8 Existing regression failures must be resolved before refactor work

Constraint:

```text
Existing Stage 0/3 tests must not be failing for reasons unrelated to the Engine API split before production refactor begins.
```

Required action:

```text
Run make test and make lint first. If they fail before Engine changes, fix only the test/environment issue when it is inside the maintained Stage 4 tooling surface, or stop without touching Engine production code if the failure is unrelated to this stage.
```

#### 12.9 Data and recommendation internals remain owned by later stages

Constraint:

```text
Stage 4 must not edit engine/server/data/* or engine/server/api/recommendations/* beyond narrow import-path adjustments needed by moved route/service code.
```

Required action:

```text
If route extraction requires changing data or recommendation internals, keep the route adapter thin and call the existing function in place. Move the deeper change to Stage 5 for recommendation internals or Stage 6 for data/schema ownership.
```

## Tests

Stage 4 is a behavior-preserving refactor. Tests must be added before moving the corresponding route behavior.

### Existing required baseline

```bash
make test
make lint
```

### Existing tests that must remain green

```text
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
```

### New Stage 4 tests

```text
tests/engine_api/test_engine_route_dispatch_characterization.py
tests/engine_api/test_channels_route_characterization.py
tests/engine_api/test_internal_video_routes_characterization.py
tests/engine_api/test_engine_ingest_mode_characterization.py
tests/engine_api/test_similar_route_characterization.py
docs/ENGINE_API_COMPATIBILITY.md
```

These are required because Stage 4 moves route behavior that Stage 0 did not fully cover at route-dispatch level.

### Test strategy

- Use pytest.
- Use handler harnesses and fake server objects for Engine route tests.
- Use fake `data.ann` only as an import seam when FAISS is unavailable.
- Use temporary SQLite databases for DB-backed internal route assertions.
- Patch only outer boundaries or heavy optional dependencies.
- Assert HTTP status, response body, route params, DB rows, request-context cleanup, and response shape.
- Do not assert that internal mocks were called unless the assertion is used to verify a route boundary and no better observable result exists.

### 13. Record Engine API backward-compatibility decisions

Create or update `docs/ENGINE_API_COMPATIBILITY.md` during Stage 4. The document must have this purpose statement at the top:

```text
This document records Engine API backward-compatibility decisions that are preserved or introduced during route and service refactors. It is not a public API reference; it explains compatibility constraints that future refactors must not accidentally remove.
```

Record every compatibility decision that Stage 4 relies on or implements. At minimum, include entries for these preserved decisions if the implementation touches the relevant route path:

```text
Decision: /videos/{id}/similar keeps path-id injection into the same internal similar-request path.
Reason: Client/frontend behavior and existing smoke checks expect path-based similar lookup to behave like query/body-based similar lookup.
Implementation action: Keep the path-id adaptation in the HTTP adapter or routes/recommendations.py before calling recommendation_service.
Tests: tests/engine_api/test_similar_route_characterization.py.

Decision: /internal/events/ingest keeps the ENGINE_INGEST_MODE gate and current 501 response when bridge ingest is disabled.
Reason: Existing deployments can disable bridge ingest without changing route availability.
Implementation action: Preserve the mode check in routes/internal_events.py before calling the ingest handler/service.
Tests: tests/engine_api/test_engine_ingest_mode_characterization.py.

Decision: recommendation request validation keeps current body-size, likes-count, malformed-likes, and debug-disabled behavior.
Reason: Client backend and Stage 0 tests depend on these request-contract failures remaining stable during route split.
Implementation action: Reuse current validation helpers; do not replace them with new schema validation in Stage 4.
Tests: tests/engine_api/test_recommendations_request_contract.py and tests/engine_api/test_engine_route_dispatch_characterization.py.

Decision: dynamic video metadata overlay remains owned by handlers/video.py or a thin video service wrapper without changing response shape.
Reason: The frontend video page depends on current DB fallback and dynamic PeerTube metadata override behavior.
Implementation action: Route extraction must delegate to the existing video handler/helper path.
Tests: tests/engine_api/test_video_metadata_characterization.py.
```

If implementation introduces a compatibility shim, adapter, fallback, retained helper, or intentionally duplicated route mapping, add a new entry with the same fields:

```text
Decision:
Reason:
Implementation action:
Tests:
Removal condition, if any:
```

Do not document vague compatibility intent. Document only concrete behavior and the implementation action that preserves it. If a compatibility behavior is deliberately not implemented in Stage 4, the document must say why it remains out of scope and identify the stage that owns it.

## Documentation Maintenance

Stage 4 affects internal Engine API structure, not product architecture or public HTTP contracts.

Update only:

```text
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/TESTING.md
docs/ENGINE_API_COMPATIBILITY.md
```

`docs/ENGINE_API_COMPATIBILITY.md` is mandatory for Stage 4 because route extraction preserves several compatibility-sensitive Engine API behaviors. It must record the concrete compatibility decision, the reason, the implementation action, and the tests for every preserved or newly introduced compatibility behavior.

Do not update deployment, data-build, crawler, frontend, or Client backend docs. If implementation appears to require such an update, do not make the Engine route extraction change that caused it; keep the affected behavior in its current owner for Stage 4 and document the deferral in `docs/ENGINE_API_COMPATIBILITY.md` only if a compatibility decision was actually retained.

## Remaining Ownership After Stage 4

After Stage 4, it is intentional that `engine/server/api/server.py` still owns runtime startup and FAISS/index loading. This is not a gap; startup isolation and dependency splitting are separate future work.

After Stage 4, it is intentional that `engine/server/api/handlers/similar.py` still contains the `SimilarHandler` class and request logging/rate-limit glue. This is not a gap; route modules and services should own behavior, while the handler remains the stdlib HTTP adapter until a future framework migration or handler-cleanup stage.

After Stage 4, it is intentional that `engine/server/api/recommendations/*` still owns recommendation internals. Stage 4 may call those modules through a service, but it must not redesign them. Recommendation pipeline clarification belongs to Stage 5.

After Stage 4, it is intentional that `engine/server/data/*` still owns data access. DB migration ownership belongs to Stage 6.

No Engine API route behavior should remain unowned:

```text
health -> routes/health.py
channels -> routes/channels.py plus optional services/channel_service.py
video -> routes/videos.py -> handlers/video.py or services/video_service.py
internal video reads -> routes/internal_videos.py -> handlers/internal_client_reads.py
internal event ingest -> routes/internal_events.py -> handlers/internal_events.py
recommendations/similar -> routes/recommendations.py -> services/recommendation_service.py -> recommendations/data modules
request logging/rate limit/dispatch -> handlers/similar.py
startup/runtime state -> server.py
```

## Regression and Blind-Spot Analysis

### Regressions Stage 4 must catch

- `GET /videos/{id}/similar` stops injecting the path id into similar params.
- `/internal/events/ingest` stops returning the current `501` shape when ingest mode is not `bridge`.
- Recommendation POST routes stop enforcing body-size, likes-count, or malformed likes validation.
- Request context leaks between recommendation requests after exceptions.
- Debug-disabled requests stop returning `403`.
- Channel route parsing changes default/cap behavior.
- Health response shape changes.
- Video route errors or dynamic metadata merge behavior change.
- Internal video resolve/metadata routes change status or body shape.
- Rate-limit checks move to the wrong path key or disappear for `/api/*` and `/videos/{id}/similar`.
- Similar response rows change stable fields, debug fields, ordering, fallback behavior, or total/count/seed semantics.
- Route extraction accidentally imports Client backend modules or reads Client DB files.
- `server.py` startup behavior changes while trying to split routes.
- Compatibility shims or retained helpers are added without being documented in `docs/ENGINE_API_COMPATIBILITY.md`.

### Blind spots that remain after Stage 4

- Recommendation quality and config validation remain only characterized at current level. Stage 5 owns deeper recommendation model/config cleanup.
- FAISS import/startup isolation remains unresolved. It is a known prerequisite and future dependency/startup concern.
- DB schema ownership remains distributed. Stage 6 owns migrations and schema source of truth.
- Crawler output behavior remains unchanged but not further split. Stage 7 owns crawler responsibilities.
- Frontend route consumption remains protected by existing boundary/behavior tests but is not refactored. Stage 8 owns frontend code structure.
- Full production smoke with real index/cache may still require local data artifacts not available in every environment.

## Compatibility and Protocol Notes

Generic behavior:

- Route extraction is a generic behavior-preserving refactor.
- Handler harness tests and temporary SQLite databases are generic regression-test techniques.
- Keeping startup and framework unchanged while moving route behavior is a generic incremental refactoring pattern.

Project-specific behavior:

- Engine API routes are project-specific HTTP contracts consumed by the Client backend and frontend through the Client gateway.
- Client likes payload parsing for recommendations is project-specific compatibility behavior.
- The internal event ingest mode gate is a project-specific bridge compatibility behavior, not generic ActivityPub behavior.
- Recommendation scoring, fallback, row projection, and debug metadata are project-specific product behavior.
- PeerTube dynamic video metadata overlay is PeerTube-specific behavior because it queries PeerTube instance APIs.

## Open Questions

None for the current Stage 4 scope.
