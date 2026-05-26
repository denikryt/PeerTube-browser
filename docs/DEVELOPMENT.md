# Development

## Purpose

This document explains how to navigate and verify the project during refactoring.

## Main Areas

```text
client/backend        browser-facing FastAPI API, local profile/write state, Engine gateway
client/backend/services  Client backend behavior split behind the HTTP handler
client/backend/repositories Client-owned SQLite persistence wrappers
client/backend/db     Client users DB current-shape migration resources
client/frontend       web UI and Client API calls
engine/server/api     Engine HTTP API startup, FastAPI app, and route adapters
engine/server/api/routes Engine route-specific request/response adapters
engine/server/api/services Engine API orchestration behind route adapters
engine/server/data    Engine data access and SQLite read helpers
engine/server/db/jobs data-build, updater, embedding, index, and cache jobs
engine/server/db/jobs/updater updater internals split behind updater-worker.py
engine/server/db/migrations Engine runtime/cache current-shape migration resources
engine/crawler        PeerTube crawler source and schema

docs                  product and operational documentation
plans                 implementation plans
tests                 characterization, contract, repository, and smoke tests
```

## Developer Setup

Install the Python development tools needed for the fast regression and lint checks:

```bash
python3 -m pip install -r engine/server/requirements-dev.txt
```

Frontend and crawler dependencies remain component-local. This repository does not use npm workspaces in Stage 2:

```bash
cd client/frontend && npm install
cd engine/crawler && npm install
```

`engine/server/requirements.txt` remains the compatibility runtime/deployment install file. Splitting API/runtime and ML/GPU dependencies is deferred to a later dependency-specific plan.

## Verification

Use `docs/TESTING.md` as the source of truth for current verification commands and prerequisites.

Fast refactor checks are available from the repository root:

```bash
make test-fast
make test-jobs
```

`make test` is an alias for `make test-fast`. It is the local fast regression baseline, not a full CI substitute.

The underlying raw commands are still documented in `docs/TESTING.md` for debugging. Python characterization tests are discovered through `pyproject.toml`, so they can also be run directly:

```bash
python3 -m pytest
```

Lint the Stage 2 maintained Python surface with:

```bash
make lint
```

Dependency-heavy checks such as frontend/crawler builds require local Node dependencies first. They can be run through root wrappers after component-local installation:

```bash
make build-frontend
make build-crawler
make test-smoke-arch
make test-installers-dry-run
```


## Crawler DB module tests

Stage 7 splits the crawler SQLite layer under `engine/crawler/src/db/` while keeping `engine/crawler/src/db.ts` as the compatibility facade. Run the crawler DB tests after installing crawler Node dependencies:

```bash
cd engine/crawler
npm install
npm run test:db

# from repository root:
make test-crawler-db
```

`make test-crawler-db` is intentionally separate from `make test` because it depends on the crawler Node environment and the native `better-sqlite3` package.

## Generated Files

Generated outputs should not be committed:

```text
engine/crawler/dist/
client/frontend/dist/
__pycache__/
.pytest_cache/
```

`engine/crawler/dist/` is still the expected output location after running `cd engine/crawler && npm run build`. Runtime jobs that execute crawler CLIs may depend on those generated files being present.

## Change Discipline

Keep behavior-preserving cleanup separate from behavior changes. If a refactor discovers a real behavior bug, add or update a regression test and plan the behavior change explicitly.

## Recommendation Internals

Recommendation defaults now live in `engine/server/api/recommendations/config.py`. `engine/server/api/server_config.py` remains a compatibility re-export for Engine startup code and existing imports.

Stage 5 adds Python-level config validation and internal dataclasses for route/service boundaries. It does not introduce external YAML/JSON config files, Pydantic/OpenAPI schemas, or recommendation behavior changes.

## Schema Ownership

Stage 6 adds current-shape migration resources for Client users DB and Engine runtime/cache tables. Existing `ensure_*` helpers remain compatibility wrappers, so startup and data-build commands do not change. See `docs/SCHEMA_OWNERSHIP.md` for owners, wrappers, and deferred schema work.

## Frontend split and tests

Stage 8 keeps the frontend on Vite and vanilla TypeScript. Shared helpers are organized under:

```text
client/frontend/src/api          Client-backend-facing frontend facade
client/frontend/src/components   string/DOM render helpers for cards, rows, status, and profile UI
client/frontend/src/state        browser/page state helpers
client/frontend/src/utils        formatting, escaping, DOM, and video-field helpers
```

Frontend tests require component-local Node dependencies and are intentionally separate from `make test`:

```bash
cd client/frontend && npm install
make test-frontend
make build-frontend
```

`make test-frontend` runs Vitest/jsdom DOM and state characterization tests. It is not part of the Python fast regression baseline.

## HTTP Framework Runtime

Client and Engine HTTP services use FastAPI/uvicorn behind the existing executable entrypoints:

```bash
python3 client/backend/server.py --help
python3 engine/server/api/server.py --help
```

The Engine entrypoint still has the existing FAISS runtime prerequisite in environments where FAISS is not installed. Stage 10 does not change that startup dependency. Framework compatibility decisions are documented in `docs/FRAMEWORK_COMPATIBILITY.md`.

## HTTP adapter model

The active Client and Engine HTTP adapter model is FastAPI/uvicorn only. Run services through the existing compatibility entrypoints:

```bash
python3 client/backend/server.py --help
python3 engine/server/api/server.py --help
```

The Engine command still has the existing FAISS prerequisite in environments without FAISS installed. Do not add stdlib HTTP handler fixtures for new tests; use FastAPI `TestClient` or direct route/service harnesses.
