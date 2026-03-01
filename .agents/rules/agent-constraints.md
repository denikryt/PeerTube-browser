---
trigger: always_on
glob:
description: Mandatory pre-task and implementation constraints
---

## Mandatory pre-task checks

Before implementing any task or task bundle, always:

1. Read `dev/TASK_EXECUTION_PIPELINE.json` and `.agents/protocols/task-execution-protocol.md`.
2. Before adding a new task (or rewriting an existing one), inspect the real implementation context in code first:
   - read the relevant modules/handlers/scripts/configs/tests,
   - verify how the feature currently works in this repository,
   - then write task steps based on actual code paths/files (not only high-level assumptions).
3. If multiple tasks are requested:
   - build execution order from `dev/TASK_EXECUTION_PIPELINE.json`,
   - identify overlaps/dependencies before coding.
4. If any task text is added/edited in `dev/TASK_LIST.json`:
   - explicitly check whether `dev/TASK_EXECUTION_PIPELINE.json` needs updates (order, block, overlaps),
   - apply pipeline changes in the same edit run when needed.

## Implementation requirements

1. Implement shared primitives first when tasks overlap.
2. Avoid duplicate logic across parallel modules.
3. Avoid local one-off implementations that would force duplicate rewrites in upcoming related tasks.
4. Never skip changelog synchronization for task create/update/complete actions; treat it as a mandatory blocking rule.
5. New tasks in `CHANGELOG.json` must be added only at the end of the `entries` array (append-only).
6. New tasks in `dev/TASK_LIST.json` must be added only at the end of the file as a single linear list entry.

