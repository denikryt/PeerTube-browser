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
1. `I16-F4-M1` - Issue planning status split: Pending (no plan) vs Planned (has plan)
2. `I20-F4-M1` - Rename decomposition commands from sync to plan tasks for issue/feature
3. `I21-F4-M1` - Confirm issue done: script-driven cleanup of issue plan block and linked issue/task tracker nodes
4. `I22-F4-M1` - Feature materialize: support multi-issue queue in one command run
5. `I18-F4-M1` - Standardize per-issue plan block format in FEATURE_PLANS and enforce strict heading lint
6. `I19-F4-M1` - Feature plan issue execution order block as the source of issue sequencing
7. `I14-F4-M1` - Replace checkbox-based GitHub issue body with description-driven readable content
8. `I15-F4-M1` - Feature materialize: reconcile GitHub sub-issues from DEV_MAP issue set
9. `I17-F4-M1` - Reject issue flow: add Rejected status and close mapped GitHub issue with explicit rejection marker
10. `I7-F4-M1` - Issue creation command for feature/standalone with optional plan init
11. `I9-F4-M1` - Add workflow CLI show/status commands for feature/issue/task
12. `I13-F4-M1` - Auto-delete sync delta file after successful feature sync write

### Follow-up issue: I16-F4-M1

**Title**
- `I16-F4-M1`: Issue planning status split: Pending (no plan) vs Planned (has plan)

### Dependencies
- `dev/map/DEV_MAP.json`
- `dev/map/DEV_MAP_SCHEMA.md`
- `dev/FEATURE_PLANS.md`
- `dev/workflow_lib/feature_commands.py` (`feature plan-lint`, `feature sync`, issue-order parsing helpers)
- `tests/check-workflow-cli-smoke.sh`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_PLANNING_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`

### Decomposition
1. Introduce issue planning status contract for feature issues.
   - Add/lock explicit semantics: `Pending` means issue exists in `DEV_MAP` but has no issue-plan block in `FEATURE_PLANS`; `Planned` means issue-plan block exists.
   - Keep `Done` and `Rejected` as terminal statuses and out of pending planning set.
2. Align issue creation/sync default status with planning state.
   - For newly created issue nodes in sync paths, default status to `Pending` unless explicit status is provided.
   - Preserve existing status when issue already exists and no status override is passed.
3. Add deterministic issue-plan coverage detection.
   - Parse issue-plan blocks inside feature sections and determine whether each active issue has plan content.
   - Reconcile status for active issues: with plan block -> `Planned`, without plan block -> `Pending`.
4. Enforce split in lint/output contracts.
   - Extend `feature plan-lint` to report status/plan presence mismatches with deterministic error messages.
   - Keep lint non-mutating; status correction should happen only in write paths.
5. Cover with smoke tests and doc updates.
   - Add smoke scenarios for `Pending` default, `Pending -> Planned` transition after plan block creation, and mismatch lint failures.
   - Update protocol/workflow text so `plan issue <issue_id>` clearly implies persisted issue-plan block and status semantics.

### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 3`.
   - Task 1: status contract + schema/status enum alignment + `Pending` default for new issues.
   - Task 2: issue-plan block detection and status reconciliation/lint consistency.
   - Task 3: smoke coverage and protocol/workflow documentation updates.
2. Why `3`:
   - model contract, reconciliation logic, and regression/documentation are separate risk domains and can be validated independently.

### Follow-up issue: I20-F4-M1

**Title**
- `I20-F4-M1`: Rename decomposition commands from sync to plan tasks for issue/feature

### Dependencies
- `dev/workflow_lib/feature_commands.py`
- `dev/workflow_lib/cli.py`
- `tests/check-workflow-cli-smoke.sh`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`
- `dev/FEATURE_PLANNING_PROTOCOL.md`
- `AGENTS.md`

### Decomposition
1. Define canonical decomposition command naming.
   - Set canonical commands: `plan tasks for issue <issue_id>` and `plan tasks for feature <feature_id>`.
   - Reserve `sync` naming only for state reconciliation operations that do not create new tasks/decomposition.
2. Implement direct CLI command rename without aliases.
   - Add command handlers so canonical `plan tasks for ...` names are first-class CLI commands.
   - Remove `sync issues to task list for <feature_id>` decomposition command path; do not keep aliases.
3. Update protocol/workflow command semantics.
   - Replace decomposition-step naming in canonical command sequence docs from `sync issues ...` to `plan tasks for ...`.
   - Keep one source of truth for semantics in `TASK_EXECUTION_PROTOCOL`; in index/docs leave concise references only.
4. Align output contract and operator guidance.
   - Ensure command output and help text describe decomposition/planning action, not synchronization.
   - Add deterministic wording for hard-rename errors and next-command guidance.
5. Add regression smoke coverage.
   - Add positive smoke for new canonical command names.
   - Add negative smoke that legacy `sync issues to task list ...` command is rejected with explicit error.

### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 3`.
   - Task 1: canonical command naming contract + docs/protocol updates.
   - Task 2: CLI implementation for `plan tasks for issue|feature` without alias paths.
   - Task 3: smoke tests and output contract verification for hard command rename.
2. Why `3`:
   - naming contract, command implementation, and regression coverage are separate risk domains and should be validated independently.

### Follow-up issue: I21-F4-M1

**Title**
- `I21-F4-M1`: Confirm issue done: script-driven cleanup of issue plan block and linked issue/task tracker nodes

### Dependencies
- `dev/workflow_lib/confirm_commands.py`
- `dev/workflow_lib/feature_commands.py` (helpers for `FEATURE_PLANS` section parsing and order rows)
- `dev/FEATURE_PLANS.md`
- `dev/map/DEV_MAP.json`
- `dev/TASK_LIST.json`
- `dev/TASK_EXECUTION_PIPELINE.json`
- `tests/check-workflow-cli-smoke.sh`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`

### Decomposition
1. Define cleanup contract for `confirm issue <issue_id> done`.
   - When confirm issue completion is applied with write mode, perform script-driven cleanup for all artifacts linked to the target issue.
   - Cleanup scope must include both tracker cleanup and plan-document cleanup in one run.
2. Implement `FEATURE_PLANS` cleanup in confirm flow.
   - Remove target issue row from feature `Issue Execution Order`.
   - Remove target issue plan block from `FEATURE_PLANS` under the owning feature section.
   - If issue block is absent, keep command idempotent and return deterministic `not-found/skipped` cleanup fields.
3. Implement issue-node removal in tracker cleanup path.
   - Remove confirmed issue node from `dev/map/DEV_MAP.json` together with embedded child task nodes.
   - Keep existing cleanup behavior for `TASK_LIST.json` and `TASK_EXECUTION_PIPELINE.json` for child task IDs.
4. Ensure operation ordering and safety.
   - Apply all local file updates in one write path after confirmation gates pass.
   - If write is disabled, return full cleanup preview describing what would be removed in plans/map/task-list/pipeline.
5. Add regression tests and protocol docs.
   - Smoke: confirm issue removes issue plan block, removes order row, removes DEV_MAP issue node, and cleans task-list/pipeline entries.
   - Smoke idempotency: repeated confirm on already-cleaned issue returns deterministic no-op cleanup details.
   - Update execution protocol/workflow docs with explicit cleanup semantics for confirm-issue flow.

### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 3`.
   - Task 1: cleanup contract + protocol/docs updates.
   - Task 2: confirm command implementation for `FEATURE_PLANS` and `DEV_MAP` issue-node removal.
   - Task 3: smoke regression and idempotency validation.
2. Why `3`:
   - behavior contract, write-path implementation, and regression/idempotency coverage are separate risk domains and should be validated independently.

### Follow-up issue: I14-F4-M1

**Title**
- `I14-F4-M1`: Replace checkbox-based GitHub issue body with description-driven readable content

### Dependencies
- `dev/map/DEV_MAP.json`
- `dev/map/DEV_MAP_SCHEMA.md`
- `dev/workflow_lib/feature_commands.py`
- `dev/workflow_lib/feature_commands.py` (`_apply_issue_delta`, `_build_materialized_issue_body`, `_build_feature_registration_issue_body`, `feature materialize`)
- `dev/workflow_lib/confirm_commands.py`
- `dev/workflow_lib/issue_checklist.py` (cleanup/removal or deprecation path)
- `tests/check-workflow-cli-smoke.sh`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`

### Decomposition
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

### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 4`.
   - Task 1: model/schema/sync support for issue `description`.
   - Task 2: child issue body rewrite (checkbox-free, readable explanation).
   - Task 3: feature issue body rewrite (checkbox-free summary).
   - Task 4: smoke/docs/protocol alignment + confirm-path checkbox decoupling.
2. Why `4`:
   - model contract, renderer changes, and confirmation decoupling are the minimal set for checkbox-free readable issue bodies.

### Follow-up issue: I15-F4-M1

**Title**
- `I15-F4-M1`: Feature materialize sub-issues reconcile for parent feature issue

### Dependencies
- `dev/map/DEV_MAP.json`
- `dev/workflow_lib/feature_commands.py`
- `dev/workflow_lib/github_adapter.py`
- `tests/check-workflow-cli-smoke.sh`
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`

### Decomposition
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

### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 3`.
   - Task 1: GitHub adapter support for sub-issues API + error contract.
   - Task 2: `feature materialize` reconcile logic and output contract.
   - Task 3: smoke/docs alignment and idempotency verification.
2. Why `3`:
   - integration layer, materialize reconcile logic, and regression coverage are separate risk domains and should be validated independently.

### Follow-up issue: I18-F4-M1

**Title**
- `I18-F4-M1`: Standardize per-issue plan blocks in `FEATURE_PLANS` (`### issue` + `####` sections) and enforce strict lint

### Dependencies
- `dev/FEATURE_PLANS.md`
- `dev/FEATURE_PLANNING_PROTOCOL.md`
- `dev/workflow_lib/feature_commands.py` (`feature plan-lint`)
- `tests/check-workflow-cli-smoke.sh`

### Decomposition
1. Define canonical issue-plan block shape in docs.
   - Set one issue = one `###` block with heading format: `### I<local>-F<feature>-M<milestone> — <title>`.
   - Reserve `####` headings for sections inside the issue block (for example `#### Context`, `#### Steps`, `#### Notes`).
2. Enforce strict lint contract for issue-plan headings.
   - In `feature plan-lint`, validate unique issue IDs per feature section.
   - Reject non-issue `###` headings inside a feature section.
   - Validate that each issue block uses only `####` for inner section headings and contains mandatory content sections.
3. Normalize all existing issue-plan entries in the document to the canonical shape.
   - Rewrite already written issue-plan headings across `FEATURE_PLANS.md` to the new `### I...` block style.
   - Keep content equivalent while removing mixed ad-hoc heading variants.
4. Add smoke checks for parser/lint stability.
   - Add positive case for canonical format and negative cases for malformed/duplicate headings.
   - Ensure deterministic lint errors include offending heading/issue ID.

### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 3`.
   - Task 1: docs + canonical format contract.
   - Task 2: strict lint implementation for `###`/`####` hierarchy and uniqueness.
   - Task 3: migration of existing entries + smoke regression checks.
2. Why `3`:
   - contract definition, validator enforcement, and migration/regression coverage are separate risk domains and should be implemented independently.

### Follow-up issue: I19-F4-M1

**Title**
- `I19-F4-M1`: Feature plan issue execution order block as the source of issue sequencing

### Dependencies
- `dev/FEATURE_PLANS.md`
- `dev/map/DEV_MAP.json`
- `dev/workflow_lib/feature_commands.py` (`feature execution-plan`, `feature plan-lint`)
- `dev/TASK_EXECUTION_PROTOCOL.md`
- `dev/FEATURE_WORKFLOW.md`

### Decomposition
1. Define one canonical issue ordering block inside each feature plan section.
   - Add `### Issue Execution Order` under `## F*-M*` plan sections.
   - Store order as a numbered list by position (no extra numeric `order` field).
2. Set inclusion rule for items in the order block.
   - Include all active issues from `DEV_MAP` for that feature (`status != Done` and `status != Rejected`), even when detailed per-issue plan text is missing.
   - Use one uniform row shape with issue ID and title: ``<issue_id>`` - `<issue_title>`.
3. Add validation for order block consistency.
   - Extend `feature plan-lint` with checks: unique issue IDs in the order block, valid ID format, and no unknown issues outside feature scope.
   - Validate against `DEV_MAP`: no missing active issues and no stale IDs in order list.
4. Integrate order block into execution guidance.
   - Update `feature execution-plan` output to include the next eligible issue from the order block.
   - Keep task-level pipeline logic unchanged; issue ordering is read from `FEATURE_PLANS`.
5. Cover with smoke/docs updates.
   - Add smoke cases for valid order block and mismatch errors.
   - Update protocol/workflow docs with the new source-of-truth rule for issue sequence.

### Issue/Task Decomposition Assessment
1. Recommended split: `task_count = 3`.
   - Task 1: format contract + lint checks for issue order block.
   - Task 2: `execution-plan` integration to surface next issue from plan order.
   - Task 3: smoke/docs alignment and regression coverage.
2. Why `3`:
   - data contract, execution integration, and validation coverage are independent risk areas and should be delivered separately.
