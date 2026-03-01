---
trigger: always_on
glob:
description: Task state management and tracking rules
---

## Task state management

1. Do not mark any task or task block as completed until the user explicitly confirms completion after review.
2. Do not move entries from `dev/TASK_LIST.json` to any completed/done list until explicit user confirmation is received.
3. Keep implemented tasks in their current state (not completed) while awaiting user verification.
4. Keep wording/style consistent with existing entries in tracking artifacts.
5. Keep `dev/TASK_LIST.json`, `dev/TASK_EXECUTION_PIPELINE.json`, and `.agents/protocols/task-execution-protocol.md` consistent when adding/updating tasks.
6. `CHANGELOG.json` is a public task board (human-readable roadmap-style tasks), not only a done-history log.
7. Every public changelog task must have an explicit status (allowed: `Planned`, `Done`).
8. Update an item in `CHANGELOG.json` to `Done` only after explicit user confirmation of completion.
9. Keep public changelog task wording human-readable and maintain stable task identity so status updates are deterministic.

### After user confirmation (required sequence)

When the user explicitly confirms a task or block of tasks is completed, perform these steps in the same edit run:

1. Update task status in `dev/map/DEV_MAP.json` to `Done`.
2. Update task state in `dev/TASK_LIST.json` (remove/move the confirmed task from future tasks).
3. Update the matching item in `CHANGELOG.json` to status `Done`.
4. If task ordering/block status changed, update `dev/TASK_EXECUTION_PIPELINE.json` accordingly.
5. If execution rules changed, update `.agents/protocols/task-execution-protocol.md` accordingly.
6. In the final response, explicitly list which task IDs/titles were marked completed.

