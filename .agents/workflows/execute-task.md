---
description: Execute a single task following strict protocol
---
1. Preparation: Follow the **Mandatory Read Order** defined in Section 1 of `.agents/protocols/task-execution-protocol.md`.
2. Check trackers: Read the exact task text for the given task ID from `dev/TASK_LIST.json` and context from `dev/map/DEV_MAP.json`.
3. Check overlaps: Read `dev/ISSUE_OVERLAPS.json` for issue-level constraints and `dev/FEATURE_PLANS.md` / `dev/map/DEV_MAP.json` for issue/task order context.
4. Enforce materialization: Verify the **Materialization Gate** for the parent issue in `dev/map/DEV_MAP.json`. Stop if `gh_issue_number` or `gh_issue_url` are missing.
5. Plan: Prepare a short implementation plan listing concrete files/modules to update.
6. Execution: Implement code/doc/config changes required, avoiding duplicate logic.
7. Validation: Run relevant checks/tests to verify no regressions in overlapping areas.
8. Closure Check: Re-read the exact task text from `dev/TASK_LIST.json` and explicitly verify EVERY stated requirement is implemented.
9. Stop execution. Do NOT mark the task as done.
10. Use the `notify_user` tool with `BlockedOnUser=true` to ask the user for explicit confirmation (e.g. `confirm task <id> done` or `reject task <id>`).
