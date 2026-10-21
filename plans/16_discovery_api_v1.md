# Discovery API v1

## Problem / Goal

The project currently exposes discovery behavior through legacy, mixed-level routes:

```text
Client backend public/read gateway:
  POST /recommendations
  POST /videos/similar
  GET  /api/video
  GET  /api/channels

Engine read routes used behind the gateway:
  POST /recommendations
  POST /videos/similar
  GET  /videos/{id}/similar
  GET  /api/video
```

The frontend currently renders feeds through `client/frontend/src/data/videos.ts`, which builds `POST /recommendations` requests and uses query flags such as `random=1`. The video page fetches metadata from `GET /api/video`. This works, but the route names and payload shapes are legacy compatibility contracts, not a clean browser-facing Discovery API.

The project architecture says the browser-facing API belongs to the Client backend, while Engine owns recommendation/discovery computation and data access. The next feature should therefore introduce Discovery API v1 as a Client-backend public API and keep Engine routes as implementation/provider details.

Goal: add a browser-facing Discovery API v1 in the Client backend, switch the frontend to that API, and preserve Engine ownership of recommendation computation and Engine-readable datasets.

Target runtime boundary:

```text
Frontend
  -> Client backend /api/v1/... public Discovery API
    -> Engine HTTP routes / internal provider routes
      -> Engine DB/index/cache/recommendation layers
```

This plan must not make the frontend call Engine directly, must not make Client backend import Engine modules or read Engine DB files, and must not expose `video_index_ids.index_id` or other index-artifact internals.

## Expected Behavior

### Public Client backend v1 routes

Add these browser-facing routes to `client/backend/app.py`:

```text
GET /api/v1/discovery/random
GET /api/v1/discovery/fresh
GET /api/v1/discovery/popular
GET /api/v1/discovery/recommendations
GET /api/v1/videos/{id}
GET /api/v1/videos/{id}/similar
```

The frontend should use these v1 routes through `resolveClientApiBase(...)`. It must not call Engine read/internal routes directly.

### Video identity contract

For video-resource routes:

```text
GET /api/v1/videos/{id}?host={instance_domain}
GET /api/v1/videos/{id}/similar?host={instance_domain}
```

Rules:

- `{id}` may be either `video_id` or `video_uuid`.
- `host` is required.
- Client backend forwards `id + host` to Engine and lets Engine resolve the current canonical video identity.
- Response video rows must include at least:

```text
video_id
video_uuid
instance_domain
```

The v1 API does not attempt a uuid-only project-wide identity migration. Add that follow-up to `dev/FUTURE_TASKS.md`.

### List response envelope

All list/discovery endpoints must return the same envelope shape:

```json
{
  "items": [],
  "pagination": {
    "limit": 20,
    "next_cursor": null,
    "has_more": false
  },
  "meta": {
    "source": "recommendations",
    "fallback": false
  }
}
```

Applies to:

```text
/api/v1/discovery/random
/api/v1/discovery/fresh
/api/v1/discovery/popular
/api/v1/discovery/recommendations
/api/v1/videos/{id}/similar
```

`GET /api/v1/videos/{id}` returns a single normalized video object, not a list envelope.

### Cursor pagination

Use cursor pagination for v1 list routes.

Request parameters:

```text
limit=<positive integer>
cursor=<opaque string, optional>
debug=1 optional, only if the underlying Engine route supports debug and Engine allows it
```

Response pagination:

```json
{
  "limit": 20,
  "next_cursor": "opaque-string-or-null",
  "has_more": true
}
```

Cursor rules:

- Cursor is opaque to frontend code.
- Frontend must only store/pass it back.
- Client backend owns cursor parsing/validation.
- Invalid cursor returns `400` with a v1 error payload.
- Cursor payload must include the feed/resource kind so a cursor issued for `popular` cannot be reused against `fresh` or `similar`.

Initial implementation may use a simple signed-or-encoded JSON cursor owned by Client backend. It must not expose Engine DB row ids, FAISS/index ids, or SQL details.

### Feed semantics

`GET /api/v1/discovery/recommendations`:

- Public method is `GET`.
- Frontend sends no recommendation profile body.
- Client backend reads local user likes for the resolved user id.
- Client backend calls existing Engine `POST /recommendations` with sanitized likes and `user_id`.
- If the user has no likes, do not create a new fallback algorithm in Client backend. Reuse existing Engine guest-profile behavior (`guest_home`) and current Engine random fallback.

`GET /api/v1/discovery/random`:

- Returns discovery rows sourced from Engine random behavior.
- It may call existing Engine `POST /recommendations?random=1` or a new internal Engine provider route if that keeps the implementation cleaner.

`GET /api/v1/discovery/fresh` and `GET /api/v1/discovery/popular`:

- Client backend must not read Engine DB.
- Engine must provide HTTP-accessible provider behavior for these feeds.
- Prefer adding internal Engine provider routes instead of exposing them as public browser API:

```text
GET /internal/discovery/fresh
GET /internal/discovery/popular
```

These provider routes can use existing Engine data helpers:

```text
engine/server/data/random_videos.py::fetch_recent_videos
engine/server/data/random_videos.py::fetch_popular_videos
```

The Client backend v1 route converts Engine provider responses into the v1 envelope.

`GET /api/v1/videos/{id}/similar`:

- Requires `host`.
- Uses existing Engine similar behavior behind the Client backend.
- The response is the v1 list envelope.
- `similarity_cache`/ANN fallback behavior remains owned by Engine.

### Frontend behavior

The feed page should load through v1 routes:

```text
recommendations mode -> GET /api/v1/discovery/recommendations
random mode          -> GET /api/v1/discovery/random
similar page/feed    -> GET /api/v1/videos/{id}/similar?host=...
```

The video page should load metadata through:

```text
GET /api/v1/videos/{id}?host=...
```

The existing PeerTube instance metadata fallback on the video page may remain as a PeerTube-specific fallback when Client/Engine metadata is unavailable. Do not remove it in this plan unless tests prove the v1 route fully replaces that behavior.

The frontend must still support current rendering fields while moving to the v1 response envelope:

```text
old rows payload: { rows: [...] }
new list payload: { items: [...], pagination: {...}, meta: {...} }
```

Implementation should update frontend data adapters so rendering code receives `VideoRow[]` without duplicating envelope parsing across pages.

## Architecture

### Ownership

Client backend owns:

- public `/api/v1/...` routes;
- user id resolution;
- reading local likes from `UsersRepository`;
- converting local likes into Engine recommendation payloads;
- v1 response envelope and error shape;
- opaque cursor parsing/encoding;
- frontend-facing route compatibility.

Engine owns:

- recommendation computation;
- similar-candidate generation;
- metadata lookup;
- random/fresh/popular data retrieval from Engine-readable DB/artifacts;
- filtering unusable/moderated rows;
- index/cache availability and fallback behavior.

Frontend owns:

- UI state;
- infinite/dynamic loading;
- calling Client backend v1 routes only;
- rendering v1 envelopes through typed data helpers.

### Client backend v1 module split

Do not place all v1 behavior directly in `client/backend/app.py`.

Add a small service/module split:

```text
client/backend/services/discovery_v1.py
  - parse limit/cursor/debug/host query rules
  - build v1 envelopes
  - build v1 error payloads
  - call Engine through HTTP helpers
  - fetch local likes from UsersRepository for recommendations

client/backend/lib/engine_api_client.py
  - add GET helper for Engine JSON routes
  - add helper wrappers for Engine /api/video, /recommendations, /videos/{id}/similar, and internal discovery providers
```

`client/backend/app.py` should only do route registration, rate-limit checks, request parameter extraction, and response serialization through existing `cors_json(...)` helpers.

### Engine provider module split

If fresh/popular provider routes are added, keep them framework-neutral like current Engine route services:

```text
engine/server/api/routes/internal_discovery.py
engine/server/api/services/discovery_service.py
```

`engine/server/api/app.py` should register the internal routes and delegate to route-result builders.

The provider response shape may stay Engine-internal and simple, for example:

```json
{
  "rows": [],
  "generatedAt": 1710000000000,
  "source": "fresh"
}
```

Client backend v1 is responsible for converting that into:

```json
{
  "items": [],
  "pagination": {...},
  "meta": {...}
}
```

### Cursor implementation

Implement cursor ownership in Client backend, not Engine, unless a feed naturally needs Engine-side seek pagination.

Recommended v1 cursor format:

```json
{
  "v": 1,
  "kind": "recommendations|random|fresh|popular|similar",
  "offset": 20,
  "seed": {
    "id": "...",
    "host": "..."
  }
}
```

Encode with URL-safe base64 JSON. The first v1 implementation does not need cryptographic signing unless the project already has a signing utility. It must validate all fields after decoding and reject malformed/mismatched cursors with `400`.

Fetch strategy for first v1:

- For recommendations/similar: call Engine with `limit = offset + requested_limit + 1`, then slice in Client backend.
- For random: use the same offset cursor shape only to produce a continuation token; each call may request a fresh random batch because random feeds are not an ordered stable collection. Document this in comments/tests. If this is unacceptable later, add a future task for deterministic random-session cursors.
- For fresh/popular: provider route may accept `limit = offset + requested_limit + 1` initially and Client backend slices, or Engine provider can support seek cursors internally. Prefer the simpler client-side slicing unless performance proves it inadequate.

This is not perfect for very large offsets, but it keeps v1 implementation simple and avoids leaking DB-specific cursor state. Add future tasks if a stronger cursor model is needed.

### Error shape

Use a consistent v1 error shape for new Client v1 routes:

```json
{
  "error": "human-readable message",
  "code": "V1_DISCOVERY_BAD_REQUEST"
}
```

Minimum codes:

```text
V1_DISCOVERY_BAD_REQUEST       invalid limit/cursor/query
V1_DISCOVERY_MISSING_HOST      video route missing host
V1_DISCOVERY_ENGINE_UNAVAILABLE Engine transport/upstream failure
V1_DISCOVERY_NOT_FOUND         Engine video metadata/similar seed not found when applicable
```

Do not change legacy route error shapes for `/recommendations`, `/videos/similar`, `/api/video`, or `/api/channels`.

### Compatibility policy

Keep legacy routes working during this milestone:

```text
POST /recommendations
POST /videos/similar
GET  /api/video
GET  /api/channels
```

Do not remove old routes until frontend has been switched, tests pass, and a later cleanup plan explicitly removes them.

Do not expose Engine `/api/v1/...` as browser API. Engine may gain internal provider routes, but Client backend remains the only public Discovery API v1 owner.

## Touched Files

```text
client/backend/app.py
client/backend/lib/engine_api_client.py
client/backend/services/engine_gateway.py
client/backend/services/profile.py
client/frontend/src/data/videos.ts
client/frontend/src/types/videos.ts
client/frontend/src/pages/videos/index.ts
client/frontend/src/pages/video-page/index.ts
client/frontend/src/api/client.ts
client/frontend/src/utils/video-fields.ts
engine/server/api/app.py
engine/server/api/routes/__init__.py
engine/server/data/random_videos.py
README.md
docs/ARCHITECTURE.md
docs/FRONTEND_COMPATIBILITY.md
docs/ENGINE_API_COMPATIBILITY.md
docs/diagram/overview.md
client/README.md
client/frontend/README.md
engine/server/README.md
dev/FUTURE_TASKS.md
tests/client_backend/conftest.py
tests/client_backend/test_read_proxy_characterization.py
tests/client_backend/test_read_proxy_failure_characterization.py
tests/engine_api/conftest.py
tests/engine_api/test_engine_route_dispatch_characterization.py
tests/engine_data/test_random_recent_popular_characterization.py
tests/check-client-engine-boundary.sh
tests/check-frontend-client-gateway.sh
client/frontend/test/data/client-api-boundary.test.ts
client/frontend/test/pages/video-page-like-action.test.ts
```

Some touched files may not need changes if implementation keeps behavior isolated, but the implementation must verify each listed boundary before claiming the plan is complete.

## New Files

```text
client/backend/services/discovery_v1.py
engine/server/api/routes/internal_discovery.py
engine/server/api/services/discovery_service.py
tests/client_backend/test_discovery_v1_api.py
tests/engine_api/test_internal_discovery_routes.py
client/frontend/test/data/discovery-v1-api.test.ts
client/frontend/test/pages/videos-discovery-v1.test.ts
```

If implementation can avoid new Engine provider routes by safely reusing existing Engine routes for all v1 feeds, do not create `internal_discovery.py` or `discovery_service.py`. In that case the plan implementation must explain which existing Engine HTTP route covers `fresh` and `popular`; current code suggests new provider routes are likely needed.

## Implementation Steps

### 1. Add Client v1 discovery service tests first

Add `tests/client_backend/test_discovery_v1_api.py` with fake Engine routes and temporary Client DB fixtures.

Required scenarios:

1. `GET /api/v1/discovery/recommendations` reads local likes and calls Engine `POST /recommendations`.

   Setup:

   - insert local likes through `UsersRepository.record_like(...)` or the existing user-action route;
   - fake Engine expects `POST /recommendations`;
   - request `GET /api/v1/discovery/recommendations?limit=2&user_id=u1`.

   Assert:

   ```text
   status == 200
   body.items == [projected Engine rows]
   body.pagination.limit == 2
   body.meta.source == "recommendations"
   fake Engine body.likes contains uuid/host pairs from local likes
   frontend did not send a POST body
   ```

2. `GET /api/v1/discovery/recommendations` with no likes still calls Engine and returns guest/fallback rows in the same envelope.

   Assert `meta.fallback` is true only if the Engine seed/random payload indicates fallback. If that signal is not available from current Engine response, set `meta.fallback` conservatively based on local likes being empty and document that it means “no local user signals”, not necessarily “Engine fell back”.

3. `GET /api/v1/videos/{id}` requires `host`.

   Assert missing host returns:

   ```json
   {"error": "Missing host", "code": "V1_DISCOVERY_MISSING_HOST"}
   ```

4. `GET /api/v1/videos/{id}?host=example.org` calls Engine `GET /api/video?id=<id>&host=example.org` and returns a single video object containing `video_id`, `video_uuid`, and `instance_domain`.

5. `GET /api/v1/videos/{id}/similar?host=example.org` calls Engine similar behavior and returns `items + pagination + meta`.

6. Unknown query parameters on v1 routes return `400` and do not reach Engine.

7. Invalid cursor returns `400` and does not reach Engine.

8. Cursor from one feed cannot be reused on another feed.

### 2. Add Engine internal discovery provider tests if fresh/popular need new routes

Add `tests/engine_api/test_internal_discovery_routes.py`.

Required scenarios:

```text
GET /internal/discovery/fresh?limit=2
  -> returns rows from fetch_recent_videos path

GET /internal/discovery/popular?limit=2
  -> returns rows from fetch_popular_videos path

GET /internal/discovery/fresh?limit=bad
  -> uses existing positive-int default/bounds behavior or returns 400, whichever the service defines explicitly
```

Use the existing Engine API test harness and small SQLite fixtures similar to `tests/engine_data/test_random_recent_popular_characterization.py`.

Do not expose these provider routes in frontend documentation as browser-facing API.

### 3. Implement Client backend Engine JSON helpers

In `client/backend/lib/engine_api_client.py`:

1. Add `_get_json(url, timeout=...)` matching `_post_json(...)` behavior.
2. Add helper wrappers:

   ```python
   fetch_engine_video(engine_base_url, video_id_or_uuid, host)
   fetch_engine_similar(engine_base_url, video_id_or_uuid, host, limit, debug=False)
   fetch_engine_recommendations(engine_base_url, likes, user_id, limit, debug=False)
   fetch_engine_random(engine_base_url, limit, debug=False)
   fetch_engine_fresh(engine_base_url, limit)
   fetch_engine_popular(engine_base_url, limit)
   ```

3. Keep helpers HTTP-only. Do not import Engine modules.
4. Preserve existing `EngineApiError` behavior for transport errors.
5. For HTTP 404, return a typed result or raise an error that `discovery_v1.py` can map to `V1_DISCOVERY_NOT_FOUND`.

### 4. Implement Client backend v1 service

Create `client/backend/services/discovery_v1.py`.

Responsibilities:

- parse and bound `limit`;
- validate allowed query parameters per route;
- require `host` for video resource routes;
- parse/validate/encode cursor;
- fetch local likes from `UsersRepository` for recommendations;
- call Engine API helpers;
- normalize Engine row envelopes into v1 responses;
- build v1 error payloads.

Limit rules:

```text
default: 20
min: 1
max: 50
```

Cursor rules:

```text
missing cursor -> offset 0
valid cursor -> offset from cursor
next_cursor -> encoded offset + len(returned_items) when Engine returned more than requested_limit
```

For recommendations/similar/fresh/popular, request `offset + limit + 1` rows from Engine, slice locally, and set `has_more` based on whether there was an extra row.

For random, request `limit + 1` rows on each call. Return `next_cursor` when an extra row exists, but do not promise stable random ordering across cursor calls. Add a comment explaining that random is a continuous feed, not a stable ordered collection.

V1 envelope builder example:

```python
{
    "items": rows[:limit],
    "pagination": {
        "limit": limit,
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
    },
    "meta": {
        "source": source,
        "fallback": fallback,
        **optional_fields,
    },
}
```

### 5. Register Client backend v1 routes

In `client/backend/app.py`, add route handlers before the catch-all:

```text
GET /api/v1/discovery/random
GET /api/v1/discovery/fresh
GET /api/v1/discovery/popular
GET /api/v1/discovery/recommendations
GET /api/v1/videos/{video_ref}
GET /api/v1/videos/{video_ref}/similar
```

Use existing rate limiting:

```python
_rate_limit_or_none(state, request, request.url.path)
```

Use `resolve_user_id(...)` for optional `user_id` / `userId` query parameters in recommendations, matching existing Client behavior.

Return via `cors_json(...)`.

Do not route these through `proxy_engine_request(...)` as raw byte proxy responses. V1 routes are a Client-owned public contract and must normalize response envelopes.

### 6. Add Engine internal discovery routes for fresh/popular

If not avoidable through existing Engine HTTP routes, add:

```text
GET /internal/discovery/fresh
GET /internal/discovery/popular
```

Implementation:

- parse `limit` with the same basic positive-int semantics used by recommendation routes;
- clamp to `server.default_limit` or a dedicated safe max;
- call `fetch_recent_videos(...)` / `fetch_popular_videos(...)` under `server.db_lock`;
- apply serving moderation filters before returning rows;
- project rows through `stable_video_rows(...)` from `recommendation_service.py` to keep row fields consistent;
- return a simple Engine-internal payload:

```json
{
  "generatedAt": 1710000000000,
  "source": "fresh",
  "rows": []
}
```

Do not add `/api/v1/...` routes to Engine.

### 7. Update frontend data layer

In `client/frontend/src/types/videos.ts`, add v1 envelope types:

```ts
export interface DiscoveryPagination {
  limit: number;
  next_cursor: string | null;
  has_more: boolean;
}

export interface DiscoveryMeta {
  source: string;
  fallback?: boolean;
  fallback_reason?: string | null;
}

export interface DiscoveryListPayload {
  items: VideoRow[];
  pagination: DiscoveryPagination;
  meta: DiscoveryMeta;
}
```

In `client/frontend/src/data/videos.ts`:

- stop building `POST /recommendations` for feed loads;
- add URL builders for:

  ```text
  /api/v1/discovery/recommendations
  /api/v1/discovery/random
  /api/v1/videos/{id}/similar
  ```

- add a small adapter that can still read legacy `{ rows: [...] }` if tests need compatibility, but production v1 paths should consume `{ items: [...] }`;
- keep `api` query param support through `resolveClientApiBase(...)`;
- pass `host` for similar/video routes;
- do not send local likes from frontend for v1 recommendations.

### 8. Update frontend page controllers

In `client/frontend/src/pages/videos/index.ts`:

- switch `fetchVideosPayload()` to v1 data helpers;
- treat v1 `items` as the row source;
- store `pagination.next_cursor` in page state;
- update infinite scroll so it loads the next cursor from the Client backend instead of only revealing preloaded local rows;
- keep the existing local chunk rendering behavior as a fallback for static/legacy payloads if needed.

In `client/frontend/src/pages/video-page/index.ts`:

- change server metadata URL from `/api/video` to `/api/v1/videos/{id}?host=...`;
- keep PeerTube instance fallback behavior if Client v1 metadata returns non-OK/null.

In `client/frontend/src/utils/video-fields.ts`:

- keep `videoPageUrl(...)` including `id` and `host`;
- prefer `video_id` for the local page URL when available but allow `video_uuid` fallback;
- do not introduce `index_id` or backend-only fields.

### 9. Update boundary/static checks

Update `tests/check-frontend-client-gateway.sh` and `client/frontend/test/data/client-api-boundary.test.ts` so frontend production source is expected to call Client v1 routes and remains forbidden from Engine internals/direct ports.

Add checks that production frontend source does not contain legacy feed route strings except in compatibility tests or migration comments:

```text
/recommendations
/videos/similar
/api/video
```

Be careful: `/api/video` may appear in tests or docs. The static check should target production frontend source files under `client/frontend/src`.

### 10. Update documentation

Update docs only where their ownership covers the change:

- `docs/ARCHITECTURE.md`: public discovery path is now Frontend -> Client `/api/v1/...` -> Engine provider routes.
- `docs/FRONTEND_COMPATIBILITY.md`: frontend project API calls use Client v1 Discovery API for feeds/video metadata.
- `docs/ENGINE_API_COMPATIBILITY.md`: legacy Engine routes remain, but Client v1 is the browser-facing contract; Engine internal discovery providers are implementation details if added.
- `docs/diagram/overview.md`: update route labels from legacy `/recommendations` to Client `/api/v1/discovery/...` where appropriate.
- `client/README.md` and `client/frontend/README.md`: document v1 routes as browser-facing API.
- `engine/server/README.md`: document any new internal discovery provider routes as internal Client-consumed routes.
- `README.md`: update the boundary table so browser-facing read API v1 belongs to Client backend.

Do not rewrite unrelated roadmap/history content.

### 11. Update future tasks

In `dev/FUTURE_TASKS.md`, add:

```text
Evaluate uuid-first video identity model
```

Reason:

```text
Discovery API v1 keeps both video_id and video_uuid. A future migration may evaluate whether video_uuid + instance_domain can replace internal video_id as the primary project identity, but that affects videos, embeddings, video_index_ids, similarity_cache, recommendations, likes, resolve logic, and DB migrations.
```

Also add, if the initial cursor implementation uses offset-style base64 cursors:

```text
Design seek-based cursors for large discovery feeds
```

Reason:

```text
Discovery API v1 starts with opaque Client-owned cursors. If feed sizes or dynamic ordering require stronger guarantees, fresh/popular/recommendations should move to feed-specific seek cursors instead of offset slicing.
```

## Tests

Run and update these Python tests:

```bash
python3 -m pytest -q tests/client_backend/test_discovery_v1_api.py
python3 -m pytest -q tests/client_backend
python3 -m pytest -q tests/engine_api/test_internal_discovery_routes.py
python3 -m pytest -q tests/engine_api
python3 -m pytest -q tests/engine_data/test_random_recent_popular_characterization.py
python3 -m pytest -q tests/contracts tests/repositories tests/recommendations tests/db
```

Run boundary checks:

```bash
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

Run frontend tests when `client/frontend/node_modules` is installed:

```bash
cd client/frontend && npm run test
cd client/frontend && npm run build
```

If Node dependencies are missing, report that clearly and still run Python/static checks.

Minimum new/updated assertions:

- Client v1 recommendations is `GET`, not `POST`.
- Client v1 recommendations sends local likes to Engine `POST /recommendations`.
- Frontend v1 recommendations does not send likes payload.
- No-likes recommendations still returns a valid v1 envelope using Engine guest behavior.
- `host` is required for `/api/v1/videos/{id}` and `/api/v1/videos/{id}/similar`.
- v1 video response includes `video_id`, `video_uuid`, `instance_domain`.
- All list endpoints return `items`, `pagination`, `meta`.
- Cursor is opaque, route-bound, and rejected when malformed or reused for another route.
- `fresh` and `popular` are available through Client v1 without Client DB access.
- Legacy routes still work until a later cleanup plan removes them.
- Frontend production code calls Client backend v1 routes and does not call Engine routes directly.

## Open Questions

None. The plan uses the decisions already made during planning:

```text
- Public Discovery API v1 lives in Client backend.
- Frontend is switched to Client backend v1 in this milestone.
- Route split is /api/v1/discovery/... and /api/v1/videos/...
- Video resource routes accept video_id or video_uuid as {id}, with required host.
- Video responses include video_id, video_uuid, and instance_domain.
- List responses use items + pagination + meta.
- Pagination is cursor-based and opaque to the frontend.
- v1 includes random, fresh, popular, recommendations, similar, and video details.
- Recommendations public API is GET only.
- Recommendations use Client backend user state/likes and existing Engine guest fallback.
```

## Out of Scope

- Removing legacy Client routes:

  ```text
  POST /recommendations
  POST /videos/similar
  GET  /api/video
  GET  /api/channels
  ```

- Making Engine `/api/v1/...` public browser API.
- Search API.
- Channels API v1.
- Source/instance filters.
- Auth/session redesign.
- uuid-first project-wide identity migration.
- Changing Engine recommendation ranking, profile configs, or fallback algorithms.
- Changing `similarity_cache` schema.
- Exposing `video_index_ids.index_id` or any ANN/random artifact identity.

## Compatibility / Migration Notes

Legacy routes must remain while frontend migration lands. This keeps existing manual scripts, smoke tests, and old built frontend bundles working during rollout.

The Client backend v1 layer is allowed to call legacy Engine routes internally. That is not a public API leak because the frontend only sees `/api/v1/...`.

The v1 route names should be added, not aliased over the old names. Do not implement `/api/v1/discovery/recommendations` as a raw proxy that returns Engine's old `{ rows: [...] }` response. The point of v1 is to establish a Client-owned envelope contract.

If Engine internal fresh/popular provider routes are added, they should be documented as internal provider routes. They are not stable browser API and should not be used by frontend.

## Regression Risks and Required Protections

### Frontend feed loading regressions

Risk: switching from preloaded `rows` to cursor-loaded `items` may break infinite scroll.

Protection:

- Add frontend tests for first load and next-cursor load.
- Keep adapter functions that turn v1 `items` into the same `VideoRow[]` rendering path.

### Client likes/recommendation payload regressions

Risk: recommendations stop using local likes because frontend no longer sends them.

Protection:

- Client backend v1 tests must assert Engine receives likes from `UsersRepository.fetch_recent_likes(...)`.
- Tests must include at least one stored like with `video_uuid + instance_domain`.

### Engine fallback regressions

Risk: Client backend tries to implement guest fallback and diverges from Engine.

Protection:

- Client backend only calls Engine recommendations with current local likes/user id.
- No new Client-side ranking/fallback algorithm.
- Test no-likes path through fake Engine response and do not assert a new algorithm.

### Identity regressions

Risk: `video_id`/`video_uuid` ambiguity returns wrong video or loses host.

Protection:

- Require `host` for v1 video resource routes.
- Test both `video_id` and `video_uuid` as path id when fake Engine returns matching metadata.
- Preserve response fields `video_id`, `video_uuid`, `instance_domain`.

### Boundary regressions

Risk: frontend starts depending on Engine or Client starts reading Engine DB.

Protection:

- Update and run `tests/check-frontend-client-gateway.sh`.
- Run `tests/check-client-engine-boundary.sh`.
- Client implementation must use HTTP helpers only.

### Cursor regressions

Risk: cursors become parseable frontend contract or leak implementation details.

Protection:

- Cursor tests assert malformed/mismatched cursors fail.
- Cursor payload must not include DB row ids, FAISS ids, `index_id`, SQL snippets, or raw Engine internal response objects.
- Frontend tests only pass cursor through; they do not parse it.

## Completion Criteria

Implementation is complete when:

- all six Client backend v1 routes exist and pass tests;
- frontend feed and video metadata fetch paths use Client backend v1 routes;
- Engine provider behavior covers fresh and popular without Client DB reads;
- all list responses use `items + pagination + meta`;
- cursor pagination works for initial and subsequent v1 feed requests;
- recommendations use local Client likes and public GET;
- legacy routes still pass existing tests;
- docs and future tasks are updated;
- Python tests, boundary shell checks, and available frontend tests pass or missing Node dependencies are reported explicitly.
