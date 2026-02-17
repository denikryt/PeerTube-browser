# Client Backend Service

Write/profile API service for PeerTube Browser Client.

## Responsibilities
- Owns user write/profile endpoints:
  - `POST /api/user-action`
  - `POST /api/user-profile/reset`
  - `GET|POST /api/user-profile/likes`
  - `GET /api/user-profile`
- Publishes normalized interaction events to Engine bridge:
  - Engine endpoint: `POST /internal/events/ingest`
- Uses Engine read API over HTTP for video resolve/metadata (no direct Engine DB access).

## Run
```bash
CLIENT_PUBLISH_MODE=bridge ./venv/bin/python3 client/backend/server.py \
  --host 127.0.0.1 \
  --port 7172 \
  --engine-ingest-base http://127.0.0.1:7171
```

`CLIENT_PUBLISH_MODE`:
- `bridge` (default): publish to Engine bridge ingest endpoint.
- `activitypub`: reserved for next milestone (currently returns not implemented).
