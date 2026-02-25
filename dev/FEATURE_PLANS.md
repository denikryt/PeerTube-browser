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
1. `I23-F4-M1` - Issue lifecycle status contract: Pending -> Planned -> Tasked with planning/materialize gates
2. `I22-F4-M1` - Feature materialize: support multi-issue queue in one command run
3. `I14-F4-M1` - Replace checkbox-based GitHub issue body with description-driven readable content
4. `I15-F4-M1` - Feature materialize: reconcile GitHub sub-issues from DEV_MAP issue set
5. `I17-F4-M1` - Reject issue flow: add Rejected status and close mapped GitHub issue with explicit rejection marker
6. `I7-F4-M1` - Issue creation command for feature/standalone with optional plan init
7. `I9-F4-M1` - Add workflow CLI show/status commands for feature/issue/task
8. `I13-F4-M1` - Auto-delete sync delta file after successful decomposition write
### Dependencies
- See issue-level dependency blocks below.

### Decomposition
1. Execute follow-up issues in `Issue Execution Order`.
2. Keep per-issue implementation details inside canonical issue-plan blocks.

### Issue/Task Decomposition Assessment
- Decomposition is maintained per issue block; no extra feature-level split is required.

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
