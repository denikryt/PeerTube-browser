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

Internally, `client/backend/server.py` is the stdlib HTTP adapter and process entrypoint. Client profile/write behavior, Engine read proxying, bridge publishing, and Client-owned persistence wrappers live under `client/backend/services/` and `client/backend/repositories/`. This internal split does not change public routes or component boundaries.

### Engine API

The Engine API owns recommendation behavior, video/channel metadata reads, internal Client-to-Engine contracts, interaction ingest, and Engine-readable data access. It must not own Client local user profile persistence.

Internally, `engine/server/api/server.py` owns process startup, runtime state, DB/cache/index wiring, and FAISS/index loading. `engine/server/api/handlers/similar.py` is the stdlib HTTP adapter and route dispatcher. Route-specific request/response adapters live under `engine/server/api/routes/`, while non-trivial API orchestration that is not pure data access or recommendation-domain logic lives under `engine/server/api/services/`. Data access remains in `engine/server/data/`, and recommendation internals remain in `engine/server/api/recommendations/`.

### Crawler and Jobs

The crawler and data-build jobs own PeerTube data collection, dataset updates, derived artifacts, and schema production for Engine consumption. Generated crawler JavaScript is a build output, not source code.

## Forbidden Coupling

- Frontend code must not bypass the Client backend to call Engine directly.
- Client backend code must not import Engine internals or read Engine DB files directly.
- Engine code must not own browser profile state.
- Crawler build outputs must not be committed as source files.

## Refactoring Rule

Structural refactoring should preserve these boundaries until a later plan explicitly changes them with tests and documentation updates.
