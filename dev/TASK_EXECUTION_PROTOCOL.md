# Task Execution Protocol

This file defines only the execution procedure (how to execute tasks).
Hard constraints (what is allowed/forbidden) are defined in `AGENTS.md`.

## Standard execution flow (single task)

Use this procedure after an explicit execution command is given.

1. **Read in strict order before coding**
   - Read exact task text for task `X` in `dev/TASK_LIST.md`.
   - Read `dev/TASK_EXECUTION_PIPELINE.md`.
   - Read `dev/map/DEV_MAP.json` context for task `X` and related ownership markers (`M/F` or `M/SI` path).
   - Read this file (`dev/TASK_EXECUTION_PROTOCOL.md`).

2. **Check overlaps/dependencies**
   - For task `X`, inspect overlaps and ordering constraints in `dev/TASK_EXECUTION_PIPELINE.md`.
   - Identify shared primitives to avoid one-off local implementations.
   - Verify markers in `dev/TASK_LIST.md` are consistent with planned ownership:
     - product path: `[M*][F*]`
     - standalone path: `[M*][SI*]`
     If task exists in `dev/map/DEV_MAP.json`, markers must match parent chain.

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
   - Re-read the exact task text for task `X` in `dev/TASK_LIST.md`.
   - Verify each stated requirement is implemented.
   - If any requirement is not implemented, list it explicitly before reporting result.
   - Verify tracking sync was preserved (`dev/map/DEV_MAP.json`, `dev/TASK_LIST.md`, `dev/TASK_EXECUTION_PIPELINE.md`).

7. **Report implementation result**
   - Summarize what was changed, what was validated, and any remaining risks.
   - Do not mark task completed until explicit user confirmation.

## Feature chain execution flow (`execute feature <feature_id>`)

Use this procedure when user requests execution of all tasks under one feature.

1. Resolve `<feature_id>` in `dev/map/DEV_MAP.json` and collect all child tasks under `Milestone -> Feature -> Issue -> Task`.
2. Keep only pending tasks (`status != Done`).
3. Build execution order:
   - first: task IDs that are present in `dev/TASK_EXECUTION_PIPELINE.md` execution order,
   - then: remaining pending tasks in `DEV_MAP` issue/task order.
4. Execute each task sequentially using the full **Standard execution flow (single task)**.
5. After each task, run overlap/dependency validations relevant to the next tasks in the same feature chain.
6. Stop on the first blocking failure and report the exact failed task + blocker; continue only if user explicitly asks to continue.
7. Do not auto-mark task/issue/feature as `Done`; completion updates require explicit `confirm ... done` commands.

## Completion flow (after explicit user confirmation)

Use explicit completion commands:
- `confirm task <task_id> done`
- `confirm issue <issue_id> done`
- `confirm feature <feature_id> done`
- `confirm standalone-issue <si_id> done`

Apply the corresponding completion update in one edit run:

1. `confirm task <task_id> done`
   - Update task state in `dev/TASK_LIST.md` (remove/move confirmed task from future tasks).
   - Update task status in `dev/map/DEV_MAP.json` under its existing parent chain.
   - Remove confirmed completed task/block from `dev/TASK_EXECUTION_PIPELINE.md` (keep only pending items).
2. `confirm issue <issue_id> done`
   - Verify all mapped child tasks are already confirmed done.
   - Update local issue status to `Done` in `dev/map/DEV_MAP.json`.
   - Close mapped GitHub issue in the same completion update run.
3. `confirm feature <feature_id> done`
   - Treat this command as explicit confirmation for the full feature subtree.
   - Resolve all child issues/tasks under `Milestone -> Feature -> Issue -> Task`.
   - For every pending child task:
     - update task status to `Done` in `dev/map/DEV_MAP.json`,
     - update task state in `dev/TASK_LIST.md` (remove/move from future list),
     - remove completed entries from `dev/TASK_EXECUTION_PIPELINE.md` (pipeline keeps only pending items).
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

1. `create feature <id>`: create feature node in `dev/map/DEV_MAP.json` using ID format from `dev/map/DEV_MAP_SCHEMA.md`.
2. `plan feature <id>`: produce scope, out-of-scope, acceptance criteria, risks, dependencies, decomposition, and write/update the corresponding section in `dev/FEATURE_PLANS.md`.
3. `approve feature plan`: freeze boundaries from the corresponding section in `dev/FEATURE_PLANS.md`, then set the target feature status to `Approved` in `dev/map/DEV_MAP.json`.
   - Feature status in `dev/map/DEV_MAP.json` is the source of truth for approval gates.
   - If that approved section is edited later, require a new explicit `approve feature plan` and re-set status to `Approved` before continuing.
4. `sync issues to task list for <id>`: run only if the target feature status in `dev/map/DEV_MAP.json` is `Approved`; then create/update local `Issue -> Task` decomposition and sync it in one change set across `dev/map/DEV_MAP.json`, `dev/TASK_LIST.md`, and `dev/TASK_EXECUTION_PIPELINE.md`.
5. Review/refine local issues/tasks with the user until decomposition is final.
6. `materialize feature <id>`: create/update GitHub feature/work issues strictly from the already-synced local issue structure, assign each issue to the corresponding GitHub milestone, and persist `gh_issue_number`/`gh_issue_url` in `dev/map/DEV_MAP.json`.
   - If milestone cannot be resolved on GitHub, stop and ask user to create/select milestone first.
   - Keep GitHub issue body strictly issue-focused; do not include local process/protocol instructions.
   - Do not include boilerplate sections/phrases like `Work issue for ...`, `Source of truth`, or `Notes` in materialized GitHub issues.
7. Only then run `execute task X` or `execute feature <feature_id>`.

## Standalone issue flow (non-product work)

Use this when work should not be attached to a product feature (ops/process/tooling/governance).

1. `create standalone-issue <id>`: create standalone issue node in `dev/map/DEV_MAP.json` using `SI<local>-M<milestone>` ID format.
2. `plan standalone-issue <id>`: define scope, acceptance checks, and expected tasks.
3. `approve standalone-issue plan`: freeze boundaries and allow local decomposition sync.
4. `sync standalone-issue to task list`: create/update local `StandaloneIssue -> Task` decomposition and sync it in one change set across `dev/map/DEV_MAP.json`, `dev/TASK_LIST.md`, and `dev/TASK_EXECUTION_PIPELINE.md`.
5. Review/refine local tasks with the user until decomposition is final.
6. `materialize standalone-issue`: create/update GitHub issue from the already-synced local standalone issue structure, assign it to the corresponding GitHub milestone, and persist `gh_issue_number`/`gh_issue_url` in `dev/map/DEV_MAP.json`.
   - If milestone cannot be resolved on GitHub, stop and ask user to create/select milestone first.
   - Keep GitHub issue body strictly issue-focused; do not include local process/protocol instructions.
   - Do not include boilerplate sections/phrases like `Work issue for ...`, `Source of truth`, or `Notes` in materialized GitHub issues.
7. Only then run `execute task X`.

## Multi-task execution flow

Use this when multiple tasks are requested in one execution run.

1. Build execution order from `dev/TASK_EXECUTION_PIPELINE.md`.
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
   Never allocate by scanning or by "last visible task" in `dev/TASK_LIST.md`.
5. Update `dev/TASK_LIST.md` as one linear list (append new tasks to the end).
6. For each new/rewritten task entry in `dev/TASK_LIST.md`, add a mandatory `#### **Concrete steps:**` section with explicit numbered actions (what to edit/run/validate), not only conceptual statements.
7. Attach/update the task in `dev/map/DEV_MAP.json` under the user-selected target chain (or create missing parent nodes first):
   - `Milestone -> Feature -> Issue -> Task`, or
   - `Milestone -> StandaloneIssue -> Task`.
8. Add/maintain markers for the task in `dev/TASK_LIST.md` according to selected binding:
   - `[M*][F*]` for feature path,
   - `[M*][SI*]` for standalone path.
9. Update `dev/TASK_EXECUTION_PIPELINE.md` order/overlaps for pending tasks.
10. Keep this protocol and `AGENTS.md` consistent if process/policy changed.

## Bundle command format

Use this command style when requesting multiple tasks:

`Execute bundle: <taskA> -> <taskB> -> <taskC>, mode=strict, no-duplicate-logic`

Feature-chain execution command:

`execute feature <feature_id>`
