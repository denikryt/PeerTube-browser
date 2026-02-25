# Task Execution Protocol

This file defines only the execution procedure (how to execute tasks).
Hard constraints (what is allowed/forbidden) are defined in `AGENTS.md`.

## Scope ownership (canonical)

- This file owns command semantics and command order for execution-related flows.
- `AGENTS.md` owns hard policy constraints and permission gates.
- `dev/FEATURE_PLANNING_PROTOCOL.md` owns planning-only quality requirements.
- `dev/FEATURE_WORKFLOW.md` is an index that points to canonical sections and must not duplicate normative contracts.

If any command-order/step-contract wording differs across docs, this file is canonical.

## Standard execution flow (single task)

Use this procedure after an explicit execution command is given.

1. **Read in strict order before coding**
   - Read exact task text for task `X` in `dev/TASK_LIST.json`.
   - Read `dev/TASK_EXECUTION_PIPELINE.json`.
   - Read `dev/map/DEV_MAP.json` context for task `X` and related ownership markers (`M/F` or `M/SI` path).
   - Read this file (`dev/TASK_EXECUTION_PROTOCOL.md`).

2. **Check overlaps/dependencies**
   - For task `X`, inspect overlaps and ordering constraints in `dev/TASK_EXECUTION_PIPELINE.json`.
   - Identify shared primitives to avoid one-off local implementations.
   - Verify markers in `dev/TASK_LIST.json` are consistent with planned ownership:
     - product path: `[M*][F*]`
     - standalone path: `[M*][SI*]`
     If task exists in `dev/map/DEV_MAP.json`, markers must match parent chain.
   - Enforce execution materialization gate from local tracker state:
     - resolve parent `Issue`/`StandaloneIssue` for task `X` in `dev/map/DEV_MAP.json`,
     - require non-null `gh_issue_number` and `gh_issue_url` on that parent node,
     - if any of those fields is missing, stop execution and request `materialize feature <id> --mode issues-create` or `materialize standalone-issue`.

3. **Prepare a short implementation plan**
   - List concrete files/modules to update.
   - Note validations to run after implementation.

4. **Implement**
   - Apply code/doc/config/test changes required by task `X`.
   - Keep one source of truth per concern; avoid duplicate logic.

5. **Validate**
   - Run relevant checks/tests/smokes for changed paths.
   - Verify no regressions in overlapping areas touched by task `X`.

6. **Requirement closure check (mandatory final stage)**
   - Re-read the exact task text for task `X` in `dev/TASK_LIST.json`.
   - Verify each stated requirement is implemented.
   - If any requirement is not implemented, list it explicitly before reporting result.
   - Verify tracking sync was preserved (`dev/map/DEV_MAP.json`, `dev/TASK_LIST.json`, `dev/TASK_EXECUTION_PIPELINE.json`).

7. **Report implementation result**
   - Summarize what was changed, what was validated, and any remaining risks.
   - Do not mark task completed until explicit user confirmation.

## Feature chain execution flow (`execute feature <feature_id>`)

Use this procedure when user requests execution of all tasks under one feature.

1. Resolve `<feature_id>` in `dev/map/DEV_MAP.json` and collect all child tasks under `Milestone -> Feature -> Issue -> Task`.
2. Keep only pending tasks (`status != Done`).
3. Enforce materialization gate for feature child issues:
   - for each issue that contains pending tasks, require non-null `gh_issue_number` and `gh_issue_url`,
   - if any issue fails this check, stop execution and request `materialize feature <feature_id> --mode issues-create`.
4. Build execution order:
   - first: task IDs that are present in `dev/TASK_EXECUTION_PIPELINE.json` execution order,
   - then: remaining pending tasks in `DEV_MAP` issue/task order.
5. Execute each task sequentially using the full **Standard execution flow (single task)**.
6. After each task, run overlap/dependency validations relevant to the next tasks in the same feature chain.
7. Stop on the first blocking failure and report the exact failed task + blocker; continue only if user explicitly asks to continue.
8. Do not auto-mark task/issue/feature as `Done`; completion updates require explicit `confirm ... done` commands.

## Issue chain execution flow (`execute issue <issue_id>`)

Use this procedure when user requests execution of all tasks under one feature issue.

1. Resolve `<issue_id>` in `dev/map/DEV_MAP.json` under `Milestone -> Feature -> Issue`.
2. Keep only pending tasks (`status != Done`) from this issue subtree.
3. If no pending tasks remain, stop and report that this issue has nothing to execute.
4. Enforce materialization gate for the target issue:
   - require non-null `gh_issue_number` and `gh_issue_url` on this issue node,
   - if either field is missing, stop execution and request `materialize feature <feature_id> --mode issues-create`.
5. Build execution order:
   - first: task IDs that are present in `dev/TASK_EXECUTION_PIPELINE.json` execution order,
   - then: remaining pending tasks in issue task order from `DEV_MAP`.
6. Execute each task sequentially using the full **Standard execution flow (single task)**.
7. After each task, run overlap/dependency validations relevant to the next tasks in the same issue chain.
8. Stop on the first blocking failure and report the exact failed task + blocker; continue only if user explicitly asks to continue.
9. Do not auto-mark task/issue/feature as `Done`; completion updates require explicit `confirm ... done` commands.

## Completion flow (after explicit user confirmation)

Use explicit completion commands:
- `confirm task <task_id> done`
- `confirm issue <issue_id> done`
- `confirm feature <feature_id> done`
- `confirm standalone-issue <si_id> done`

Apply the corresponding completion update in one edit run:

1. `confirm task <task_id> done`
   - Update task state in `dev/TASK_LIST.json` (remove/move confirmed task from future tasks).
   - Update task status in `dev/map/DEV_MAP.json` under its existing parent chain.
   - Remove confirmed completed task/block from `dev/TASK_EXECUTION_PIPELINE.json` (keep only pending items).
2. `confirm issue <issue_id> done`
   - Resolve all mapped child tasks under the selected issue.
   - If any child task is not `Done`, request explicit additional confirmation to cascade these tasks to `Done`.
   - If additional confirmation is not given, stop without applying completion updates.
   - If additional confirmation is given:
     - update child task statuses to `Done` in `dev/map/DEV_MAP.json`.
   - Update local issue status to `Done` in `dev/map/DEV_MAP.json`.
   - Close mapped GitHub issue in the same completion update run.
3. `confirm feature <feature_id> done`
   - Treat this command as explicit confirmation for the full feature subtree.
   - Resolve all child issues/tasks under `Milestone -> Feature -> Issue -> Task`.
   - For every pending child task:
     - update task status to `Done` in `dev/map/DEV_MAP.json`,
     - update task state in `dev/TASK_LIST.json` (remove/move from future list),
     - remove completed entries from `dev/TASK_EXECUTION_PIPELINE.json` (pipeline keeps only pending items).
   - For every child issue:
     - update local issue status to `Done` in `dev/map/DEV_MAP.json`,
     - close mapped child GitHub issue in the same completion update run.
   - Update local feature status to `Done` in `dev/map/DEV_MAP.json`.
   - Close mapped feature GitHub issue in the same completion update run.
4. `confirm standalone-issue <si_id> done`
   - Verify all mapped child tasks are already confirmed done.
   - Update local standalone issue status to `Done` in `dev/map/DEV_MAP.json`.
   - Close mapped GitHub standalone issue in the same completion update run.
5. If process rules changed, update this file in the same edit run.

## Feature planning/materialization flow

Use this procedure before executing tasks for a new feature.

1. `create feature <id>`: register the feature in local and GitHub trackers.
   - Create feature node in `dev/map/DEV_MAP.json` using ID format from `dev/map/DEV_MAP_SCHEMA.md`.
   - Create/update feature-level GitHub issue for this feature and assign it to the corresponding GitHub milestone.
   - Persist feature `gh_issue_number`/`gh_issue_url` in `dev/map/DEV_MAP.json` in the same change set.
   - If milestone cannot be resolved on GitHub, stop and ask user to create/select milestone first.
   - Registration-only boundary: do not auto-run `plan`, `approve`, `sync`, `materialize`, or `execute` after `create feature`.
2. `plan feature <id>`: produce/update `dependencies`, `decomposition` (strict step-by-step command flow), `Issue Execution Order` (ordered active feature issues), and `Issue/Task Decomposition Assessment` in `dev/FEATURE_PLANS.md`.
3. `plan issue <issue_id>`: produce/update one issue-level plan block in `dev/FEATURE_PLANS.md` under the owning feature section.
   - Resolve `<issue_id>` in `dev/map/DEV_MAP.json` and bind to exactly one parent feature.
   - If issue is missing in `DEV_MAP`, stop and request issue creation/sync first.
   - Update only issue-plan content for the target issue (do not auto-create feature/issue mapping nodes from this command).
   - Keep `Issue Execution Order` consistent: include the target issue if it is active (`status != Done` and `status != Rejected`).
   - Persist plan content to `dev/FEATURE_PLANS.md` in the same run (no chat-only plan output).
4. `approve feature plan`: freeze boundaries from the corresponding section in `dev/FEATURE_PLANS.md`, then set the target feature status to `Approved` in `dev/map/DEV_MAP.json`.
   - Feature status in `dev/map/DEV_MAP.json` is the source of truth for approval gates.
   - If that approved section is edited later, require a new explicit `approve feature plan` and re-set status to `Approved` before continuing.
5. `sync issues to task list for <id>`: run only if the target feature status in `dev/map/DEV_MAP.json` is `Approved`; then create/update local `Issue -> Task` decomposition and sync it in one change set across `dev/map/DEV_MAP.json`, `dev/TASK_LIST.json`, and `dev/TASK_EXECUTION_PIPELINE.json`.
6. Review/refine local issues/tasks with the user until decomposition is final.
7. `materialize feature <id> --mode <bootstrap|issues-create|issues-sync>`: run explicit materialization mode for an already-synced feature.
   - `--mode bootstrap`: resolve/create canonical feature branch context and persist branch linkage metadata; do not materialize child issues.
   - `--mode issues-create`: materialize feature child `Issue` nodes to GitHub in create-oriented flow from local issue structure.
   - `--mode issues-sync`: materialize feature child `Issue` nodes to GitHub in sync/update flow from local issue structure.
   - `--issue-id <issue_id>` is allowed only with `issues-create`/`issues-sync` and targets one issue node.
   - Feature-level GitHub issue is managed at `create feature <id>` step; during materialization, update it only if metadata/body sync is explicitly required, without creating duplicates.
   - Branch policy (mandatory): resolve canonical feature branch `feature/<feature_id>` and persist branch linkage metadata; do not auto-checkout/switch branches during `materialize`.
   - Never create duplicate branches for the same feature id (for example `feature/F1-M1-2`).
   - Default: one branch per feature; create issue-level branches only by explicit user request.
   - Persist branch linkage on target feature node in `dev/map/DEV_MAP.json`:
     - `branch_name = feature/<feature_id>`,
     - `branch_url = <repo_url>/tree/feature/<feature_id>` (or `null` if repository URL cannot be resolved).
   - Include branch context in result message: `Canonical feature branch: feature/<feature_id>`.
   - If milestone cannot be resolved on GitHub, stop and ask user to create/select milestone first.
   - Keep GitHub issue body strictly issue-focused; do not include local process/protocol instructions.
   - Do not include boilerplate sections/phrases like `Work issue for ...`, `Source of truth`, or `Notes` in materialized GitHub issues.
8. Only then run `execute task X` or `execute issue <issue_id>` or `execute feature <feature_id>`.
   - Execution gate: every parent `Issue` for the target task set must have non-null `gh_issue_number` and `gh_issue_url` in `dev/map/DEV_MAP.json`.

## Standalone issue flow (non-product work)

Use this when work should not be attached to a product feature (ops/process/tooling/governance).

1. `create standalone-issue <id>`: create standalone issue node in `dev/map/DEV_MAP.json` using `SI<local>-M<milestone>` ID format.
2. `plan standalone-issue <id>`: define scope, acceptance checks, and expected tasks.
3. `approve standalone-issue plan`: freeze boundaries and allow local decomposition sync.
4. `sync standalone-issue to task list`: create/update local `StandaloneIssue -> Task` decomposition and sync it in one change set across `dev/map/DEV_MAP.json`, `dev/TASK_LIST.json`, and `dev/TASK_EXECUTION_PIPELINE.json`.
5. Review/refine local tasks with the user until decomposition is final.
6. `materialize standalone-issue`: create/update GitHub issue from the already-synced local standalone issue structure, assign it to the corresponding GitHub milestone, and persist `gh_issue_number`/`gh_issue_url` in `dev/map/DEV_MAP.json`.
   - If milestone cannot be resolved on GitHub, stop and ask user to create/select milestone first.
   - Keep GitHub issue body strictly issue-focused; do not include local process/protocol instructions.
   - Do not include boilerplate sections/phrases like `Work issue for ...`, `Source of truth`, or `Notes` in materialized GitHub issues.
7. Only then run `execute task X`.
   - Execution gate: parent `StandaloneIssue` must have non-null `gh_issue_number` and `gh_issue_url` in `dev/map/DEV_MAP.json`.

## Multi-task execution flow

Use this when multiple tasks are requested in one execution run.

1. Build execution order from `dev/TASK_EXECUTION_PIPELINE.json`.
2. Identify overlaps and shared primitives before coding.
3. Implement shared primitives first.
4. Execute tasks in dependency order.
5. Run one integration pass for the whole bundle.
6. Run a requirement closure check for each executed task against its exact task text.
7. Apply completion flow only for tasks explicitly confirmed by the user.

## New/edited task update flow

When creating or rewriting a task definition:

1. Inspect real implementation context first (relevant code paths/modules/scripts/tests).
2. Analyze existing bindings in `dev/map/DEV_MAP.json` and prepare candidate targets for this task:
   - one or more matching feature chains (`Milestone -> Feature -> Issue`), or
   - standalone chain (`Milestone -> StandaloneIssue`) if no suitable feature exists.
3. Ask user to choose binding target; do not write mapping before explicit user choice.
4. Allocate task ID from `dev/map/DEV_MAP.json`:
   - read `task_count`,
   - assign `new_id = task_count + 1` as the new numeric task ID,
   - set `task_count = new_id` in the same change set.
   Never allocate by scanning or by "last visible task" in `dev/TASK_LIST.json`.
5. Update `dev/TASK_LIST.json` as one linear list (append new tasks to the end).
6. For each new/rewritten task entry in `dev/TASK_LIST.json`, add a mandatory `concrete_steps` field with explicit numbered actions (what to edit/run/validate), not only conceptual statements.
7. Attach/update the task in `dev/map/DEV_MAP.json` under the user-selected target chain (or create missing parent nodes first):
   - `Milestone -> Feature -> Issue -> Task`, or
   - `Milestone -> StandaloneIssue -> Task`.
8. Add/maintain markers for the task in `dev/TASK_LIST.json` according to selected binding:
   - `[M*][F*]` for feature path,
   - `[M*][SI*]` for standalone path.
9. Update `dev/TASK_EXECUTION_PIPELINE.json` order/overlaps for pending tasks.
10. Keep this protocol and `AGENTS.md` consistent if process/policy changed.

## Bundle command format

Use this command style when requesting multiple tasks:

`Execute bundle: <taskA> -> <taskB> -> <taskC>, mode=strict, no-duplicate-logic`

Feature-chain execution command:

`execute feature <feature_id>`

Issue-chain execution command:

`execute issue <issue_id>`
