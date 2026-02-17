# AGENTS.md

Project-level execution rules for task work in this repository.

## Mandatory pre-task checks

Before implementing any task or task bundle, always:

1. Read `dev/TASK_EXECUTION_PIPELINE.md`.
2. Read `dev/TASK_EXECUTION_PROTOCOL.md`.
3. If multiple tasks are requested:
   - build execution order from `dev/TASK_EXECUTION_PIPELINE.md`,
   - identify overlaps/dependencies before coding.
4. If any task text is added/edited in `dev/TASK_LIST.md`:
   - explicitly check whether `dev/TASK_EXECUTION_PIPELINE.md` needs updates (order, block, overlaps),
   - apply pipeline changes in the same edit run when needed.
5. Before adding a new task (or rewriting an existing one), inspect the real implementation context in code first:
   - read the relevant modules/handlers/scripts/configs/tests,
   - verify how the feature currently works in this repository,
   - then write task steps based on actual code paths/files (not only high-level assumptions).

## Multi-task execution requirements

1. Implement shared primitives first when tasks overlap.
2. Avoid duplicate logic across parallel modules.
3. Run one integration pass for the whole task bundle.

## Single-task execution requirements

1. Even for one task, check its overlaps/dependencies in `dev/TASK_EXECUTION_PIPELINE.md` before coding.
2. Implement with future tasks from the same block in mind (shared primitives first where reasonable).
3. Avoid local one-off implementations that would force duplicate rewrites in upcoming related tasks.

## Task execution trigger (strict)

1. Do not start implementing any task until the user gives an explicit execution command in this exact format: `выполни задачу X`.
2. Any message that does not contain an explicit command in the format `выполни задачу X` is treated as non-execution (clarification, planning, edits of task text, review, or discussion only).
3. If the user intent looks like execution but the command format is not explicit, ask for a direct command in the required format and do not start implementation.
4. User confirmation that a task is completed is separate from execution start and must still be explicit (see Task state management rules below).

## Task state management

1. Do not mark any task or task block as completed until the user explicitly confirms completion after review.
2. Do not move entries from `dev/TASK_LIST.md` to `dev/COMPLETED_TASKS.md` until explicit user confirmation is received.
3. Keep implemented tasks in their current state (not completed) while awaiting user verification.
4. Keep wording/style consistent with existing entries in `dev/COMPLETED_TASKS.md`.
5. Keep `dev/TASK_LIST.md`, `dev/TASK_EXECUTION_PIPELINE.md`, and `dev/TASK_EXECUTION_PROTOCOL.md` consistent when adding/updating tasks.
6. `CHANGELOG.json` is a public task board (human-readable roadmap-style tasks), not only a done-history log.
7. Every public changelog task must have an explicit status (allowed: `Planned`, `Done`).
8. Update an item in `CHANGELOG.json` to `Done` only after explicit user confirmation of completion.
9. Keep public changelog task wording human-readable and maintain stable task identity so status updates are deterministic.
10. When creating any new task in `dev/TASK_LIST.md`, add the corresponding task entry to `CHANGELOG.json` in the same edit run with status `Planned`.
11. When changing task text/scope/title/ID in `dev/TASK_LIST.md`, explicitly check whether the matching item in `CHANGELOG.json` must be updated; apply that changelog update in the same edit run when needed.
12. Never skip changelog synchronization for task create/update/complete actions; treat it as a mandatory blocking rule.
13. `CHANGELOG.json` task `id` must be exactly the task number from `dev/TASK_LIST.md` (for example: `1`, `30`, `45`, `8b`, `12a`, `16l`) and must not use text slugs.
14. Task-number identity is canonical: one task number in `dev/TASK_LIST.md` -> one entry with the same `id` in `CHANGELOG.json` (no duplicates, no aliases).
15. New tasks in `CHANGELOG.json` must be added only at the end of the `entries` array (append-only); do not insert/reorder by category or any other grouping.
16. New tasks in `dev/TASK_LIST.md` must be added only at the end of the file as a single linear list entry; do not place new tasks into category sections and do not regroup existing tasks by categories.

### After user confirmation (required sequence)

When the user explicitly confirms a task or block of tasks is completed, perform these steps in the same edit run:

1. Update task state in `dev/TASK_LIST.md` (remove/move the confirmed task from future tasks).
2. Add the task to `dev/COMPLETED_TASKS.md` with consistent wording/style.
3. Update the matching item in `CHANGELOG.json` to status `Done`.
4. If task ordering/block status changed, update `dev/TASK_EXECUTION_PIPELINE.md` accordingly.
5. If execution rules changed, update `dev/TASK_EXECUTION_PROTOCOL.md` accordingly.
6. In the final response, explicitly list which task IDs/titles were marked completed.

## Command style for bundles

Use this format for multi-task requests:

`Execute bundle: <taskA> -> <taskB> -> <taskC>, mode=strict, no-duplicate-logic`
