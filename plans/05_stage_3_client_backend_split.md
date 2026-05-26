# Stage 3: Split Client Backend Responsibilities Without Changing Framework

## Problem / Goal

The Client backend currently works, but `client/backend/server.py` still owns too many responsibilities in one file. It is simultaneously the command-line entrypoint, server factory, request router, rate-limit gate, Engine read proxy, user action handler, profile handler, bridge publisher, request sanitizer, response writer, and lifecycle logger.

Stage 3 must reduce that file into a small stdlib HTTP composition layer while preserving current runtime behavior. This stage must not migrate to FastAPI, change endpoint paths, change response payloads, change database schema, change frontend behavior, change Engine contracts, or change deployment semantics.

Current Client backend responsibilities found in real code:

```text
client/backend/server.py
  parse_args()
  connect_db()
  ClientBackendServer
  ClientBackendHandler.do_GET()
  ClientBackendHandler.do_POST()
  ClientBackendHandler._handle_engine_read_proxy_get()
  ClientBackendHandler._handle_engine_read_proxy_post()
  ClientBackendHandler._proxy_engine_request()
  ClientBackendHandler._handle_user_action()
  ClientBackendHandler._handle_user_profile_reset()
  ClientBackendHandler._handle_user_profile_likes_get()
  ClientBackendHandler._handle_user_profile_likes_from_client()
  ClientBackendHandler._handle_client_publish_event()
  _publish_to_engine_bridge()
  _publish_event()
  _parse_client_likes()
  _summarize_proxy_likes()
  main()
```

Existing lower-level helpers already exist and should be reused instead of reimplemented:

```text
client/backend/lib/engine_api_client.py
  EngineApiError
  resolve_video_seed()
  fetch_metadata_for_entries()
  resolve_videos_by_uuid_host()

client/backend/lib/http_utils.py
  RateLimiter
  read_json_body()
  resolve_user_id()
  respond_json()
  respond_bytes()
  respond_options()

client/backend/lib/users_store.py
  ensure_user_schema()
  get_or_create_user()
  record_like()
  remove_like()
  clear_likes()
  fetch_recent_likes()
```

Stage 3 should introduce narrow Client backend service and repository modules, then make `server.py` call those modules from the existing handler methods. The first implementation should prefer moving existing code with minimal semantic edits over redesigning behavior.

The desired result after Stage 3:

```text
client/backend/server.py
  command-line parsing
  process lifecycle
  ClientBackendServer state holder
  ClientBackendHandler routing, rate limit checks, request body reads, response writes

client/backend/repositories/users.py
  Client-owned users/likes persistence wrapper around lib.users_store

client/backend/services/user_actions.py
  /api/user-action validation, Engine identity resolution, Client DB write/remove, event payload creation

client/backend/services/bridge_publisher.py
  bridge/activitypub mode handling and POST /internal/events/ingest publishing

client/backend/services/engine_gateway.py
  Client read proxy allowlists, query/body sanitization, upstream Engine HTTP call/retry/result mapping

client/backend/services/profile.py
  /api/user-profile, /api/user-profile/reset, /api/user-profile/likes, client-provided likes metadata resolution

client/backend/schemas.py
  small dataclasses/typed response objects shared by services and server.py if needed
```

This stage is a behavior-preserving refactor. If implementation discovers that a current behavior is undesirable, do not fix it in Stage 3. Add or update a regression test and plan the behavior change separately.

## Expected Behavior

All current Client backend behavior must remain stable.

### Public routes must remain unchanged

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
OPTIONS *
```

Unknown routes must still return:

```json
{"error": "Not found"}
```

with status `404`.

### Health response must remain unchanged

`GET /api/health` must continue to return the current shape:

```json
{
  "ok": true,
  "service": "client-backend",
  "engine_ingest_base": "http://127.0.0.1:7070",
  "publish_mode": "bridge"
}
```

The actual `engine_ingest_base` and `publish_mode` values come from the current server configuration.

### User profile read must remain unchanged

`GET /api/user-profile?user_id=local-user` must continue to:

- normalize missing or blank user ids through `resolve_user_id()`;
- create the user row if it does not exist;
- return recent local likes from the Client users DB;
- cap likes at the current `MAX_LIKES` default;
- return `user_id`, `likes`, and dynamic integer `updatedAt`.

### User action behavior must remain unchanged

For `POST /api/user-action`:

- invalid JSON still returns status `400` with the current error shape;
- unsupported actions still return status `400` with `{"error": "Unsupported action"}`;
- missing both `video_id` and `uuid` still returns status `400` with `{"error": "Missing video_id or uuid"}`;
- Engine resolve failures still return status `502` with `Engine resolve failed: ...`;
- missing Engine seed still returns status `404` with `{"error": "Video not found in Engine"}`;
- incomplete Engine identity still returns status `502` with `{"error": "Engine resolve returned incomplete identity"}`;
- `like` still writes a Client-owned like row before bridge publishing;
- `dislike` and `undo_like` still remove the Client-owned like and publish `UndoLike`;
- bridge failure after local like write still returns status `502` while preserving the local like;
- success/failure response fields remain `ok`, `bridge_ok`, `bridge_error`, `user_id`, and `updatedAt`.

Concrete success example:

```json
{
  "action": "like",
  "uuid": "uuid-123",
  "host": "example.org",
  "user_id": "local-user"
}
```

must still resolve through Engine `/internal/videos/resolve`, insert or update the Client `likes` row, publish this event shape to `/internal/events/ingest`, and return the current status/body:

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
  "published_at": 1739700000000,
  "source_instance": "example.org",
  "raw_payload": {
    "action": "like",
    "uuid": "uuid-123",
    "host": "example.org",
    "user_id": "local-user"
  }
}
```

Only dynamic fields such as `event_id`, `published_at`, and `updatedAt` may vary.

### Profile likes metadata behavior must remain unchanged

For `GET /api/user-profile/likes`:

- user id normalization remains the same;
- limit parsing remains the same through `_parse_int()` semantics;
- Client DB stores lightweight like identity;
- display metadata still comes from Engine `/internal/videos/metadata` through `fetch_metadata_for_entries()`;
- Engine metadata failure still returns status `502` with `Engine metadata failed: ...`.

For `POST /api/user-profile/likes`:

- likes still parse from client `{uuid, host}` entries;
- invalid or incomplete entries are skipped;
- empty parsed likes still return `{"likes": [], "updatedAt": ...}` with status `200`;
- non-empty likes still resolve via Engine `/internal/videos/resolve` and metadata via `/internal/videos/metadata`;
- response shape remains `likes` and `updatedAt`.

### Client read proxy behavior must remain unchanged

Current allowlisted read routes remain:

```text
GET  /api/video
GET  /api/channels
POST /recommendations
POST /videos/similar
```

Current query allowlists remain:

```text
/recommendations: id, host, limit, random, debug, mode, user_id
/videos/similar: id, host, limit, random, debug, mode, user_id
/api/video: refresh_cache, user_id, id, host
/api/channels: limit, offset, q, instance, minFollowers, minVideos, maxVideos, sort, dir
```

Current POST body allowlists remain:

```text
/recommendations: likes, user_id, mode
/videos/similar: likes, user_id, mode
```

The proxy must still:

- reject unknown query parameters with status `400` and `Unknown query parameter: <name>`;
- reject repeated query parameters with status `400` and `Multiple values are not allowed for query parameter: <name>`;
- reject unknown body fields with status `400` and `Unknown body field: <name>`;
- reject non-list `likes` with status `400` and `Invalid likes payload`;
- sanitize likes to `{uuid, host}` with trimmed values;
- cap forwarded likes at `MAX_CLIENT_LIKES`;
- forward upstream Engine response status, bytes, and content type when Engine responds;
- preserve Engine HTTP error payload bytes when present;
- return the current `ENGINE_PROXY_UNAVAILABLE` or `ENGINE_PROXY_FAILURE` response shape for transport/unexpected failures;
- keep the current retry count and retry delay behavior.

### Bridge publishing behavior must remain unchanged

`POST /client/events/publish` must still:

- read JSON body;
- reject non-dict payloads with `Invalid JSON body`;
- add missing `event_id` as `client-...`;
- add missing `published_at` via `now_ms()`;
- call the same publish mode behavior;
- return status `200` when bridge result has `ok=true` and `502` otherwise.

Bridge mode behavior must stay:

```text
bridge       -> POST {engine_base}/internal/events/ingest
activitypub  -> ok=false, error="CLIENT_PUBLISH_MODE=activitypub is not implemented yet", mode="activitypub"
```

### Boundary behavior must remain unchanged

The Client backend must still:

- not import `engine.*` modules;
- not read `engine/server/db/*`;
- communicate with Engine through HTTP only;
- remain the browser-facing owner of profile/write routes.

## Architecture

Stage 3 keeps the current stdlib HTTP architecture. The handler remains the HTTP adapter; services own behavior that is not inherently HTTP response writing.

Target architecture for this stage:

```text
client/backend/server.py
  parse_args()
  connect_db()
  ClientBackendServer
  ClientBackendHandler.do_GET()/do_POST()
  rate-limit check
  minimal route dispatch
  read_json_body()/respond_json()/respond_bytes() calls
  main()

client/backend/repositories/users.py
  UsersRepository or thin functions around lib.users_store
  no Engine calls
  no HTTP response writing

client/backend/services/bridge_publisher.py
  resolve_publish_mode()
  publish_event()
  publish_to_engine_bridge()
  no Client DB access
  no BaseHTTPRequestHandler dependency

client/backend/services/engine_gateway.py
  route allowlists
  sanitize_get_query()
  sanitize_post_body()
  summarize_proxy_likes()
  proxy_engine_request()
  returns a ProxyResult for server.py to write
  no Client DB access

client/backend/services/user_actions.py
  parse and validate action payload
  resolve Engine video identity through lib.engine_api_client
  update Client users repository
  build normalized event payload
  call bridge_publisher.publish_event()
  returns an HTTP-neutral service result

client/backend/services/profile.py
  get profile summary
  reset profile likes
  fetch stored likes metadata through Engine
  resolve client-provided likes and fetch metadata

client/backend/schemas.py
  small dataclasses if they make handler-service contracts explicit
```

Recommended service result shape:

```python
@dataclass(frozen=True)
class ServiceResult:
    """HTTP-neutral result returned by Client backend services."""

    status: int
    body: dict[str, Any]
```

Recommended proxy result shape:

```python
@dataclass(frozen=True)
class ProxyResult:
    """Engine proxy response bytes ready for HTTP adaptation."""

    status: int
    payload: bytes
    content_type: str
    is_json_error: bool = False
```

The exact type names can change during implementation, but the contract should stay simple: services return data and status; `server.py` writes HTTP responses.

### Import compatibility

Current tests add `client/backend` to `sys.path` and import `server`. Existing runtime executes:

```bash
python3 client/backend/server.py
```

Therefore Stage 3 modules should use imports that work under that execution model. Prefer keeping `client/backend` as the import root for this stage:

```python
from lib.http_utils import resolve_user_id
from services.bridge_publisher import publish_event
from repositories.users import UsersRepository
```

Do not convert `client/backend` into an installed Python package in this stage. Packaging/import normalization can be planned later if needed.

### What must not be done in Stage 3

Do not:

- migrate to FastAPI or any other framework;
- change `BaseHTTPRequestHandler` usage;
- change public route paths;
- change response JSON shapes intentionally;
- change Client users DB schema;
- move Engine API code;
- change frontend code;
- change Engine internal endpoints;
- introduce async HTTP clients;
- introduce dependency injection frameworks;
- add broad lint cleanup outside touched Client backend modules;
- fix currently characterized product behavior unless a separate behavior-change plan exists.

## Remaining Ownership After Stage 3

Stage 3 is complete even though `server.py` still owns HTTP routing and process startup. That remaining ownership is intentional, not a gap between stages.

After Stage 3, `client/backend/server.py` must remain responsible for:

```text
command-line argument parsing
SQLite connection construction
ClientBackendServer construction and runtime state holder wiring
BaseHTTPRequestHandler subclass
do_GET and do_POST route dispatch
OPTIONS/CORS response wiring
rate-limit checks
request body reading through lib.http_utils
response writing through lib.http_utils
process lifecycle logging and signal handling
main()
```

After Stage 3, `client/backend/server.py` must no longer be responsible for:

```text
Engine read-proxy allowlists and body/query sanitization
Engine proxy retry loop and upstream response mapping
bridge publish implementation and publish-mode behavior
Client user action orchestration
profile likes metadata enrichment
client-provided likes parsing/resolution for metadata endpoints
Client users DB operation details beyond repository/service construction and calls
```

Deferred work that must not be pulled into Stage 3:

```text
client/backend/app.py
client/backend/routes/*
FastAPI or other framework migration
public request/response schema redesign
Client users DB schema migration
frontend API client changes
Engine API changes
```

`client/backend/schemas.py` may contain only small internal dataclasses or typed result objects for service boundaries. It must not introduce new public API schemas, Pydantic models, OpenAPI contracts, or changed validation policy in Stage 3.

## Touched Files

```text
client/backend/server.py
client/backend/lib/engine_api_client.py
client/backend/lib/http_utils.py
client/backend/lib/users_store.py
client/README.md
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/TESTING.md
README.md
Makefile
pyproject.toml
tests/client_backend/conftest.py
tests/client_backend/test_user_action_like_characterization.py
tests/client_backend/test_read_proxy_characterization.py
tests/client_backend/test_profile_likes_characterization.py
tests/client_backend/test_client_publish_event_characterization.py
tests/client_backend/test_user_profile_reset_characterization.py
tests/client_backend/test_user_profile_characterization.py
tests/client_backend/test_read_proxy_failure_characterization.py
tests/contracts/test_current_boundary_scripts.py
tests/check-client-engine-boundary.sh
```

Stage 3 should only edit a subset of these files. The files are listed because the plan is based on their current contracts or because they may need small documentation/tooling updates after the Client backend split.

Expected production-code edits:

```text
client/backend/server.py
client/backend/repositories/users.py
client/backend/services/bridge_publisher.py
client/backend/services/engine_gateway.py
client/backend/services/user_actions.py
client/backend/services/profile.py
client/backend/schemas.py
```

Expected documentation edits:

```text
client/README.md
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/TESTING.md
```

Only update docs whose current responsibility covers the changed code layout. Do not add broad architecture prose unrelated to Client backend Stage 3.

## New Files

```text
plans/05_stage_3_client_backend_split.md
client/backend/repositories/__init__.py
client/backend/repositories/users.py
client/backend/services/__init__.py
client/backend/services/bridge_publisher.py
client/backend/services/engine_gateway.py
client/backend/services/user_actions.py
client/backend/services/profile.py
client/backend/schemas.py
tests/client_backend/test_client_publish_event_characterization.py
tests/client_backend/test_user_profile_reset_characterization.py
tests/client_backend/test_user_profile_characterization.py
tests/client_backend/test_read_proxy_failure_characterization.py
```

Explicitly deferred from Stage 3:

```text
client/backend/app.py
client/backend/routes/*
```

`app.py` and route modules are intentionally not part of Stage 3. This stage extracts service and repository responsibilities while keeping `server.py` as the stdlib HTTP entrypoint and route dispatch layer. Route-module splitting can be planned later after the service extraction is complete.

## Implementation Steps

### 1. Run the Stage 2 fast baseline before editing

Run from repository root:

```bash
make test
make lint
```

Expected current result before Stage 3 edits:

```text
make test -> PASS
make lint -> PASS
```

If either fails before production edits, stop and record the baseline failure. Do not start moving Client backend code on a failing baseline unless the failure is clearly unrelated and documented.

### 2. Inventory exact Client backend behavior before moving code

Read and map `client/backend/server.py` into these behavior groups:

```text
routing/lifecycle:
  parse_args
  connect_db
  ClientBackendServer
  ClientBackendHandler.do_GET
  ClientBackendHandler.do_POST
  ClientBackendHandler._rate_limit_check
  main

Engine read proxy:
  _handle_engine_read_proxy_get
  _handle_engine_read_proxy_post
  _proxy_engine_request
  _summarize_proxy_likes
  PROXY_READ_GET_ROUTES
  PROXY_READ_POST_ROUTES
  PROXY_ALLOWED_QUERY_PARAMS
  PROXY_ALLOWED_BODY_KEYS

profile:
  /api/user-profile inline logic in do_GET
  _handle_user_profile_reset
  _handle_user_profile_likes_get
  _handle_user_profile_likes_from_client
  _parse_client_likes

user actions:
  _handle_user_action

bridge publishing:
  _publish_to_engine_bridge
  _publish_event
  _resolve_mode
```

Confirm that existing Stage 0 tests plus the required new Stage 3 characterization tests cover the externally visible flows:

```text
tests/client_backend/test_user_action_like_characterization.py
tests/client_backend/test_read_proxy_characterization.py
tests/client_backend/test_profile_likes_characterization.py
tests/client_backend/test_client_publish_event_characterization.py
tests/client_backend/test_user_profile_reset_characterization.py
tests/client_backend/test_user_profile_characterization.py
tests/client_backend/test_read_proxy_failure_characterization.py
tests/contracts/test_current_boundary_scripts.py
```

If a behavior group is not covered by any existing test and would be moved in this stage, add a narrow characterization test before moving it. Do not move uncharacterized behavior and do not rely on "the code looks equivalent" as a substitute for a behavior check.

Required additional characterization tests before moving the corresponding behavior:

```text
tests/client_backend/test_client_publish_event_characterization.py
  POST /client/events/publish adds event_id/published_at, preserves bridge/activitypub mode behavior,
  and returns status 200 vs 502 from the current publish result.

tests/client_backend/test_user_profile_reset_characterization.py
  POST /api/user-profile/reset clears stored likes and returns the current reset response shape.

tests/client_backend/test_user_profile_characterization.py
  GET /api/user-profile creates/returns the local Client profile and raw stored like identities without Engine metadata enrichment.

tests/client_backend/test_read_proxy_failure_characterization.py
  proxy transport failures return the current ENGINE_PROXY_UNAVAILABLE/ENGINE_PROXY_FAILURE shape,
  and Engine HTTP errors with payload bytes are passed through with status/content-type/body preserved.
```

These tests are required because Stage 3 moves the code responsible for those paths. Do not add broad new test categories, but do add these focused route-level tests before extracting their behavior from `server.py`.

### 3. Add shared service result schemas if needed

Create `client/backend/schemas.py` only if the extraction needs explicit result objects. Keep it small.

Suggested content:

```python
"""Shared lightweight result types for Client backend service boundaries."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ServiceResult:
    """HTTP-neutral JSON result returned by Client backend services."""

    status: int
    body: dict[str, Any]


@dataclass(frozen=True)
class ProxyBytesResult:
    """HTTP-neutral upstream response returned by the Engine gateway service."""

    status: int
    payload: bytes
    content_type: str
```

Avoid creating large schema models. This is not the stage for Pydantic or OpenAPI.

### 4. Extract bridge publishing first

Create:

```text
client/backend/services/bridge_publisher.py
```

Move behavior from:

```text
_resolve_mode
_publish_to_engine_bridge
_publish_event
```

Expected public functions:

```python
def resolve_publish_mode(value: str, default: str = "bridge") -> str:
    """Normalize the Client publish mode to a supported current mode."""


def publish_to_engine_bridge(engine_ingest_base: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Publish one normalized Client event to Engine bridge ingest."""


def publish_event(publish_mode: str, engine_ingest_base: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Publish one Client event using the current configured publish mode."""
```

Preserve exact behavior:

```text
mode normalization accepts bridge/activitypub only
activitypub returns ok=false and current not-implemented error
HTTPError returns {ok: false, error: "engine bridge HTTP <code>"}
URLError/TimeoutError returns {ok: false, error: str(exc)}
valid Engine JSON returns {ok: bool(parsed.get("ok", True)), response: parsed}
```

Update `server.py` imports and calls:

```python
from services.bridge_publisher import publish_event, resolve_publish_mode
```

Replace `_resolve_mode(...)` call sites with `resolve_publish_mode(...)`. Replace `_publish_event(...)` call sites with `publish_event(...)`.

After this extraction, run:

```bash
make test-python
```

### 5. Extract the users repository wrapper

Create:

```text
client/backend/repositories/users.py
```

This module should be a thin wrapper around `client/backend/lib/users_store.py`, not a new schema owner.

Recommended class:

```python
class UsersRepository:
    """Repository for Client-owned users and likes stored in SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None: ...
    def ensure_schema(self) -> None: ...
    def get_or_create_user(self, user_id: str) -> None: ...
    def record_like(self, user_id: str, video: dict[str, Any], max_likes: int) -> None: ...
    def remove_like(self, user_id: str, video_id: str, instance_domain: str) -> None: ...
    def clear_likes(self, user_id: str) -> None: ...
    def fetch_recent_likes(self, user_id: str, limit: int) -> list[dict[str, Any]]: ...
```

The wrapper can use `with conn:` at service call sites or inside methods, but transaction semantics must match current behavior. Be careful: current `users_store` helpers call `conn.commit()` internally. Do not introduce nested transaction behavior that changes commit timing.

Update `ClientBackendServer` to hold either:

```python
self.user_db = user_db
self.users = UsersRepository(user_db)
```

or only `self.users` while keeping `self.user_db` temporarily for tests/backward compatibility. Prefer keeping `self.user_db` during Stage 3 to reduce test churn.

After this extraction, run:

```bash
make test-python
```

### 6. Extract profile service

Create:

```text
client/backend/services/profile.py
```

Move behavior from:

```text
GET /api/user-profile inline block
_handle_user_profile_reset
_handle_user_profile_likes_get
_handle_user_profile_likes_from_client
_parse_client_likes
_parse_int if it remains profile-only; otherwise keep it in server.py or move to a small utility in this module
```

Recommended functions:

```python
def parse_positive_int(value: str | None) -> int:
    """Parse a positive integer using current Client backend query semantics."""


def parse_client_likes(payload: dict[str, Any], max_items: int) -> list[dict[str, str]]:
    """Parse frontend uuid/host likes into Engine uuid/host identity entries."""


def get_user_profile(users: UsersRepository, user_id: str, max_likes: int) -> ServiceResult:
    """Return the local Client profile payload for one user."""


def reset_user_profile(users: UsersRepository, user_id: str) -> ServiceResult:
    """Clear local Client likes for one user and return the current reset payload."""


def get_profile_likes_metadata(
    users: UsersRepository,
    engine_base_url: str,
    user_id: str,
    limit: int,
    max_likes: int,
) -> ServiceResult:
    """Return Engine-enriched metadata for locally stored likes."""


def get_client_likes_metadata(
    engine_base_url: str,
    body: dict[str, Any],
    max_client_likes: int,
) -> ServiceResult:
    """Resolve frontend-provided uuid/host likes and return Engine metadata rows."""
```

Preserve current Engine error handling:

```text
EngineApiError in metadata paths -> status 502, error "Engine metadata failed: <exc>"
```

Update `server.py` handler methods to read request body/query params and call the service, then `respond_json(self, result.status, result.body)`.

After this extraction, run:

```bash
make test-python
```

### 7. Extract user action service

Create:

```text
client/backend/services/user_actions.py
```

Move behavior from:

```text
_handle_user_action
```

Recommended function:

```python
def handle_user_action(
    users: UsersRepository,
    engine_base_url: str,
    publish_mode: str,
    body: dict[str, Any],
    max_likes: int,
    event_id_factory: Callable[[], str] = lambda: f"client-{uuid4()}",
    now_ms_func: Callable[[], int] = now_ms,
) -> ServiceResult:
    """Apply one Client user action and publish the matching Engine interaction event."""
```

The optional factory/time parameters are acceptable because they expose existing dynamic boundaries without changing runtime behavior. Tests can keep using route-level HTTP behavior; new unit tests are optional unless needed for missing cases.

Preserve exact action mapping:

```text
like      -> record_like(...), event_type="Like"
dislike   -> remove_like(...), event_type="UndoLike"
undo_like -> remove_like(...), event_type="UndoLike"
```

Preserve exact validation and error messages listed in `Expected Behavior`.

Preserve event payload keys and values:

```text
event_id
 event_type
 actor_id
 object.video_uuid
 object.instance_domain
 object.canonical_url
 published_at
 source_instance
 raw_payload
```

Update `server.py` `_handle_user_action()` to only:

```text
read JSON body
call user_actions.handle_user_action(...)
respond_json(...)
```

After this extraction, run:

```bash
make test-python
```

### 8. Extract Engine gateway service

Create:

```text
client/backend/services/engine_gateway.py
```

Move behavior from:

```text
PROXY_READ_GET_ROUTES
PROXY_READ_POST_ROUTES
PROXY_ALLOWED_QUERY_PARAMS
PROXY_ALLOWED_BODY_KEYS
_handle_engine_read_proxy_get
_handle_engine_read_proxy_post sanitization logic
_proxy_engine_request
_summarize_proxy_likes
```

Recommended functions:

```python
def sanitize_get_query(path: str, params: dict[str, list[str]]) -> ServiceResult | dict[str, str]:
    """Validate and sanitize allowlisted GET proxy query parameters."""


def sanitize_post_request(
    path: str,
    query_params: dict[str, list[str]],
    body: dict[str, Any],
    max_client_likes: int,
) -> ServiceResult | tuple[dict[str, str], dict[str, Any]]:
    """Validate and sanitize a Client read-proxy POST request."""


def summarize_proxy_likes(raw_likes: Any, max_items: int = 6) -> tuple[int, list[str], int]:
    """Return compact like diagnostics for Client recommendation logs."""


def proxy_engine_request(
    engine_base_url: str,
    method: str,
    path: str,
    sanitized_query: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout_seconds: int = ENGINE_PROXY_TIMEOUT_SECONDS,
    max_body_bytes: int = ENGINE_PROXY_MAX_BODY_BYTES,
    retry_count: int = ENGINE_PROXY_RETRY_COUNT,
    retry_delay_seconds: float = ENGINE_PROXY_RETRY_DELAY_SECONDS,
    log: Callable[[int, str, str, dict[str, Any] | None], None] | None = None,
) -> ProxyBytesResult | ServiceResult:
    """Forward one allowlisted Client read request to Engine over HTTP."""
```

If returning unions makes implementation awkward, introduce small explicit result classes. Do not return raw `BaseHTTPRequestHandler` objects from services.

Preserve proxy logging fields where practical:

```text
event names: recommendations.incoming_likes, engine.proxy
method
path
status
attempt
attempts
duration_ms
likes_count
likes
likes_omitted
user_id
mode
error
traceback for unexpected exception path
```

`server.py` should remain responsible for writing bytes:

```python
result = proxy_engine_request(...)
if isinstance(result, ProxyBytesResult):
    respond_bytes(self, result.status, result.payload, result.content_type)
else:
    respond_json(self, result.status, result.body)
```

After this extraction, run:

```bash
make test-python
make test-boundaries
```

### 9. Reduce `server.py` to route dispatch and HTTP adaptation

After services are extracted, simplify `ClientBackendHandler` methods:

```text
do_GET
  parse url/query
  rate-limit route
  call small handler methods
  respond

do_POST
  parse path
  rate-limit route
  read body when needed
  call services
  respond
```

`server.py` should still own:

```text
BaseHTTPRequestHandler subclass
ThreadingHTTPServer subclass
CORS OPTIONS response call
rate-limit gate
JSON body read calls
HTTP response writes
process lifecycle logging
signal handling
main()
```

`server.py` should no longer own:

```text
Engine proxy retry loop
proxy allowlist definitions
proxy likes sanitization
bridge POST implementation
user action business flow
profile metadata enrichment flow
Client users DB operation details beyond repository construction
```

Avoid a big-bang rewrite. Move one behavior group at a time and run tests after each group.

### 10. Update documentation for new Client backend layout

Read the purpose/opening sections before editing:

```text
client/README.md
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/TESTING.md
```

Expected documentation updates:

```text
client/README.md
  Add a short backend module map explaining server.py, services/, repositories/, lib/.

 docs/DEVELOPMENT.md
  Update the project navigation block to mention Client backend services/repositories if helpful.

 docs/ARCHITECTURE.md
  Only update if the internal Client backend responsibility split is worth documenting.
  Do not change component boundary semantics.

 docs/TESTING.md
  Only update if Stage 3 adds new targeted tests or changes the recommended command surface.
```

Do not edit deployment docs unless the runtime command changes. Stage 3 should not change:

```bash
CLIENT_PUBLISH_MODE=bridge ./venv/bin/python3 client/backend/server.py \
  --host 127.0.0.1 \
  --port 7172 \
  --engine-url http://127.0.0.1:7070
```

### 11. Run the complete Stage 2 verification after extraction

Required checks:

```bash
make test
make lint
```

If Node dependencies are installed, optional prerequisite-sensitive checks:

```bash
make build-frontend
make build-crawler
```

Do not require Node checks for Stage 3 completion unless the local environment has the prerequisites documented in `docs/TESTING.md`.

### 12. Stop conditions

Stop and update this plan before continuing if any of these occur:

- A route response shape differs from Stage 0 characterization tests.
- Service extraction requires changing public route behavior to make code cleaner.
- Importing new service modules breaks `python3 client/backend/server.py` execution.
- The Client backend boundary script flags new imports or Engine DB references.
- A service needs direct access to `BaseHTTPRequestHandler` to preserve behavior.
- Transaction timing changes because repository wrappers conflict with current `users_store` commits.
- A missing behavior test is discovered for a route being moved and cannot be covered quickly.
- The refactor requires changing `lib/engine_api_client.py` response semantics.
- The implementation wants to add FastAPI, Pydantic, async HTTP, or packaging changes.

## Tests

Stage 3 must rely first on the existing Stage 0 characterization tests, the required new Stage 3 characterization tests, and Stage 2 command wrappers.

Primary required checks:

```bash
make test
make lint
```

Relevant Client backend and boundary tests that must stay green:

```text
tests/client_backend/test_user_action_like_characterization.py
tests/client_backend/test_read_proxy_characterization.py
tests/client_backend/test_profile_likes_characterization.py
tests/client_backend/test_client_publish_event_characterization.py
tests/client_backend/test_user_profile_reset_characterization.py
tests/client_backend/test_user_profile_characterization.py
tests/client_backend/test_read_proxy_failure_characterization.py
tests/repositories/test_client_users_store.py
tests/contracts/test_current_boundary_scripts.py
tests/check-client-engine-boundary.sh
tests/check-frontend-client-gateway.sh
```

Required targeted test additions before moving the corresponding behavior:

```text
tests/client_backend/test_client_publish_event_characterization.py
tests/client_backend/test_user_profile_reset_characterization.py
tests/client_backend/test_user_profile_characterization.py
tests/client_backend/test_read_proxy_failure_characterization.py
```

These tests close the remaining Stage 0 coverage gaps for Client backend code that Stage 3 will move out of `server.py`. They should be narrow route-level characterization tests, not a broad new test category.

Do not add unrelated test suites in Stage 3. This is a refactor stage for Client backend structure, not a new behavior stage.

Test design rules:

- Keep route-level scenario tests as the source of truth for externally visible behavior.
- Use fake Engine HTTP servers for Engine boundaries.
- Use temporary SQLite databases for Client users/profile persistence.
- Mock only time, event ids, network, or other outer boundaries if direct scenario testing is not practical.
- Prefer testing service modules through existing HTTP characterization tests unless a service has complex pure validation logic that is easier to cover directly.

## Regression and Blind-Spot Analysis

High-risk regressions Stage 3 must catch:

- Client backend fails to start via `python3 client/backend/server.py` because imports changed.
- `GET /api/health` shape changes.
- `POST /api/user-action` writes DB state after bridge publish instead of before it.
- Bridge ingest failure stops preserving the local like.
- `dislike` or `undo_like` action mapping changes.
- Event payload changes and Engine ingest receives different keys.
- `/client/events/publish` stops adding missing `event_id` or `published_at`.
- Profile likes endpoint returns raw Client DB rows instead of Engine metadata rows.
- Client-provided likes parsing changes from `{uuid, host}` to another shape.
- Proxy allowlists become broader or narrower accidentally.
- Proxy no longer preserves Engine response body/content type/status.
- Proxy retry/error response shape changes.
- Rate limiting stops applying to the same route keys.
- CORS headers change because response writing moves accidentally.
- New modules import Engine internals and violate the Client boundary.
- Documentation claims a different runtime command or architecture than the real code.

Blind spots that may remain after Stage 3:

- Full production-like network timeout behavior is only lightly characterized.
- Rate-limit behavior is not deeply tested beyond existing route flow tests.
- Client lifecycle signal handling remains mostly covered by compile/runtime startup checks, not deep tests.
- ActivityPub publish mode remains intentionally not implemented and lightly characterized.
- Frontend behavior is protected by gateway tests and existing contracts, not by browser tests in this stage.

## Compatibility and Protocol Notes

Generic behavior:

- Moving logic from a handler into services should preserve externally observable HTTP behavior.
- Services should return data/status and should not write HTTP responses directly.
- Repository wrappers should preserve current transaction and schema behavior.

Project-specific behavior:

- Client backend is the browser-facing owner of user profile/write behavior.
- Client backend talks to Engine only through HTTP contracts.
- Client users DB is Client-owned state and must not move to Engine in this stage.
- Bridge publishing is the current project-specific Client-to-Engine ingest path, not a generic ActivityPub implementation.
- `activitypub` publish mode remains a reserved not-implemented branch.

PeerTube-specific behavior:

- Video identity fields such as `video_uuid`, `instance_domain`, `host`, and `canonical_url` are used because this product works with PeerTube video metadata and Engine identity resolution.
- Stage 3 should not reinterpret these fields or change identity semantics.

## Expected Conflicts and Compatibility Risks

- Current imports assume `client/backend` can be used as an import root. New modules must work with direct script execution, not only with pytest.
- `server.py` currently imports functions directly from `lib.*`; changing import style too much may break local execution.
- Moving `_resolve_mode` changes constants such as `DEFAULT_CLIENT_PUBLISH_MODE`; imports must avoid circular dependencies.
- Moving `_proxy_engine_request` out of the handler means response writing must be separated from upstream request execution without losing content-type/status preservation.
- Moving proxy logging out of `server.py` may accidentally drop diagnostic fields.
- Moving user action behavior into a service may accidentally change when DB writes happen relative to bridge publishing.
- `users_store` functions currently call `conn.commit()` internally. Repository wrappers must not assume they are pure unit-of-work functions.
- Broadening `make lint` to include new modules may require small lint fixes in the new Stage 3 files; avoid widening lint to unrelated legacy files.
- Adding dataclasses with modern typing must remain compatible with the Python version targeted by `pyproject.toml`.

## Open Questions

None for the current Stage 3 scope.
