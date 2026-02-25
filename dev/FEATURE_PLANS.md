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
1. `I24-F4-M1` - Remove approve feature plan command and approval gate from workflow lifecycle
2. `I23-F4-M1` - Issue lifecycle status contract: Pending -> Planned -> Tasked with planning/materialize gates
3. `I22-F4-M1` - Feature materialize: support multi-issue queue in one command run
4. `I25-F4-M1` - Automate `plan issue` command with canonical issue-plan block upsert and scoped lint
5. `I14-F4-M1` - Replace checkbox-based GitHub issue body with description-driven readable content
6. `I15-F4-M1` - Feature materialize: reconcile GitHub sub-issues from DEV_MAP issue set
7. `I17-F4-M1` - Reject issue flow: add Rejected status and close mapped GitHub issue with explicit rejection marker
8. `I7-F4-M1` - Issue creation command for feature/standalone with optional plan init
9. `I9-F4-M1` - Add workflow CLI show/status commands for feature/issue/task
10. `I13-F4-M1` - Auto-delete sync delta file after successful decomposition write
### Dependencies
- See issue-level dependency blocks below.

### Decomposition
1. Execute follow-up issues in `Issue Execution Order`.
2. Keep per-issue implementation details inside canonical issue-plan blocks.

### Issue/Task Decomposition Assessment
- Decomposition is maintained per issue block; no extra feature-level split is required.

### I24-F4-M1 - Remove approve feature plan command and approval gate from workflow lifecycle

#### Dependencies
- `dev/workflow_lib/feature_commands.py`
- `dev/workflow_lib/cli.py`
- `dev/workflow_lib/validate_commands.py`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`
- `dev/FEATURE_PLANNING_PROTOCOL.md`
- `tests/check-workflow-cli-smoke.sh`

#### Decomposition
1. Remove `feature approve` command from CLI surface.
   - Delete command registration/handler wiring for `feature approve`.
   - Ensure help/usage output no longer advertises this command.
2. Remove approval status gate from all feature workflow command paths.
   - Remove checks that require feature status `Approved` before `plan tasks for ...`.
   - Remove checks that require feature status `Approved` before `feature materialize`.
   - Remove checks that require feature status `Approved` for `feature execution-plan`.
   - Remove checks in validation commands that expect feature status `Approved` / `Done` as a precondition.
3. Run full `Approved`-dependency audit and remove remaining gates.
   - Search all workflow commands/protocol validators/docs for `Approved` as mandatory status gate.
   - Remove every mandatory dependency on `Approved` status (runtime, validation, and command-contract text).
4. Normalize process contract to no-approve lifecycle.
   - Update canonical protocol/workflow docs to remove `approve feature plan` step and references.
   - Keep feature status for lifecycle/reporting only, without any execution/planning/materialize gating role.
5. Add regression coverage.
   - Add smoke assertions that `feature approve` is unsupported.
   - Add smoke assertions that `plan tasks for ...`, `feature materialize`, `feature execution-plan`, and `validate --feature` are not blocked by missing `Approved` feature status.
   - Add guard assertion that no workflow command fails with error text expecting `Approved` status.

#### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 4`.
   - Task 1: CLI command removal + routing cleanup (`feature approve`).
   - Task 2: remove `Approved` gates from all feature command handlers (`plan tasks`, `materialize`, `execution-plan`) and validators.
   - Task 3: run/encode full `Approved`-dependency audit so no remaining mandatory gate exists.
   - Task 4: protocol/docs/smoke updates for no-approve lifecycle.
2. Why `4`:
   - CLI surface removal, runtime gate cleanup, repo-wide dependency audit, and regression/docs are separate risk domains.

### I23-F4-M1 - Issue lifecycle status contract: Pending -> Planned -> Tasked with planning/materialize gates

#### Dependencies
- `dev/map/DEV_MAP.json`
- `dev/map/DEV_MAP_SCHEMA.md`
- `dev/workflow_lib/feature_commands.py`
- `dev/workflow_lib/task_commands.py`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`
- `tests/check-workflow-cli-smoke.sh`

#### Decomposition
1. Define canonical issue lifecycle statuses and transitions in workflow logic/docs.
   - `Pending` is assigned at issue creation.
   - `Planned` is assigned when issue-plan block is created/recognized.
   - `Tasked` is assigned after successful task decomposition (`plan tasks for issue` / `plan tasks for feature` for that issue).
2. Enforce planning gate for task decomposition.
   - Reject `plan tasks for issue` / `plan tasks for feature` attempts for issue nodes with status `Pending`.
   - Return deterministic error with required next action (`plan issue <issue_id>`).
3. Enforce materialization gate by issue status.
   - Allow issue materialization only for issue nodes with status `Tasked`.
   - Reject materialize run when selected issue set contains non-`Tasked` issue status.
4. Keep execution materialization gate explicit.
   - Preserve explicit check that execution is blocked when issue `gh_issue_number` / `gh_issue_url` are missing.
   - Align protocol/workflow wording with this gate.
5. Add regression coverage and protocol updates.
   - Add smoke checks for status transitions/gates (`Pending -> Planned -> Tasked` and blocked paths).
   - Update protocol/workflow docs to use the same status contract and gate wording.

#### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 4`.
   - Task 1: status contract + transition hooks (`Pending/Planned/Tasked`) in planning flow.
   - Task 2: decomposition gate (reject task planning from `Pending` issues).
   - Task 3: materialize gate (require `Tasked` for materialized issue nodes).
   - Task 4: smoke/docs alignment for new lifecycle and gate behavior.
2. Why `4`:
   - status transitions, decomposition gate, materialize gate, and regression/docs are separate change domains.

### I22-F4-M1 - Feature materialize: support multi-issue queue in one command run

#### Dependencies
- `dev/workflow_lib/feature_commands.py`
- `dev/workflow_lib/cli.py`
- `tests/check-workflow-cli-smoke.sh`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`

#### Decomposition
1. Extend materialize CLI input contract from one optional issue selector to an ordered issue queue.
   - Replace single-value parsing (`--issue-id`) with repeatable queue parsing that preserves user-provided order.
   - Keep `--mode bootstrap` incompatible with any issue selectors.
   - Expected result: materialize command accepts multiple issue IDs in one run without ambiguous ordering.
2. Add queue validation and issue-node resolution in materialize flow.
   - Validate each requested issue ID format and ownership (`I*-F*-M*` belongs to target feature).
   - Resolve only requested issue nodes and fail deterministically when any requested issue is missing.
   - Handle duplicate issue IDs deterministically (reject duplicate queue entries with clear error).
   - Expected result: issue selection is deterministic, safe, and explicit before any GitHub side effects.
3. Execute materialization loop against the resolved queue for `issues-create` and `issues-sync`.
   - Reuse current per-issue create/update/skip behavior, but process in queue order.
   - Preserve create-only semantics (`issues-create` skips mapped issues) for each queued issue.
   - Return output payload with queue-aware selection metadata (selected issue IDs and per-issue action results).
   - Expected result: one command run can materialize multiple selected issues with stable ordering and output.
4. Add regression coverage and protocol/workflow wording updates.
   - Add smoke tests for multi-issue queue success, duplicate-ID rejection, and mixed mapped/unmapped behavior in create-only mode.
   - Update protocol/workflow command examples to document queue usage for `materialize feature ... --mode issues-create|issues-sync`.
   - Expected result: queue behavior is verifiable and documented as canonical command usage.

#### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 3`.
   - Task 1: CLI + parser contract for repeatable issue queue input and queue validation helpers.
   - Task 2: materialize execution path update for queue-based issue filtering/order and deterministic output contract.
   - Task 3: smoke/docs updates for queue behavior and failure paths.
2. Why `3`:
   - parser/input contract, materialize runtime behavior, and regression/docs are separate change domains and can be validated independently.

### I25-F4-M1 - Automate `plan issue` command with canonical issue-plan block upsert and scoped lint

#### Dependencies
- `dev/workflow_lib/feature_commands.py`
- `dev/workflow_lib/cli.py`
- `tests/check-workflow-cli-smoke.sh`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_PLANNING_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`

#### Decomposition
1. Add a dedicated CLI subcommand for issue planning.
   - Register `feature plan-issue` in `register_feature_router(...)` next to `plan-lint`/`materialize`.
   - Input contract:
     - required: `--id <I*-F*-M*>`,
     - optional: `--write`, `--strict`,
     - optional: `--feature-id <F*-M*>` only as an ownership assertion (must match resolved owner).
   - Output contract (JSON): `command`, `issue_id`, `feature_id`, `action`, `write`, `strict`, `plan_block_updated`, `issue_order_checked`, `issue_order_mutated`.
2. Implement issue resolution and ownership validation in one deterministic function.
   - Parse ID via existing `_parse_issue_id(...)`.
   - Resolve issue node from `DEV_MAP` and owner feature from `Milestone -> Feature -> Issue`.
   - Reject cases with explicit error text:
     - malformed issue id,
     - issue not found in `DEV_MAP`,
     - multiple matches (if map integrity is broken),
     - `--feature-id` mismatch with resolved owner.
3. Implement canonical issue-plan block upsert in `FEATURE_PLANS.md`.
   - Read owner feature section via existing `_extract_feature_plan_section(...)`.
   - Find existing block `### <issue_id> - <issue_title>`:
     - if present: replace only this block content,
     - if absent: insert one new block after existing issue blocks in the same feature section.
   - Enforce canonical inner structure exactly:
     - `#### Dependencies`,
     - `#### Decomposition`,
     - `#### Issue/Task Decomposition Assessment`.
   - Keep update scope strict: do not mutate other issue blocks.
4. Add scoped lint for target issue instead of full section lint, with read-only `Issue Execution Order` checks.
   - Validate only:
     - heading format `### <issue_id> - <issue_title>`,
     - allowed `####` subheadings and non-empty content,
     - ownership of issue id to target feature,
     - row presence/format in `Issue Execution Order` for this issue when issue is active.
   - `plan-issue` must not mutate `Issue Execution Order`:
     - do not add/remove/reorder rows,
     - if active issue row is missing, fail with deterministic error and keep file unchanged.
   - Reuse existing validators (`_lint_issue_plan_blocks`, `_lint_one_issue_plan_block`, `_resolve_issue_execution_order_state`) through a narrow wrapper, without changing behavior of full `feature plan-lint`.
5. Add smoke coverage for command behavior and edge cases.
   - Success path:
     - create block when missing (`--write`),
     - update block when exists (`--write`),
     - dry-run reports planned mutation without file write.
   - Failure path:
     - unknown issue id,
     - malformed id,
     - feature mismatch via `--feature-id`,
     - missing active issue row in order block,
     - invalid custom heading inside target block.
   - Stability path:
     - repeated `--write` is idempotent (no additional mutations after first success).
6. Update protocol/docs to include command and boundaries.
   - `dev/TASK_EXECUTION_PROTOCOL.md`: add `plan issue` automation note and scoped-lint behavior.
   - `dev/FEATURE_WORKFLOW.md`: add canonical usage example.
   - `dev/FEATURE_PLANNING_PROTOCOL.md`: clarify that output is persisted via command, block is canonical single-source artifact, and `Issue Execution Order` is read-only for `plan-issue`.

#### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 5`.
   - Task 1: CLI surface and output contract.
     - Files: `dev/workflow_lib/feature_commands.py`, `dev/workflow_lib/cli.py`.
     - Acceptance: `python3 dev/workflow feature --help` shows `plan-issue`.
   - Task 2: issue resolver and ownership/error contract.
     - File: `dev/workflow_lib/feature_commands.py`.
     - Acceptance: deterministic errors for malformed/unknown/mismatch cases.
   - Task 3: issue-plan block upsert engine.
     - File: `dev/workflow_lib/feature_commands.py`.
     - Acceptance: one canonical block created/updated without touching other issue blocks.
   - Task 4: scoped lint wrapper + read-only `Issue Execution Order` guard.
     - File: `dev/workflow_lib/feature_commands.py`.
     - Acceptance: target-block lint passes/fails deterministically; missing active issue row fails without modifying order block.
   - Task 5: regression tests and docs sync.
     - Files: `tests/check-workflow-cli-smoke.sh`, `dev/TASK_EXECUTION_PROTOCOL.md`, `dev/FEATURE_WORKFLOW.md`, `dev/FEATURE_PLANNING_PROTOCOL.md`.
     - Acceptance: smoke scenarios for success/failure/idempotency pass.
2. Why `5`:
   - CLI surface, resolver contract, markdown mutation, order/lint semantics, and regression/docs have separate failure modes and should be validated independently.

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
   - Add CLI/state handling for reject transition in confirm flow for feature issues.
   - Keep deterministic issue-ID validation and ownership checks.
2. Implement local tracker transition to `Rejected`.
   - Persist explicit issue status update to `Rejected` in `DEV_MAP`.
   - Keep terminal-status behavior stable for planning/materialization/execution filters.
3. Implement mapped GitHub issue reject handling.
   - Add explicit rejection marker update for mapped issue body (or equivalent deterministic reject note).
   - Close mapped GitHub issue in the same write run after rejection marker is applied.
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
1. Add issue-level human-readable description field to local model.
   - Extend issue node contract in `DEV_MAP` and schema docs with `description` (non-empty text explaining problem/context of issue).
   - Extend sync write path so issue `description` is accepted from delta payload and persisted in issue nodes.
2. Rewrite feature child GitHub issue body to description-driven readable text.
   - Rework `_build_materialized_issue_body` to generate readable text sections (for example: problem/context, expected outcome, implementation notes).
   - Remove markdown checkbox rendering from child issue body output.
3. Rewrite feature-level GitHub issue body without checkboxes.
   - Rework `_build_feature_registration_issue_body` to a readable list/summary format without checkbox syntax.
   - Keep child issue references as readable bullets/links (no checkbox state transport in body).
4. Remove checkbox coupling from confirm-path.
   - Keep `confirm issue ... done` focused on status transition + GitHub close.
   - Remove dependency on feature-issue body parsing/sync (`row_found`-style behavior should no longer affect completion semantics).
5. Update tests and docs.
   - Add/adjust smoke assertions for description-based issue body (checkbox-free).
   - Update protocol/workflow docs to describe `description`-driven issue body contract.

#### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 4`.
   - Task 1: model/schema/sync support for issue `description`.
   - Task 2: child issue body rewrite (checkbox-free, readable explanation).
   - Task 3: feature issue body rewrite (checkbox-free summary).
   - Task 4: smoke/docs/protocol alignment + confirm-path checkbox decoupling.
2. Why `4`:
   - model contract, renderer changes, and confirmation decoupling are the minimal set for checkbox-free readable issue bodies.

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
