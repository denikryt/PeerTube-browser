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
### After user confirmation (required sequence)

When the user explicitly confirms a task or block of tasks is completed, perform the mandatory update sequence defined in `.agents/protocols/task-execution-protocol.md` (Completion flow) in the same edit run.
