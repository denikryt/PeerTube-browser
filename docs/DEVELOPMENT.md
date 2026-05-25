# Development

## Purpose

This document explains how to navigate and verify the project during refactoring.

## Main Areas

```text
client/backend        browser-facing API, local profile/write state, Engine gateway
client/frontend       web UI and Client API calls
engine/server/api     Engine HTTP API, recommendations, metadata, internal ingest
engine/server/data    Engine data access and SQLite read helpers
engine/server/db/jobs data-build, updater, embedding, index, and cache jobs
engine/crawler        PeerTube crawler source and schema

docs                  product and operational documentation
plans                 implementation plans
tests                 characterization, contract, repository, and smoke tests
```

## Verification

Use `docs/TESTING.md` as the source of truth for current verification commands and prerequisites.

Fast refactor checks currently include:

```bash
python3 -m compileall client/backend engine/server
python3 engine/server/db/jobs/tests/test-interaction-events.py
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
python3 -m pytest tests/contracts tests/repositories tests/client_backend tests/engine_api tests/recommendations tests/engine_data -q
```

Dependency-heavy checks such as frontend/crawler builds require local Node dependencies first.

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
