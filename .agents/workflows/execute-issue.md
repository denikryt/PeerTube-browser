---
description: Execute all pending tasks for a specific issue
---
1. Initialization: Resolve the given `<issue_id>` in `dev/map/DEV_MAP.json` under `Milestone -> Feature -> Issue`.
2. Formulate execution scope: Collect all pending tasks (`status != Done`) from this issue subtree. If no pending tasks exist, stop and report there is nothing to execute.
3. Materialization Gate: Enforce the **Materialization Gate** for the target issue as defined in `.agents/protocols/task-execution-protocol.md`. Stop if mapping is missing.
4. Execution Order: Build the execution order (Pipeline order first, then `DEV_MAP` task order).
5. Execution: Execute each task sequentially following the procedure in `execute-task.md`.
6. Overlaps: After each task, run overlap/dependency validations relevant to the next tasks in the same issue chain. Stop on the first blocking failure.
7. Stop execution. Do not auto-mark any task or issue as `Done`. Wait for explicit user confirmation via `notify_user` with `BlockedOnUser=true` (e.g., `confirm issue <id> done`).
