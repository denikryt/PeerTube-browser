# Client

Client workspace contains two parts:

- `client/frontend/` - static frontend UI.
- `client/backend/` - write/profile API service that publishes events to Engine.

## Backend Responsibilities

- Owns user write/profile endpoints:
  - `POST /api/user-action`
  - `POST /api/user-profile/reset`
  - `GET|POST /api/user-profile/likes`
  - `GET /api/user-profile`
- Publishes normalized interaction events to Engine bridge:
  - Engine endpoint: `POST /internal/events/ingest`
- Uses Engine read API over HTTP for video resolve/metadata (no direct Engine DB access).


## Backend Layout

`client/backend/server.py` remains the executable entrypoint and launches the FastAPI app from `client/backend/app.py`. It owns process startup, runtime dependency construction, uvicorn launch, and lifecycle compatibility.

The backend behavior is split into narrow modules:

```text
client/backend/services/bridge_publisher.py  Client -> Engine bridge publish modes
client/backend/services/engine_gateway.py     read proxy allowlists and Engine HTTP forwarding
client/backend/services/profile.py            local profile and likes metadata flows
client/backend/services/user_actions.py       user action orchestration and event payload creation
client/backend/repositories/users.py          Client users/likes SQLite wrapper
client/backend/schemas.py                     small internal service result types
```

These modules are internal structure only. Public routes and payload shapes remain the boundary contract described above.

## Boundary Contract (Client-side)
- Browser-facing ownership stays in Client backend:
  - write/profile: `/api/user-action`, `/api/user-profile/*`
  - read gateway: `/recommendations`, `/videos/similar`, `/api/video`, `/api/channels`
- Client backend consumes Engine internal read contract over HTTP only:
  - `/internal/videos/resolve`
  - `/internal/videos/metadata`
- Client backend publishes normalized events to temporary Engine bridge ingest:
  - `/internal/events/ingest`
- Forbidden:
  - importing `engine.*` modules in `client/backend`,
  - direct reads from `engine/server/db/*`,
  - frontend direct usage of Engine API base instead of Client gateway routes.

## Run Backend Locally

```bash
CLIENT_PUBLISH_MODE=bridge ./venv/bin/python3 client/backend/server.py \
  --host 127.0.0.1 \
  --port 7172 \
  --engine-url http://127.0.0.1:7070
```

`CLIENT_PUBLISH_MODE`:
- `bridge` (default): publish to Engine bridge ingest endpoint.
- `activitypub`: reserved for next milestone (currently returns not implemented).


## Discovery API v1

The Client backend exposes browser-facing Discovery v1 routes for `recommendations`, `fresh`, `popular`, and `random`, plus `/api/v1/search/videos`, `/api/v1/search/channels`, `/api/v1/video-facets`, and `/api/v1/videos/...`. Browser code never calls Engine `/internal/...` routes directly.

`language`, `category`, `tag`, and `instance` are one shared video-filter contract for Discovery and video Search. Fresh/Popular/Random continuation cursors are opaque Client-owned wrappers around Engine provider cursors and are bound to source + filters. Recommended is intentionally a finite legacy computation in this milestone: the Client returns the same envelope with terminal pagination (`next_cursor=null`, `has_more=false`). Similar-video routes keep their existing independent behavior.

The Client owns public validation/error codes and user-like lookup. Engine owns filter semantics, provider ordering, serving eligibility, recommendation computation, facets, and canonical video metadata.
