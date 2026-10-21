# Roadmap

## Purpose

This document captures product direction for PeerTube Browser. It is not a task tracker and does not define implementation order for a specific commit.

## Near-Term Cleanup

- Preserve current behavior with characterization and regression tests.
- Remove obsolete non-product workflow infrastructure from the active repository.
- Clarify architecture, development, testing, data-build, and deployment documentation.
- Split large Client and Engine modules in later stages without changing behavior first.

## Runtime and API Modernization

- Stabilize the Client-to-Engine contract.
- Keep gateway boundaries explicit and testable.
- Consider API framework migration only after behavior is protected and route responsibilities are separated.
- Publish API documentation after request/response shapes are explicit and stable.

## Discovery and Recommendation Work

- Improve feed modes such as random, popular, fresh, similar, and recommendations.
- Keep recommendation scoring, filtering, mixing, and fallback behavior deterministic enough to test.
- Add search and scoped discovery features after the core API contract is stable.
- Improve cache and index refresh behavior without breaking existing feed behavior.

## Crawler and Data Build

- Clarify schema and migration ownership.
- Improve incremental refresh reliability.
- Keep crawler command names and data outputs stable while internals are reorganized.
- Add stronger fake PeerTube API and temporary SQLite coverage when crawler code changes.

## Frontend and Client

- Refactor frontend pages toward clearer API, state, and component boundaries.
- Preserve the Client backend as the browser-facing gateway.
- Improve profile, likes, and interaction flows through tested behavior changes.
- Consider authentication/profile features only through separate plans.

## Future Federation Work

ActivityPub and federation support remain future ideas. They must be separately planned and must distinguish generic ActivityPub behavior, PeerTube-specific behavior, and this project's local Client-to-Engine compatibility behavior.
