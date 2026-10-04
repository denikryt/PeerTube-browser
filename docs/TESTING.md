# Testing

This document defines how to verify current PeerTube Browser behavior before and during refactoring. It separates fast regression checks from dependency-heavy builds and full-contour smoke checks.


## Root command wrappers

Use `make test-fast` for the normal fast regression baseline before and during refactoring. It wraps the same fast checks listed below and does not run Node builds, full-contour smoke checks, installer checks, FAISS-heavy tests, or local production DB/index checks.

`make test` is an alias for `make test-fast`. It is the default local regression command, not a full CI substitute.

Root targets provided by the repository tooling setup:

```bash
make test
make test-fast
make test-python
make test-boundaries
make build-frontend
make build-crawler
make test-crawler-db
make test-frontend
make test-jobs
make test-framework
make test-smoke-arch
make test-installers-dry-run
make lint
```

The raw commands remain documented below so failures can be debugged without Makefile indirection.

## Fast baseline

These checks should pass before structural refactoring and do not require frontend or crawler Node dependencies:

```bash
python3 -m compileall client/backend engine/server
python3 engine/server/db/jobs/tests/test-interaction-events.py
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

Current behavior-freeze baseline in this environment:

- `python3 -m compileall client/backend engine/server`: PASS.
- `python3 engine/server/db/jobs/tests/test-interaction-events.py`: PASS.
- `bash tests/check-client-engine-boundary.sh`: PASS.
- `bash tests/check-frontend-client-gateway.sh`: PASS.

## Python behavior tests

The behavior-freeze work adds pytest characterization tests around current behavior. The Client backend service split extends the Client backend coverage for publish, profile reset, profile read, and proxy failure paths before moving that behavior into services. The Engine API route split adds Engine API route-dispatch tests before moving Engine route behavior into `engine/server/api/routes/` and `engine/server/api/services/`. The updater module split adds updater job tests for CLI defaults, command construction, locking, staging helpers, sync helpers, service restart behavior, and pipeline command order before splitting updater internals. These tests are intended to freeze observable behavior before code is split or moved. The repository tooling setup configures pytest discovery in `pyproject.toml`, so the complete characterization suite can be run from the repository root with:

```bash
make test-python
python3 -m pytest
```

Individual directories can still be run directly when debugging:

```bash
python3 -m pytest tests/contracts
python3 -m pytest tests/repositories
python3 -m pytest tests/client_backend
python3 -m pytest tests/engine_api
python3 -m pytest tests/recommendations
python3 -m pytest tests/engine_data
python3 -m pytest tests/db
```

The tests should assert externally visible effects: HTTP status codes, JSON fields, SQLite rows, dedup decisions, forwarded payloads, and route boundary behavior. They should not primarily assert that an internal mock was called.


## Job/updater tests

The updater module split separates updater internals while keeping `engine/server/db/jobs/updater-worker.py` as the executable compatibility entrypoint. The fast Python suite includes the updater tests because they use fake command runners, temporary SQLite databases, and temporary lock files instead of real crawler CLIs, systemctl, FAISS, or network calls.

Run only the updater tests with:

```bash
make test-jobs
python3 -m pytest tests/jobs -q
```

Full operational smoke for the updater remains prerequisite-sensitive because it can require Node crawler builds, FAISS/index artifacts, systemd behavior, and dataset files.

## Contract and boundary checks

The existing shell boundary checks remain the source of truth for two current architecture rules:

```bash
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

`tests/contracts/test_current_boundary_scripts.py` runs these scripts from pytest so the boundary rules appear in the normal Python test baseline.


## Crawler database tests

The crawler database split adds TypeScript crawler DB characterization tests. They use temporary SQLite files and Node's built-in test runner after compiling crawler source and tests to `engine/crawler/dist-test/`. These checks require `engine/crawler/node_modules` and are not part of `make test` or `make test-fast`:

```bash
make test-crawler-db

# Equivalent raw command:
cd engine/crawler && npm run test:db
```

Use these tests when changing modules under `engine/crawler/src/db/`. Missing Node dependencies should be treated as a prerequisite issue, not as a Python/product regression.


## Frontend DOM/unit tests

The frontend module split adds Vitest/jsdom tests for extracted frontend rendering and state helpers. These checks require `client/frontend/node_modules` and are not part of `make test` or `make test-fast`:

```bash
make test-frontend

# Equivalent raw command:
cd client/frontend && npm run test
```

Use these tests when changing `client/frontend/src/components`, `client/frontend/src/state`, `client/frontend/src/utils`, or page-controller code that consumes those helpers. Missing Node dependencies should be treated as a prerequisite issue, not as a Python/product regression.

## Node build checks

Frontend and crawler builds are dependency-heavy checks. They require local package installation inside their component directories.

```bash
make build-frontend
make build-crawler

# Equivalent raw commands:
cd client/frontend && npm run build
cd engine/crawler && npm run build
```

Current behavior-freeze baseline in this environment:

- `cd client/frontend && npm run build`: blocked because `vite` is not installed.
- `cd engine/crawler && npm run build`: blocked because `engine/crawler/node_modules/typescript/bin/tsc` is missing.

These are missing-prerequisite failures, not product behavior regressions by themselves.

## Full-contour smoke checks

The full split smoke script starts the Engine and Client locally, exercises the gateway path, sends a Client like action, checks profile likes, and verifies that Engine does not open the Client users DB.

```bash
make test-smoke-arch

# Equivalent raw command:
bash tests/run-arch-split-smoke.sh
```

Use this when the environment has Engine runtime dependencies and usable DB/index/cache inputs. It is not a replacement for the fast characterization tests because it has broader runtime prerequisites.

## Known local prerequisites

- Engine server startup checks may import `faiss` through `engine/server/api/server.py`; route-level tests should avoid broad server startup imports when possible.
- Frontend build requires `npm install` or equivalent in `client/frontend`.
- Crawler build requires `npm install` or equivalent in `engine/crawler`.
- Full-contour smoke requires Engine runtime dependencies and data/index/cache files compatible with the current local configuration.

Current dependency-heavy baseline in this environment:

- `python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit`: PASS after the Engine API route split moved the test to narrow recommendation service imports.
- `python3 engine/server/api/server.py --help`: blocked by missing `faiss` because startup still imports the FAISS-backed ANN path.


### Compatibility shim-removal tests

`tests/compatibility` contains static guards for internal compatibility shims that have been intentionally removed. These tests prevent the old Engine recommendation helper re-export path, the old crawler `db.ts` facade, and recommendation-domain `server_config.py` re-exports from returning.

## How to interpret failures

A fast baseline or behavior-freeze characterization test failure should be treated as a potential behavior regression unless the failure is clearly caused by a documented missing prerequisite.

A Node build or full-contour smoke failure should first be classified as either a dependency/precondition issue or a real product failure. Do not hide missing prerequisites, but do not treat them as code regressions without confirming the prerequisite state.


## Linting

The repository tooling setup adds `ruff` as a development check for a narrow maintained surface. The Client backend service split extends that maintained surface to the Client backend HTTP adapter, services, repositories, and small internal schemas introduced by the Client backend split. Broader lint coverage is still deferred so refactoring stages do not turn into unrelated legacy cleanup:

```bash
python3 -m pip install -r engine/server/requirements-dev.txt
make lint
```

This stage uses `ruff check` only. It does not introduce `ruff format`; broad formatting normalization is deferred so tooling changes do not create unrelated code churn. The Engine API route split extends the maintained lint surface to the Engine API handler adapter, route modules, service modules, and new Engine route tests introduced by the route split.

## Recommendation config and internal type checks

The recommendation pipeline cleanup adds focused recommendation tests for config validation and internal boundary dataclasses:

```bash
python3 -m pytest tests/recommendations/test_config_validation.py tests/recommendations/test_types_characterization.py -q
```

These tests prove that the checked-in recommendation defaults validate, malformed config is rejected early, and internal result objects preserve the current primitive response shape.

## Schema ownership tests

The schema-ownership cleanup adds `tests/db` to the fast Python test suite. These tests use temporary SQLite databases to verify current-shape migration resources, legacy `ensure_*` wrapper equivalence, primary-key contracts, idempotency, and the schema ownership documentation. They do not use production DB files, FAISS, Node dependencies, crawler runtime, or network.

## Framework adapter checks

The FastAPI migration adds FastAPI adapter tests without replacing the existing characterization suite:

```bash
make test-framework
```

These tests verify Client and Engine FastAPI route contracts, stable `server.py` entrypoint paths, CORS/OPTIONS behavior, rate-limit responses, and framework compatibility documentation.

## FastAPI-only adapter tests

The stdlib HTTP cleanup removed the transitional stdlib HTTP route adapters. The FastAPI response-helper cleanup removes the remaining handler-shaped response-helper compatibility, so Client and Engine HTTP behavior tests exercise FastAPI app factories through `TestClient` or framework-neutral `RouteResult` assertions.

```bash
python3 -m pytest tests/client_backend tests/engine_api tests/framework -q
```

Do not add new tests that execute removed stdlib route adapters or fake handler-shaped response helpers. Unknown-route, CORS, rate-limit, invalid-body, and path-id compatibility must be covered through the active FastAPI adapter or framework-neutral route-result/service harnesses.

## Database bootstrap tests

Fast tests include explicit database bootstrap coverage in `tests/db/test_database_bootstrap.py` and a static guard in `tests/db/test_no_direct_runtime_ensure_calls.py`. Tests that verify old `ensure_*` wrappers remain transitional compatibility coverage until the wrapper-deletion stage.
