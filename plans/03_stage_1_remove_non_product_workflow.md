# Stage 1: Remove Non-Product Workflow Infrastructure

## Problem / Goal

Stage 1 removes obsolete local planning/agent workflow infrastructure from the active repository while preserving the working PeerTube Browser product behavior frozen by Stage 0.

The project currently contains two different systems in one tree:

```text
PeerTube Browser product
  crawler -> SQLite datasets/indexes -> Engine API -> Client backend API -> Frontend

Old local workflow/tracker system
  .agents/*
  dev/workflow
  dev/workflow_lib/*
  dev/map/*
  dev/TASK_LIST.json
  dev/TASK_EXECUTION_PIPELINE.json
  dev/ISSUE_DEP_INDEX.json
  dev/ISSUE_OVERLAPS.json
  dev/FEATURE_PLANS.md
  tests/workflow/*
```

The second system is not part of the product runtime. It makes the repository harder to read, pulls test attention toward obsolete behavior, and exposes agent/task-management concepts that do not belong in the normal developer path.

Stage 1 must make the repository product-oriented without changing runtime behavior, API behavior, crawler commands, recommendation behavior, installer behavior, or data-build behavior.

The working behavior protected by Stage 0 must remain valid:

```text
Frontend -> Client backend -> Engine API
Client profile/write state remains Client-owned
Engine read/recommendation/internal ingest behavior remains Engine-owned
Crawler/data-build commands continue to use generated crawler dist files after npm build
```

## Expected Behavior

After Stage 1:

- Product code behavior is unchanged.
- Product tests from Stage 0 still pass.
- The repository no longer contains active old agent/workflow implementation files.
- The repository no longer contains workflow-specific tests or dev-map viewer smoke checks.
- Generated crawler JavaScript files are no longer committed, but the generated `engine/crawler/dist/` directory remains the expected output of `npm run build`.
- Documentation clearly presents PeerTube Browser as the product, not the old local workflow system.
- Human-readable project direction is preserved in normal documentation, not in old tracker JSON/MD files.
- New contributors can start from `README.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`, `docs/TESTING.md`, and `docs/ROADMAP.md` without reading `.agents/` or `dev/workflow_lib/`.
- Any deleted workflow material remains recoverable through Git history; Stage 1 does not need to keep an `_archive/` copy inside the active tree.

Concrete preserved behavior examples:

```bash
python3 -m compileall client/backend engine/server
python3 -m pytest tests/contracts tests/repositories tests/client_backend tests/engine_api tests/recommendations tests/engine_data -q
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

Expected result: all continue to pass.

Concrete crawler build contract after removing committed `dist/`:

```bash
cd engine/crawler
npm install
npm run build
npm run crawl:instances -- --help
```

Expected result when Node dependencies are installed: TypeScript compiles into `engine/crawler/dist/`, and existing npm script names continue to invoke `node dist/*.js`.

If Node dependencies are not installed, this remains a documented missing-prerequisite failure, not a Stage 1 product regression.

## Architecture

Stage 1 does not change runtime architecture.

Current product architecture remains:

```text
client/frontend
  -> client/backend HTTP API
      -> client/backend local users DB
      -> Engine HTTP API gateway calls
      -> Engine internal event ingest
engine/server/api
  -> engine/server/data
  -> SQLite datasets/caches/signals
engine/crawler + engine/server/db/jobs
  -> build/update SQLite datasets and derived artifacts
```

Stage 1 changes repository organization only:

```text
Before:
  product files + old workflow files + generated crawler dist files

After:
  product files + product docs + product tests + plans
```

The old workflow files should be removed from the active tree, not moved under `_archive/`, because Git history is already the archive and an in-tree archive would still force developers to distinguish active from obsolete code.

The only historical planning content that may be preserved is product-facing direction. It should be rewritten into `docs/ROADMAP.md` using readable product milestones from `dev/MILESTONES.md` and selected product items from `dev/PROJECT_FEATURES.md`. Do not preserve tracker status, issue IDs, task IDs, GitHub issue mappings, DEV_MAP schema rules, overlap indexes, or workflow command semantics.

## Touched Files

```text
AGENTS.md
README.md
.gitignore
docs/DATA_BUILD.md
docs/DEPLOYMENT.md
docs/TESTING.md
engine/server/db/jobs/docs/UPDATER_WORKER.md
engine/server/db/jobs/updater-worker.py
engine/server/db/jobs/tests/test-orchestrator-smoke.py
engine/crawler/package.json
tests/check-client-engine-boundary.sh
tests/check-frontend-client-gateway.sh
tests/check-dev-map-viewer-smoke.sh
tests/contracts/test_current_boundary_scripts.py
.agents/protocols/feature-planning-protocol.md
.agents/protocols/task-execution-protocol.md
.agents/rules/docstring-constraints.md
.agents/rules/execution-triggers.md
.agents/rules/feature-planning.md
.agents/rules/implementation-constraints.md
.agents/rules/tracking-state.md
.agents/workflows/*.md
dev/workflow
dev/workflow_lib/*.py
dev/map/*
dev/FEATURE_PLANS.md
dev/ISSUE_DEP_INDEX.json
dev/ISSUE_OVERLAPS.json
dev/MILESTONES.md
dev/MILESTONES_FEATURES.md
dev/MILESTONES_FEATURES_WITH_VERIFICATION.md
dev/MILESTONES_PLAN.md
dev/PROJECT_FEATURES.md
dev/TASK_EXECUTION_PIPELINE.json
dev/TASK_LIST.json
tests/workflow/*.py
engine/crawler/dist/*.js
```

Most files in this list should be deleted or updated only as documentation/static references. Runtime code changes should be avoided unless a reference check proves they are necessary.

## New Files

```text
plans/03_stage_1_remove_non_product_workflow.md
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/ROADMAP.md
```

Optional only if needed to keep Stage 1 verification clear:

```text
docs/REMOVED_WORKFLOW.md
```

Do not add broad tooling files such as `pyproject.toml`, `Makefile`, `pre-commit`, or dependency split files in Stage 1. Those belong to Stage 2 unless Stage 1 discovers a narrow blocker that cannot be handled otherwise.

## Implementation Steps

### 1. Run the Stage 0 fast baseline before deleting anything

Run:

```bash
python3 -m compileall client/backend engine/server
python3 engine/server/db/jobs/tests/test-interaction-events.py
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
python3 -m pytest tests/contracts tests/repositories tests/client_backend tests/engine_api tests/recommendations tests/engine_data -q
```

Expected result:

```text
compileall: PASS
interaction event script: PASS
boundary shell scripts: PASS
Stage 0 pytest suite: PASS
```

Do not start deletion if the baseline is already broken. Record any existing failure as a pre-existing Stage 0 regression and stop.

### 2. Inventory obsolete workflow artifacts and active references

Run reference searches before deleting files:

```bash
grep -RIn --exclude-dir=.git \
  -E '(\.agents|dev/workflow|workflow_lib|TASK_LIST|TASK_EXECUTION_PIPELINE|ISSUE_DEP_INDEX|ISSUE_OVERLAPS|FEATURE_PLANS|PROJECT_FEATURES|MILESTONES|tests/workflow|dev/map|engine/crawler/dist)' \
  .
```

Then repeat excluding obsolete directories to find references in active files:

```bash
grep -RIn \
  --exclude-dir=.git \
  --exclude-dir=.agents \
  --exclude-dir=dev \
  --exclude-dir='tests/workflow' \
  -E '(\.agents|dev/workflow|workflow_lib|TASK_LIST|TASK_EXECUTION_PIPELINE|ISSUE_DEP_INDEX|ISSUE_OVERLAPS|FEATURE_PLANS|PROJECT_FEATURES|MILESTONES|tests/workflow|dev/map|engine/crawler/dist)' \
  .
```

Current known active references from plan preparation:

```text
engine/server/db/jobs/docs/UPDATER_WORKER.md
  references Crawler CLIs from engine/crawler/dist/*.js

engine/server/db/jobs/updater-worker.py
  expects crawler_dir/dist/*.js at runtime after build

engine/server/db/jobs/tests/test-orchestrator-smoke.py
  expects dist CLI names in worker command/log assertions

tests/check-dev-map-viewer-smoke.sh
  references dev/map/dev-map.js and should be removed with dev/map

plans/01_project_refactor_preserve_behavior.md
  intentionally describes old workflow removal and should remain as historical refactor planning context
```

The `engine/crawler/dist` references in updater runtime code are not obsolete. They describe generated build outputs and should remain unless Stage 7 changes crawler execution. Stage 1 should update docs/comments only where they imply committed dist files.

### 3. Create product-facing documentation before removing old planning files

Create `docs/ROADMAP.md` from readable product-level content, not workflow tracker state.

Source content to use:

```text
dev/MILESTONES.md
  product milestone direction and staged product goals

dev/PROJECT_FEATURES.md
  broad Engine/Client/documentation ideas
```

Rules for the new roadmap:

- Preserve product direction, not task tracker metadata.
- Do not copy DEV_MAP issue IDs, task IDs, GitHub issue URLs, status transitions, overlap metadata, or workflow command descriptions.
- Keep roadmap language explicitly non-binding because Stage 1 is cleanup, not product planning.
- Mark old ActivityPub/federation items as future ideas, not active Stage 1 scope.

Suggested `docs/ROADMAP.md` structure:

```text
# Roadmap

## Purpose
This document captures product direction for PeerTube Browser. It is not a task tracker.

## Near-term cleanup
- preserve behavior with regression tests
- remove obsolete workflow infrastructure
- clarify architecture and developer setup
- split large Client/Engine modules in later stages

## Runtime and API modernization
- stabilize Engine/Client contracts
- migrate API runtime only after behavior is protected
- publish API documentation later

## Discovery and recommendation work
- feed modes
- search
- similarity/recommendation improvements
- indexing stability

## Crawler and data build
- schema/migration ownership
- incremental refresh reliability
- scope control

## Frontend and Client
- component-oriented frontend
- profile/like behavior
- future auth/profile work

## Future federation work
- ActivityPub/federation support remains future work and must be separately planned
```

Create `docs/ARCHITECTURE.md` as a short component ownership document.

Minimum content:

```text
# Architecture

## Purpose
Defines current PeerTube Browser component boundaries.

## Runtime flow
crawler -> SQLite/index/cache -> Engine API -> Client backend -> Frontend

## Ownership boundaries
Frontend: UI and Client API calls only.
Client backend: browser-facing gateway, local profile/write state, Engine HTTP gateway.
Engine API: read/recommendation/internal ingest endpoints and Engine data reads.
Crawler/jobs: data collection and derived artifact generation.

## Forbidden coupling
Frontend must not call Engine directly.
Client backend must not import Engine internals or read Engine DB files directly.
Engine must not own Client local user profile state.
```

Create `docs/DEVELOPMENT.md` as a short orientation document.

Minimum content:

```text
# Development

## Purpose
Explains how to navigate and verify the project during refactoring.

## Main areas
client/backend
client/frontend
engine/server/api
engine/server/data
engine/server/db/jobs
engine/crawler

docs
plans
tests

## Verification
Point to docs/TESTING.md and list Stage 0 fast checks.

## Generated files
engine/crawler/dist and client/frontend/dist are build outputs and should not be committed.
```

### 4. Replace `AGENTS.md` with project-general rules

The current `AGENTS.md` still contains rules from a different bridge/thread/comment workflow context. Replace it with concise general rules for this repository.

The new file should keep these concepts:

- preserve behavior before refactoring;
- write characterization/regression tests for behavior changes;
- prefer pytest for product behavior tests;
- keep bash for static boundary checks and smoke wrappers;
- test observable effects rather than internal call counts;
- keep component responsibilities narrow;
- maintain docs with code changes;
- write plans in `plans/` when explicitly requested.

The new file should not mention:

```text
post/thread creation
comment/message fanout
reply/parent resolution
subscription/community/thread mapping
old local workflow commands
.agents workflows
DEV_MAP/TASK_LIST lifecycle rules
```

This change is documentation/rules cleanup only. It must not change product behavior.

### 5. Remove obsolete workflow implementation and tracker files

Delete from the active tree:

```text
.agents/
dev/workflow
dev/workflow_lib/
dev/map/
dev/FEATURE_PLANS.md
dev/ISSUE_DEP_INDEX.json
dev/ISSUE_OVERLAPS.json
dev/MILESTONES.md
dev/MILESTONES_FEATURES.md
dev/MILESTONES_FEATURES_WITH_VERIFICATION.md
dev/MILESTONES_PLAN.md
dev/PROJECT_FEATURES.md
dev/TASK_EXECUTION_PIPELINE.json
dev/TASK_LIST.json
tests/workflow/
tests/check-dev-map-viewer-smoke.sh
```

Rationale:

- `.agents/` describes the old agent workflow system, not PeerTube Browser runtime behavior.
- `dev/workflow` and `dev/workflow_lib/` implement the old local tracker CLI.
- `dev/map/` stores old viewer/schema artifacts for the tracker.
- tracker JSON/MD files are old planning state, not active product documentation.
- `tests/workflow/` tests the old tracker system and should not be part of the product test suite.
- `tests/check-dev-map-viewer-smoke.sh` only validates `dev/map` viewer artifacts and becomes obsolete with `dev/map` removal.

Do not delete:

```text
docs/subtree-workflow.md
```

unless a reference audit proves it is the same obsolete tracker workflow. Its current name suggests repository subtree workflow documentation, which may be unrelated to `.agents`/`dev/workflow`.

### 6. Remove committed generated crawler output

Delete committed generated files:

```text
engine/crawler/dist/*.js
```

Do not change npm script names in `engine/crawler/package.json` during Stage 1. They currently use `node dist/*.js`, and that remains correct after running:

```bash
cd engine/crawler
npm run build
```

Update `.gitignore` to prevent generated outputs from returning:

```gitignore
# Build outputs
engine/crawler/dist/
client/frontend/dist/

# Python caches
__pycache__/
*.py[cod]
.pytest_cache/
```

Keep existing local DB/index ignore rules.

Update documentation that references crawler dist to clarify generated output:

```text
engine/server/db/jobs/docs/UPDATER_WORKER.md
```

Change wording from:

```text
Crawler CLIs from engine/crawler/dist/*.js
```

to:

```text
Crawler CLIs generated by `cd engine/crawler && npm run build` into `engine/crawler/dist/*.js`
```

Do not change `engine/server/db/jobs/updater-worker.py` in Stage 1. It correctly expects built CLIs at runtime. Changing worker execution belongs to Stage 7 or Stage 9.

### 7. Update README navigation without changing product claims

Update `README.md` only where needed to point readers toward the new product docs.

Add or adjust a short documentation section:

```text
## Documentation
- docs/ARCHITECTURE.md: component boundaries and runtime flow.
- docs/DEVELOPMENT.md: local navigation and verification commands.
- docs/TESTING.md: regression and smoke test guidance.
- docs/DATA_BUILD.md: crawler and dataset build flow.
- docs/DEPLOYMENT.md: service installation and runtime deployment.
- docs/ROADMAP.md: product direction, not a task tracker.
```

Do not expand README into a long implementation guide. Stage 1 should reduce confusion, not move all docs into README.

### 8. Search again and classify remaining references

After deletion and docs updates, rerun:

```bash
grep -RIn \
  --exclude-dir=.git \
  -E '(\.agents|dev/workflow|workflow_lib|TASK_LIST|TASK_EXECUTION_PIPELINE|ISSUE_DEP_INDEX|ISSUE_OVERLAPS|FEATURE_PLANS|PROJECT_FEATURES|MILESTONES|tests/workflow|dev/map)' \
  .
```

Allowed remaining references:

```text
plans/01_project_refactor_preserve_behavior.md
plans/03_stage_1_remove_non_product_workflow.md
```

Potentially allowed if added intentionally:

```text
docs/ROADMAP.md
```

Only if it explains that old tracker state was replaced by this product roadmap and does not describe old workflow commands as active.

No active README, product docs, runtime code, installer scripts, or smoke scripts should reference deleted workflow commands/files.

For crawler dist references, allowed remaining references:

```text
engine/crawler/package.json
engine/server/db/jobs/updater-worker.py
engine/server/db/jobs/tests/test-orchestrator-smoke.py
engine/server/db/jobs/docs/UPDATER_WORKER.md
docs/DATA_BUILD.md
docs/DEPLOYMENT.md
docs/TESTING.md
```

These references are valid only when they describe generated build outputs, not committed files.

### 9. Run verification after cleanup

Run the same checks as pre-cleanup:

```bash
python3 -m compileall client/backend engine/server
python3 engine/server/db/jobs/tests/test-interaction-events.py
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
python3 -m pytest tests/contracts tests/repositories tests/client_backend tests/engine_api tests/recommendations tests/engine_data -q
```

Expected result:

```text
PASS
```


Do not require Node builds in Stage 1 unless dependencies are installed. If attempted, expected prerequisite-sensitive commands remain:

```bash
cd client/frontend && npm run build
cd engine/crawler && npm run build
```

If dependencies are missing, document the failure as an environment prerequisite, not a Stage 1 regression.

### 10. Stop conditions

Stop and update this plan before continuing if any of these occur:

- A product runtime file imports or executes `dev/workflow`, `dev/workflow_lib`, or `.agents` content.
- An installer script depends on committed `engine/crawler/dist/*.js` being present before `npm run build`.
- Removing `tests/check-dev-map-viewer-smoke.sh` breaks an active product smoke script.
- A Stage 0 product characterization test fails after workflow deletion.
- `docs/MILESTONES.md` or `dev/PROJECT_FEATURES.md` contains product direction that cannot be safely summarized into `docs/ROADMAP.md` without losing important current project commitments.
- `docs/subtree-workflow.md` is discovered to be part of the old agent/task tracker system rather than repository subtree operations.
- Any proposed edit requires changing Client/Engine route behavior, recommendation behavior, crawler command semantics, updater stage order, or installer behavior.

## Tests

Stage 1 uses the existing Stage 0 product tests, boundary checks, and reference-audit commands as regression guards. It does not add new tests.

Required pre-cleanup tests:

```bash
python3 -m compileall client/backend engine/server
python3 engine/server/db/jobs/tests/test-interaction-events.py
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
python3 -m pytest tests/contracts tests/repositories tests/client_backend tests/engine_api tests/recommendations tests/engine_data -q
```

Required post-cleanup tests:

```bash
python3 -m compileall client/backend engine/server
python3 engine/server/db/jobs/tests/test-interaction-events.py
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
python3 -m pytest tests/contracts tests/repositories tests/client_backend tests/engine_api tests/recommendations tests/engine_data -q
```


Reference-audit commands:

```bash
grep -RIn \
  --exclude-dir=.git \
  -E '(\.agents|dev/workflow|workflow_lib|TASK_LIST|TASK_EXECUTION_PIPELINE|ISSUE_DEP_INDEX|ISSUE_OVERLAPS|FEATURE_PLANS|PROJECT_FEATURES|MILESTONES|tests/workflow|dev/map)' \
  .
```

Dependency-heavy checks, if prerequisites are installed:

```bash
cd client/frontend && npm run build
cd engine/crawler && npm run build
```

These are not mandatory in a clean environment without Node dependencies. `docs/TESTING.md` already records them as prerequisite-sensitive checks.

## Regression and Blind-Spot Analysis

Regressions Stage 1 must catch:

- Product tests fail after deleting non-product workflow files.
- Frontend boundary checks accidentally get deleted or weakened while removing workflow tests.
- Client backend boundary checks accidentally get deleted or weakened while removing workflow tests.
- Runtime code or installers still reference deleted old workflow files.
- The updater documentation incorrectly implies crawler `dist` files are committed rather than generated.
- `engine/crawler/dist/*.js` files return to Git after being removed.
- README continues to send developers into obsolete `.agents` or `dev/workflow` material.
- Useful product roadmap material is lost instead of being converted to normal documentation.

Blind spots that remain after Stage 1:

- The repository still lacks full root-level tooling; Stage 2 owns `Makefile`, `pyproject.toml`, lint/typecheck, and dependency grouping.
- Large runtime modules are still large; Stages 3 and 4 own Client/Engine splitting.
- Crawler source modules are still large; Stage 7 owns crawler refactor.
- Updater worker still invokes generated `dist/*.js`; Stage 9 owns updater/job rationalization.
- Frontend page code is still large; Stage 8 owns frontend code organization.
- Documentation added in Stage 1 is intentionally concise and may need expansion in later stage-specific plans.

## Expected Conflicts and Compatibility Risks

- `engine/server/db/jobs/updater-worker.py` requires `engine/crawler/dist/*.js` at runtime. Removing committed `dist` files is safe only if documentation remains clear that `npm run build` must run before updater usage.
- `engine/server/db/jobs/tests/test-orchestrator-smoke.py` asserts CLI names like `instances-cli.js` and `videos-cli.js`. These assertions should remain because they describe generated runtime command names, not committed files.
- `tests/check-dev-map-viewer-smoke.sh` is outside `tests/workflow/`, so it must be removed explicitly with `dev/map/`.
- Some old tracker files contain broad product roadmap ideas. Preserve direction in `docs/ROADMAP.md` before deleting those files.
- `AGENTS.md` currently contains non-project-specific bridge/thread/comment rules. Replacing it may affect future agent behavior, but it should improve alignment with this repository.
- If a contributor expected the old workflow CLI to remain available, Stage 1 removes that path. The compatibility mechanism is Git history, not active-tree support.

## Generic vs Project-Specific Behavior

Generic behavior:

- Remove obsolete non-product infrastructure after tests freeze current behavior.
- Keep generated build artifacts out of Git.
- Preserve useful human-readable planning information as normal documentation.
- Use existing tests and reference-audit checks to verify cleanup without changing product behavior.

Project-specific behavior:

- PeerTube Browser product flow remains `crawler -> SQLite/index/cache -> Engine API -> Client backend -> Frontend`.
- Frontend must continue to use the Client backend gateway.
- Client backend must not import Engine internals or read Engine DB files directly.
- Engine updater jobs currently execute generated crawler CLIs from `engine/crawler/dist/*.js`.
- Old `.agents`, `dev/workflow`, `dev/workflow_lib`, `dev/map`, and tracker JSON/MD files are not part of PeerTube Browser runtime behavior.

## Open Questions

- Should `docs/ROADMAP.md` preserve only the milestone structure from `dev/MILESTONES.md`, or also include a condensed idea backlog from `dev/PROJECT_FEATURES.md`?
- Should the old workflow files be deleted outright, as this plan recommends, or moved to `_archive/old-agent-workflow/` for one transitional commit despite the added repository noise?
- Should `AGENTS.md` be simplified during Stage 1, or should it be handled as a separate rules-cleanup commit before Stage 1 implementation?
- Should `docs/ARCHITECTURE.md` and `docs/DEVELOPMENT.md` be minimal Stage 1 orientation docs, or should Stage 1 only add placeholders and leave fuller docs to Stage 2?
- Should `docs/subtree-workflow.md` remain unchanged after the reference audit, or does it also contain obsolete workflow language that should be renamed or rewritten?
- Should Stage 1 add an explicit CI-like command in documentation for the post-cleanup pytest set, or wait until Stage 2 root tooling?
