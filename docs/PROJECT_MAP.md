# Project Map

Purpose: show where each part of the project is located.

## Top Level

```text
client/                 browser-facing application
engine/                 data collection, data build, and read-side API
docs/                   project documentation
plans/                  implementation plans
tests/                  cross-component behavior and contract tests
Makefile                root verification commands
install-service.sh      centralized systemd installer
uninstall-service.sh    centralized systemd uninstaller
```

## Frontend

```text
client/frontend/src/main.ts                 Vue application bootstrap
client/frontend/src/App.vue                 application shell
client/frontend/src/router/                 browser routes
client/frontend/src/views/                  route-level pages
client/frontend/src/components/             reusable UI components
client/frontend/src/composables/             page state and API orchestration
client/frontend/src/data/                    Client API access and browser storage
client/frontend/src/state/                   URL and profile state
client/frontend/src/types/                   frontend payload types
client/frontend/src/utils/                   formatting and field helpers
client/frontend/scripts/dev.mjs              development server wrapper
client/frontend/package.json                 frontend commands and dependencies
```

## Client Backend

```text
client/backend/server.py                     executable entrypoint
client/backend/app.py                        FastAPI routes
client/backend/runtime.py                    runtime dependencies
client/backend/services/engine_gateway.py    Engine HTTP forwarding
client/backend/services/discovery_v1.py      discovery response handling
client/backend/services/search_v1.py         search response handling
client/backend/services/profile.py           profile and likes behavior
client/backend/services/user_actions.py      user-action orchestration
client/backend/services/bridge_publisher.py  Client-to-Engine event publication
client/backend/repositories/users.py         Client SQLite access
client/backend/db/                           Client schema bootstrap and migrations
```

## Engine API

```text
engine/server/api/server.py                  executable entrypoint and runtime wiring
engine/server/api/app.py                     FastAPI route registration
engine/server/api/routes/                    HTTP adapters
engine/server/api/services/                  request orchestration
engine/server/api/recommendations/           recommendation domain logic
engine/server/api/server_config.py           Engine runtime defaults
engine/server/data/                          Engine data access
engine/server/db/bootstrap.py                Engine runtime DB bootstrap
engine/server/db/migrations/                 Engine-owned SQLite migrations
```

## Crawler

```text
engine/crawler/src/*-cli.ts                   CLI entrypoints
engine/crawler/src/*-worker.ts                crawl orchestration
engine/crawler/src/db/                        crawler SQLite stores
engine/crawler/src/http.ts                    HTTP and retry execution
engine/crawler/src/request-limiter.ts         per-host request limits
engine/crawler/schema.sql                     crawler schema
engine/crawler/package.json                   crawler commands
engine/crawler/dist/                          generated runtime JavaScript
```

## Data Jobs and Updater

```text
engine/server/db/jobs/updater-worker.py       updater executable entrypoint
engine/server/db/jobs/updater/cli.py          updater arguments
engine/server/db/jobs/updater/pipeline.py     updater orchestration
engine/server/db/jobs/updater/commands.py     subprocess commands
engine/server/db/jobs/updater/locks.py        single-run lock
engine/server/db/jobs/updater/staging.py      staging lifecycle
engine/server/db/jobs/updater/sync.py         JoinPeerTube synchronization
engine/server/db/jobs/updater/paths.py        output path validation
engine/server/db/jobs/merge-staging-db.py     staging-to-production merge
engine/server/db/jobs/build-video-embeddings.py
engine/server/db/jobs/build-ann-index.py
engine/server/db/jobs/sync-video-index-ids.py
engine/server/db/jobs/rebuild-video-discovery-data.py
engine/server/db/jobs/rebuild-video-search-index.py
engine/server/db/jobs/precompute-random-index-ids.py
engine/server/db/jobs/precompute-similar-ann.py
engine/server/db/jobs/recompute-popularity.py
```

## Data Files

```text
client/backend/db/users.db
    Client users and likes

engine/crawler/data/crawl.db
    raw crawler output

engine/server/db/whitelist.db
    canonical Engine dataset and runtime tables

engine/server/db/staging-worker.db
    updater staging database

engine/server/db/whitelist-video-embeddings.faiss
engine/server/db/whitelist-video-embeddings.faiss.json
    FAISS index and metadata

engine/server/db/random-cache.db
    persisted Random provider order

engine/server/db/similarity-cache.db
    precomputed similarity candidates
```

## Tests

```text
tests/client_backend/       Client API behavior
tests/engine_api/           Engine routes and contracts
tests/engine_data/          Engine data behavior
tests/recommendations/      recommendation logic
tests/repositories/         SQLite repositories
tests/db/                   schema and bootstrap behavior
tests/jobs/                 updater and data jobs
tests/architecture/         component ownership boundaries
tests/contracts/            static boundary contracts
tests/framework/            FastAPI runtime contracts
tests/compatibility/        removal guards for obsolete interfaces
```

## Find the Owner

| Change | Location |
|---|---|
| Browser page or component | `client/frontend/src/views/` or `client/frontend/src/components/` |
| Frontend request or browser state | `client/frontend/src/data/`, `composables/`, or `state/` |
| Browser-facing API route | `client/backend/app.py` |
| Profile, likes, or user action | `client/backend/services/` and `repositories/users.py` |
| Client-to-Engine proxy | `client/backend/services/engine_gateway.py` |
| Engine route | `engine/server/api/routes/` |
| Engine request orchestration | `engine/server/api/services/` |
| Recommendation behavior | `engine/server/api/recommendations/` |
| Engine SQLite query | `engine/server/data/` |
| PeerTube collection | `engine/crawler/src/` |
| Crawler schema | `engine/crawler/schema.sql` |
| Production data refresh | `engine/server/db/jobs/updater/` |
| Derived artifact build | `engine/server/db/jobs/` |
