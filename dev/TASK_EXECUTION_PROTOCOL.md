# Task Execution Protocol

This file defines only the execution procedure (how to execute tasks).
Hard constraints (what is allowed/forbidden) are defined in `AGENTS.md`.

## Standard execution flow (single task)

Use this procedure after an explicit execution command is given.

1. **Read in strict order before coding**
   - Read exact task text for task `X` in `dev/TASK_LIST.md`.
   - Read `dev/TASK_EXECUTION_PIPELINE.md`.
   - Read `dev/map/DEV_MAP.json` context for task `X` and related milestone/feature ownership markers.
   - Read this file (`dev/TASK_EXECUTION_PROTOCOL.md`).

2. **Check overlaps/dependencies**
   - For task `X`, inspect overlaps and ordering constraints in `dev/TASK_EXECUTION_PIPELINE.md`.
   - Identify shared primitives to avoid one-off local implementations.
   - Verify `[M*][F*]` markers in `dev/TASK_LIST.md` are consistent with planned ownership; if task exists in `dev/map/DEV_MAP.json`, markers must match parent chain.

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

## Completion flow (after explicit user confirmation)

When user explicitly confirms task/block completion, update all trackers in the same edit run:

1. Update task state in `dev/TASK_LIST.md` (remove/move confirmed task from future tasks).
2. Update task status in `dev/map/DEV_MAP.json` under its existing parent chain.
3. Update matching entry in `CHANGELOG.json` to status `Done`.
4. Remove the confirmed completed task/block from `dev/TASK_EXECUTION_PIPELINE.md` (keep only pending items).
5. If process rules changed, update this file in the same edit run.

## Feature planning/materialization flow

Use this procedure before executing tasks for a new feature.

1. `create feature <id>`: create feature node in `dev/map/DEV_MAP.json` using ID format from `dev/map/DEV_MAP_SCHEMA.md`.
2. `plan feature <id>`: produce scope, out-of-scope, acceptance criteria, risks, dependencies, decomposition.
3. `approve feature plan`: freeze boundaries and allow materialization.
4. `materialize feature`: create/update GitHub feature/work issues and persist `gh_issue_number`/`gh_issue_url` in `dev/map/DEV_MAP.json`.
5. `sync issues to task list`: synchronize tasks into `dev/TASK_LIST.md` (`[M*][F*]` markers) and overlaps in `dev/TASK_EXECUTION_PIPELINE.md`.
6. Only then run `execute task X`.

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
2. Update `dev/TASK_LIST.md` as one linear list (append new tasks to the end).
3. Attach/update the task in `dev/map/DEV_MAP.json` under existing `Milestone -> Feature -> Issue` chain (or create missing parent nodes first).
4. Add/maintain `[M*][F*]` markers for the task in `dev/TASK_LIST.md`.
5. Update `CHANGELOG.json` in the same edit run (append new entries to the end, keep ID equal to task number).
6. Update `dev/TASK_EXECUTION_PIPELINE.md` order/overlaps for pending tasks.
7. Keep this protocol and `AGENTS.md` consistent if process/policy changed.

## Bundle command format

Use this command style when requesting multiple tasks:

`Execute bundle: <taskA> -> <taskB> -> <taskC>, mode=strict, no-duplicate-logic`
