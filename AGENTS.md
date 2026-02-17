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
