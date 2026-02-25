# Feature Plans

Canonical storage for `plan feature <id>` outputs.

## Scope ownership

- This file stores plan artifacts only.
- Command semantics/order are defined in `dev/TASK_EXECUTION_PROTOCOL.md`.
- Planning quality requirements are defined in `dev/FEATURE_PLANNING_PROTOCOL.md`.

## Format

Each feature plan section must use the feature ID as a heading and include:
- Dependencies
- Decomposition
- Issue/Task Decomposition Assessment

Canonical per-issue plan block format inside a feature section:
- Heading: `### <issue_id> - <issue_title>` (one block per issue ID).
- Allowed inner headings: only `#### Dependencies`, `#### Decomposition`, `#### Issue/Task Decomposition Assessment`.
- All three inner headings are mandatory for each issue block.

## Planned Features

<!-- Add or update feature plan sections below, for example: -->
<!-- ## F<local>-M<milestone> -->
<!-- ### Dependencies -->
<!-- ... -->

## F4-M1

### Issue Execution Order
1. `I14-F4-M1` - Replace checkbox-based GitHub issue body with description-driven readable content
2. `I15-F4-M1` - Feature materialize: reconcile GitHub sub-issues from DEV_MAP issue set
3. `I17-F4-M1` - Reject issue flow: add Rejected status and close mapped GitHub issue with explicit rejection marker
4. `I26-F4-M1` - Add plan tasks for issues command for batch issue decomposition in one run
5. `I7-F4-M1` - Issue creation command for feature/standalone with optional plan init
6. `I9-F4-M1` - Add workflow CLI show/status commands for feature/issue/task
7. `I13-F4-M1` - Auto-delete sync delta file after successful decomposition write
### Dependencies
- See issue-level dependency blocks below.

### Decomposition
1. Execute follow-up issues in `Issue Execution Order`.
2. Keep per-issue implementation details inside canonical issue-plan blocks.

### Issue/Task Decomposition Assessment
- Decomposition is maintained per issue block; no extra feature-level split is required.

### I17-F4-M1 - Reject issue flow: add Rejected status and close mapped GitHub issue with explicit rejection marker

#### Dependencies
- `dev/workflow_lib/confirm_commands.py`
- `dev/workflow_lib/feature_commands.py`
- `dev/workflow_lib/github_adapter.py`
- `tests/check-workflow-cli-smoke.sh`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`

#### Decomposition
1. Extend issue completion contract with explicit reject transition.
   - Add explicit command contract `reject issue <id>` for feature issue nodes.
   - Command behavior: set local issue status to `Rejected`.
   - Keep deterministic issue-ID validation and ownership checks.
2. Implement local tracker transition to `Rejected`.
   - Persist explicit issue status update to `Rejected` in `DEV_MAP`.
   - Keep terminal-status behavior stable for planning/materialization/execution filters.
3. Implement mapped GitHub issue reject handling.
   - If mapped GitHub issue exists (`gh_issue_number`/`gh_issue_url`), close it in the same reject run.
   - If mapping is missing, keep reject command successful with local status update only (no hard failure).
4. Add regression coverage and docs updates.
   - Cover success path, missing mapping behavior, and idempotent repeated reject attempts.
   - Update protocol/workflow docs for explicit rejected-state semantics.

#### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 3`.
   - Task 1: confirm flow contract and local `Rejected` transition support.
   - Task 2: GitHub reject marker + close behavior with deterministic error/skip contract.
   - Task 3: smoke/docs alignment and repeated-call stability checks.
2. Why `3`:
   - local state transition, GitHub side effects, and regression/docs validation are separate risk domains.

### I14-F4-M1 - Replace checkbox-based GitHub issue body with description-driven readable content

#### Dependencies
- `dev/map/DEV_MAP.json`
- `dev/map/DEV_MAP_SCHEMA.md`
- `dev/workflow_lib/feature_commands.py`
- `dev/workflow_lib/feature_commands.py` (`_apply_issue_delta`, `_build_materialized_issue_body`, `_build_feature_registration_issue_body`, `feature materialize`)
- `dev/workflow_lib/confirm_commands.py`
- `dev/workflow_lib/issue_checklist.py` (cleanup/removal or deprecation path)
- `tests/check-workflow-cli-smoke.sh`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`

#### Decomposition
1. Define issue-level `description` contract for human-readable GitHub bodies.
   - Extend issue node contract in `DEV_MAP` and schema docs with `description`.
   - Description must be short and readable: what the issue is about and why it exists; avoid deep technical detail by default.
   - Extend sync write path so issue `description` is accepted from delta payload and persisted in issue nodes.
2. Add default description generation for new issues.
   - When a new issue has no explicit description, derive one from issue title plus mapped child-task titles/summaries.
   - Keep deterministic fallback text for issues without mapped tasks.
3. Rewrite child issue GitHub body to description-driven content.
   - Rework `_build_materialized_issue_body` to render readable sections based on `description` (no checklist syntax).
   - Keep body concise and issue-focused; remove markdown checkbox transport entirely.
4. Rewrite feature-level GitHub issue body without checkboxes.
   - Rework `_build_feature_registration_issue_body` to a readable feature summary + child issue list.
   - Keep child issue references in plain readable format (id/title/short description), without checkbox state.
5. Decouple completion flow from checkbox parsing/sync.
   - Keep `confirm issue ... done` focused on status transition + GitHub close only.
   - Remove feature-issue body checklist update dependency from confirm/materialize flows.
6. Backfill descriptions for existing issues and sync GitHub bodies.
   - Add `description` text for all existing local issue nodes, using title and child-task context as source.
   - Run GitHub issue body update path for already mapped issues so all existing GitHub issue bodies are converted to the new description-based format.
7. Update tests and docs.
   - Add/adjust smoke assertions for description-based issue body rendering and no-checkbox guarantees.
   - Update protocol/workflow docs to describe the `description`-driven body contract and backfill/sync behavior.

#### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 5`.
   - Task 1: model/schema/sync support for issue `description`.
   - Task 2: default description generation + local backfill for existing issue nodes.
   - Task 3: child issue body rewrite (checkbox-free, readable text).
   - Task 4: feature issue body rewrite + confirm/materialize checklist decoupling.
   - Task 5: smoke/docs alignment + mapped GitHub body resync coverage.
2. Why `5`:
   - description contract, generation/backfill, renderers, and resync/verification are separate risk domains and should be validated independently.

### I15-F4-M1 - Feature materialize sub-issues reconcile for parent feature issue

#### Dependencies
- `dev/map/DEV_MAP.json`
- `dev/workflow_lib/feature_commands.py`
- `dev/workflow_lib/github_adapter.py`
- `tests/check-workflow-cli-smoke.sh`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`

#### Decomposition
1. Add GitHub adapter for sub-issues API operations.
   - Implement list/add helpers for parent issue sub-items via `gh api` (or explicit GraphQL call).
   - Return deterministic errors for unsupported API response or permission failures.
2. Reconcile sub-issues in `feature materialize`.
   - For `--mode issues-sync`, run in one pass: create missing child GitHub issues from DEV_MAP first, then reconcile parent feature sub-issues using the fresh mapped set.
   - For `--mode issues-create`, create only unmapped child issues and then reconcile sub-issues for all mapped child issues.
   - After child issue materialization, compute mapped child issue numbers from DEV_MAP.
   - Compare against current parent feature issue sub-issues and add missing links (idempotent behavior).
   - Keep deterministic output payload (`sub_issues_sync`: attempted/added/skipped/errors).
3. Keep create/sync behavior aligned with partial mappings.
   - If some child issues are not materialized yet (`gh_issue_number/url` missing), skip only those and report them explicitly.
   - At the end of `feature materialize --mode issues-sync`, return explicit output list of such issues (for example `missing_issue_mappings` with issue id + missing fields).
   - Keep output deterministic: include this field in success responses even when the list is empty.
   - Do not fail whole materialize run for skipped-unmapped child issues; continue with successfully created/mapped items.
4. Add smoke coverage and docs.
   - Add fake-gh smoke scenario validating: first run adds missing sub-issue links, second run adds zero (idempotent).
   - Update protocol/workflow docs with sub-issues ownership and sync semantics.

#### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 3`.
   - Task 1: GitHub adapter support for sub-issues API + error contract.
   - Task 2: `feature materialize` reconcile logic and output contract.
   - Task 3: smoke/docs alignment and idempotency verification.
2. Why `3`:
   - integration layer, materialize reconcile logic, and regression coverage are separate risk domains and should be validated independently.

### I26-F4-M1 - Add plan tasks for issues command for batch issue decomposition in one run

#### Dependencies
- `dev/workflow_lib/feature_commands.py`
- `dev/workflow_lib/sync_delta.py`
- `dev/workflow_lib/tracking_writers.py`
- `tests/check-workflow-cli-smoke.sh`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`

#### Decomposition
1. Add batch issue decomposition command in workflow CLI.
   - Register `plan tasks for issues` with repeatable `--issue-id` and shared `--delta-file`.
   - Keep command output deterministic and explicit for multi-issue scope.
2. Implement multi-issue queue validation and filtering.
   - Validate every provided issue ID belongs to selected feature.
   - Reject duplicate IDs and reject delta payloads that contain issues outside requested queue.
3. Execute batch decomposition in one write transaction.
   - Apply one `task_count` allocation pass for all selected issues so cross-issue task references are deterministic.
   - Support one `pipeline.overlaps_append` payload that can include both new cross-issue task pairs and pairs with existing pipeline task IDs.
4. Cover behavior with smoke tests and docs.
   - Add success case for `plan tasks for issues` with multiple issue IDs and overlap entries.
   - Add failure cases for duplicate issue IDs and non-owned issue IDs.
   - Update protocol/workflow docs with the new command syntax and constraints.

#### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 3`.
   - Task 1: CLI surface and multi-issue argument contract.
   - Task 2: multi-issue filter/execution path with one-pass allocation and overlap support.
   - Task 3: smoke and docs alignment for success/failure contracts.
2. Why `3`:
   - command surface, core decomposition semantics, and regression/docs validation are separate risk domains.
