# Task Execution Protocol

This protocol defines how to execute one or multiple tasks consistently.
Use it together with `TASK_EXECUTION_PIPELINE.md`.

## Multi-task execution protocol

Use this protocol when implementing multiple tasks in one run.

1. **Read bundle + overlaps first**
   - Identify shared logic, dependencies, and possible conflicts before coding.
   - Write a short bundle plan (order + shared components).

2. **Implement shared primitives first**
   - If tasks overlap, implement shared contracts/abstractions/utilities first.
   - Avoid duplicate logic across related modules.

3. **Implement tasks in dependency order**
   - Follow `Recommended implementation order` from `TASK_EXECUTION_PIPELINE.md`.
   - If order must change, note why in task notes.

4. **Run one integration pass for the whole bundle**
   - Verify final behavior after all tasks are applied together.
   - Check regressions in overlapping areas (shared configs, interfaces, and data flow).

5. **Done criteria for multi-task bundle**
   - One source of truth per concern (no duplicate competing implementations).
   - All requested tasks work together without conflicting behavior.
   - Task status/docs are updated consistently (`TASK_LIST.md`, `COMPLETED_TASKS.md`, related docs).
   - Completed tasks are moved from `TASK_LIST.md` to `COMPLETED_TASKS.md` in the same run.

## Update protocol for new tasks

For every new task:

1. Assign a block in `TASK_EXECUTION_PIPELINE.md`.
2. Insert it into global execution order.
3. Add overlap notes if it intersects existing logic.
4. Keep `TASK_EXECUTION_PIPELINE.md` and `TASK_LIST.md` consistent.

## Bundle command format

Use this command style when requesting multiple tasks:

`Execute bundle: <taskA> -> <taskB> -> <taskC>, mode=strict, no-duplicate-logic`
