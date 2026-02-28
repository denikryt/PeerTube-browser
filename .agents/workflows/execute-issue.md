---
description: Execute all pending tasks for a specific issue
---
1. Initialization: Resolve the given `<issue_id>` in `dev/map/DEV_MAP.json` under `Milestone -> Feature -> Issue`.
2. Formulate execution scope: Collect all pending tasks (`status != Done`) from this issue subtree. If no pending tasks exist, stop and report there is nothing to execute.
3. Materialization Gate: Enforce that the target issue node has a valid `gh_issue_number` and `gh_issue_url`. Stop if either is missing.
4. Execution Order: Build the execution order. First prioritize IDs present in `dev/TASK_EXECUTION_PIPELINE.json` execution order, then fall back to the `DEV_MAP` issue task order.
5. Execution: Execute each task sequentially utilizing the full standard execution procedure (identifying dependencies, implementing code/doc changes, and running requirement closure checks).
6. Overlaps: After each task, run overlap/dependency validations relevant to the next tasks in the same issue chain. Stop on the first blocking failure and report it.
7. Stop execution. Do not auto-mark any task or issue as `Done`. Wait for explicit user confirmation via `notify_user` with `BlockedOnUser=true` (e.g., `confirm issue <id> done`).
