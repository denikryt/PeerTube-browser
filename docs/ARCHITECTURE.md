# Architecture

## Purpose

This document defines the current PeerTube Browser component boundaries and the runtime data flow that must remain stable during refactoring.

## Runtime Flow

```text
crawler -> SQLite datasets/indexes/caches -> Engine API -> Client backend -> Frontend
```

The crawler and update jobs build local datasets and derived artifacts. The Engine API reads those artifacts and serves metadata, recommendations, and internal ingest endpoints. The Client backend is the browser-facing gateway and owns local user/profile state. The frontend renders UI and talks to the Client backend.

## Component Ownership

### Frontend

The frontend owns page state, rendering, UI interactions, and calls to the Client backend. It must not call Engine internal or read APIs directly.

### Client Backend

The Client backend owns browser-facing profile and write behavior, local user data, Client API error shaping, and HTTP gateway calls to Engine. It must not import Engine modules or read Engine database files directly.

Internally, `client/backend/server.py` remains the executable process entrypoint and now launches the FastAPI app from `client/backend/app.py`. Client profile/write behavior, Engine read proxying, bridge publishing, and Client-owned persistence wrappers live under `client/backend/services/` and `client/backend/repositories/`. This framework migration does not change public routes or component boundaries.

### Engine API

The Engine API owns recommendation behavior, video/channel metadata reads, internal Client-to-Engine contracts, interaction ingest, and Engine-readable data access. It must not own Client local user profile persistence.

Internally, `engine/server/api/server.py` owns process startup, runtime state, DB/cache/index wiring, FAISS/index loading, and the FastAPI/uvicorn launch. `engine/server/api/app.py` registers the active FastAPI routes. Route-specific request/response adapters live under `engine/server/api/routes/`, while non-trivial API orchestration that is not pure data access or recommendation-domain logic lives under `engine/server/api/services/`. Data access remains in `engine/server/data/`, and recommendation internals remain in `engine/server/api/recommendations/`.

### Crawler and Jobs

The crawler and data-build jobs own PeerTube data collection, dataset updates, derived artifacts, and schema production for Engine consumption. Generated crawler JavaScript is a build output, not source code. `engine/server/db/jobs/updater-worker.py` remains the stable updater entrypoint, while updater orchestration internals live under `engine/server/db/jobs/updater/`.

## SQLite Schema Ownership

SQLite schemas are owned by the component that creates or publishes the database artifact. Client backend owns the local users/likes DB, the crawler owns the raw crawl DB schema, Engine jobs own data-build output shapes, and Engine runtime owns runtime/cache helper tables. Detailed owners, compatibility wrappers, and Stage 6 migration resources are documented in `docs/SCHEMA_OWNERSHIP.md`.

## Forbidden Coupling

- Frontend code must not bypass the Client backend to call Engine directly.
- Client backend code must not import Engine internals or read Engine DB files directly.
- Engine code must not own browser profile state.
- Crawler build outputs must not be committed as source files.

## Refactoring Rule

Structural refactoring should preserve these boundaries until a later plan explicitly changes them with tests and documentation updates.

## Frontend Internal Layout

Stage 8 keeps the same Vite/vanilla TypeScript runtime while splitting reusable frontend code into narrower modules. Page entrypoints remain the lifecycle controllers, while shared Client API facades, rendering helpers, state helpers, and formatting utilities live under `client/frontend/src/api/`, `client/frontend/src/components/`, `client/frontend/src/state/`, and `client/frontend/src/utils/`.

This split does not change the component boundary: frontend project API calls still go through the Client backend, and public PeerTube instance fallback on the video page remains PeerTube-specific metadata fallback behavior.
