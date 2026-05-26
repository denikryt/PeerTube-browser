# Testing

This document defines how to verify current PeerTube Browser behavior before and during refactoring. It separates fast regression checks from dependency-heavy builds and full-contour smoke checks.


## Root command wrappers

Use `make test-fast` for the normal fast regression baseline before and during refactoring. It wraps the same fast checks listed below and does not run Node builds, full-contour smoke checks, installer checks, FAISS-heavy tests, or local production DB/index checks.

`make test` is an alias for `make test-fast`. It is the default local regression command, not a full CI substitute.

Root targets provided by Stage 2:

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

Current Stage 0 baseline in this environment:

- `python3 -m compileall client/backend engine/server`: PASS.
- `python3 engine/server/db/jobs/tests/test-interaction-events.py`: PASS.
- `bash tests/check-client-engine-boundary.sh`: PASS.
- `bash tests/check-frontend-client-gateway.sh`: PASS.

## Python behavior tests

Stage 0 adds pytest characterization tests around current behavior. Stage 3 extends the Client backend coverage for publish, profile reset, profile read, and proxy failure paths before moving that behavior into services. Stage 4 adds Engine API route-dispatch tests before moving Engine route behavior into `engine/server/api/routes/` and `engine/server/api/services/`. Stage 9 adds updater job tests for CLI defaults, command construction, locking, staging helpers, sync helpers, service restart behavior, and pipeline command order before splitting updater internals. These tests are intended to freeze observable behavior before code is split or moved. Stage 2 configures pytest discovery in `pyproject.toml`, so the complete characterization suite can be run from the repository root with:

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

Stage 9 splits updater internals while keeping `engine/server/db/jobs/updater-worker.py` as the executable compatibility entrypoint. The fast Python suite includes the updater tests because they use fake command runners, temporary SQLite databases, and temporary lock files instead of real crawler CLIs, systemctl, FAISS, or network calls.

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

Stage 7 adds TypeScript crawler DB characterization tests. They use temporary SQLite files and Node's built-in test runner after compiling crawler source and tests to `engine/crawler/dist-test/`. These checks require `engine/crawler/node_modules` and are not part of `make test` or `make test-fast`:

```bash
make test-crawler-db

# Equivalent raw command:
cd engine/crawler && npm run test:db
```

Use these tests when changing `engine/crawler/src/db.ts` or modules under `engine/crawler/src/db/`. Missing Node dependencies should be treated as a prerequisite issue, not as a Python/product regression.


## Frontend DOM/unit tests

Stage 8 adds Vitest/jsdom tests for extracted frontend rendering and state helpers. These checks require `client/frontend/node_modules` and are not part of `make test` or `make test-fast`:

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

Current Stage 0 baseline in this environment:

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

- `python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit`: PASS after Stage 4 moved the test to narrow recommendation service imports.
- `python3 engine/server/api/server.py --help`: blocked by missing `faiss` because startup still imports the FAISS-backed ANN path.

## How to interpret failures

A fast baseline or Stage 0 characterization test failure should be treated as a potential behavior regression unless the failure is clearly caused by a documented missing prerequisite.

A Node build or full-contour smoke failure should first be classified as either a dependency/precondition issue or a real product failure. Do not hide missing prerequisites, but do not treat them as code regressions without confirming the prerequisite state.


## Linting

Stage 2 adds `ruff` as a development check for a narrow maintained surface. Stage 3 extends that maintained surface to the Client backend HTTP adapter, services, repositories, and small internal schemas introduced by the Client backend split. Broader lint coverage is still deferred so refactoring stages do not turn into unrelated legacy cleanup:

```bash
python3 -m pip install -r engine/server/requirements-dev.txt
make lint
```

This stage uses `ruff check` only. It does not introduce `ruff format`; broad formatting normalization is deferred so tooling changes do not create unrelated code churn. Stage 4 extends the maintained lint surface to the Engine API handler adapter, route modules, service modules, and new Engine route tests introduced by the route split.

## Recommendation config and internal type checks

Stage 5 adds focused recommendation tests for config validation and internal boundary dataclasses:

```bash
python3 -m pytest tests/recommendations/test_config_validation.py tests/recommendations/test_types_characterization.py -q
```

These tests prove that the checked-in recommendation defaults validate, legacy `server_config.py` imports still work, malformed config is rejected early, and internal result objects preserve the current primitive response shape.

## Schema ownership tests

Stage 6 adds `tests/db` to the fast Python test suite. These tests use temporary SQLite databases to verify current-shape migration resources, legacy `ensure_*` wrapper equivalence, primary-key contracts, idempotency, and the schema ownership documentation. They do not use production DB files, FAISS, Node dependencies, crawler runtime, or network.

## Framework adapter checks

Stage 10 adds FastAPI adapter tests without replacing the existing characterization suite:

```bash
make test-framework
```

These tests verify Client and Engine FastAPI route contracts, stable `server.py` entrypoint paths, CORS/OPTIONS behavior, rate-limit responses, and framework compatibility documentation.

## Stage 11 FastAPI-only adapter tests

Stage 11 removes the transitional stdlib HTTP route adapters. Client and Engine HTTP behavior tests now exercise FastAPI app factories through `TestClient`, while direct handler-style harnesses are limited to narrow route/service helpers that still use structural response-helper protocols.

```bash
python3 -m pytest tests/client_backend tests/engine_api tests/framework -q
```

Do not add new tests that execute removed stdlib route adapters. Unknown-route, CORS, rate-limit, invalid-body, and path-id compatibility must be covered through the active FastAPI adapter or narrow service harnesses.
