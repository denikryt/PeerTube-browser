---
description: Execute a single task following strict protocol
---
1. Check task tracker: Read the exact task text for the given task ID from `dev/TASK_LIST.json`.
2. Check overlaps/dependencies: Read `dev/TASK_EXECUTION_PIPELINE.json` to inspect ordering constraints and identify shared primitives.
3. Check context: Read `dev/map/DEV_MAP.json` to verify ownership markers (`[M*][F*]` or `[M*][SI*]`).
4. Enforce materialization: Resolve the parent `Issue` in `dev/map/DEV_MAP.json` and ensure `gh_issue_number` and `gh_issue_url` are not null. Stop if they are missing.
5. Plan: Prepare a short implementation plan listing concrete files/modules to update.
6. Execution: Implement code/doc/config changes required, avoiding duplicate logic.
7. Validation: Run relevant checks/tests to verify no regressions in overlapping areas.
8. Closure Check: Re-read the exact task text from `dev/TASK_LIST.json` and explicitly verify EVERY stated requirement is implemented.
9. Stop execution. Do NOT mark the task as done.
10. Use the `notify_user` tool with `BlockedOnUser=true` to ask the user for explicit confirmation (e.g. `confirm task <id> done` or `reject task <id>`).
