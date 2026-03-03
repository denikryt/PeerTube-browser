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
6. `confirm issue <issue_id> done` must not cascade unfinished child tasks to `Done` without additional explicit user confirmation.
7. `confirm feature <feature_id> done` is full-subtree confirmation for the feature and its mapped child issues/tasks.
8. `confirm standalone-issue <si_id> done` is allowed only when all mapped child tasks are already confirmed done.
9. `reject issue <issue_id>` must keep mapped issues as local `Rejected` nodes, but must remove unmapped local issue nodes instead of applying a status-only transition.
10. Completion and rejection flows must not mutate GitHub issue checklist rows; status is tracked by local state and issue close flow.

### After user confirmation (required sequence)

When the user explicitly confirms a task or block of tasks is completed, perform the mandatory update sequence defined in `.agents/protocols/task-execution-protocol.md` (Section 4: Completion state-transition contract) in the same edit run.
