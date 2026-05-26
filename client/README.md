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

`client/backend/server.py` remains the stdlib HTTP entrypoint and route dispatch layer. It owns process startup, request parsing, rate-limit checks, CORS/response writing, and server lifecycle.

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
