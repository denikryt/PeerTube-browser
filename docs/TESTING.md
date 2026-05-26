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

Stage 0 adds pytest characterization tests around current behavior. They are intended to freeze observable behavior before code is split or moved. Stage 2 configures pytest discovery in `pyproject.toml`, so the complete characterization suite can be run from the repository root with:

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
```

The tests should assert externally visible effects: HTTP status codes, JSON fields, SQLite rows, dedup decisions, forwarded payloads, and route boundary behavior. They should not primarily assert that an internal mock was called.

## Contract and boundary checks

The existing shell boundary checks remain the source of truth for two current architecture rules:

```bash
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

`tests/contracts/test_current_boundary_scripts.py` runs these scripts from pytest so the boundary rules appear in the normal Python test baseline.

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

- Engine server API tests may import `faiss` through `engine/server/api/server.py` or broad Engine server import paths.
- Frontend build requires `npm install` or equivalent in `client/frontend`.
- Crawler build requires `npm install` or equivalent in `engine/crawler`.
- Full-contour smoke requires Engine runtime dependencies and data/index/cache files compatible with the current local configuration.

Current dependency-heavy baseline in this environment:

- `python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit`: blocked by missing `faiss`.

## How to interpret failures

A fast baseline or Stage 0 characterization test failure should be treated as a potential behavior regression unless the failure is clearly caused by a documented missing prerequisite.

A Node build or full-contour smoke failure should first be classified as either a dependency/precondition issue or a real product failure. Do not hide missing prerequisites, but do not treat them as code regressions without confirming the prerequisite state.


## Linting

Stage 2 adds `ruff` as a development check for a narrow maintained surface: the boundary contract tests and small Client backend utility modules. Broader lint coverage is deferred so Stage 2 does not turn into unrelated legacy cleanup:

```bash
python3 -m pip install -r engine/server/requirements-dev.txt
make lint
```

This stage uses `ruff check` only. It does not introduce `ruff format`; broad formatting normalization is deferred so tooling changes do not create unrelated code churn.
