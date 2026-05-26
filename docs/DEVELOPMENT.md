# Development

## Purpose

This document explains how to navigate and verify the project during refactoring.

## Main Areas

```text
client/backend        browser-facing API, local profile/write state, Engine gateway
client/backend/services  Client backend behavior split behind the HTTP handler
client/backend/repositories Client-owned SQLite persistence wrappers
client/frontend       web UI and Client API calls
engine/server/api     Engine HTTP API, recommendations, metadata, internal ingest
engine/server/data    Engine data access and SQLite read helpers
engine/server/db/jobs data-build, updater, embedding, index, and cache jobs
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
