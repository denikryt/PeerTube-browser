---
description: Execute all pending tasks for a feature chain
---
1. Initialization: Resolve `<feature_id>` in `dev/map/DEV_MAP.json` and collect all child pending tasks (`status != Done`) under `Milestone -> Feature -> Issue -> Task`.
2. Materialization Gate: For every issue containing pending tasks, verify `gh_issue_number` and `gh_issue_url` exist. Stop and request materialization if any are missing.
3. Execution Order: Build the order using `dev/TASK_EXECUTION_PIPELINE.json` first, then by remaining pending tasks in `DEV_MAP` issue/task order.
4. Execution: Execute EACH task sequentially using the full standard execution flow (including reading context, implementing, validating, and checking exact requirements).
5. Overlap Check: After each task, run overlap/dependency validations relevant to the next tasks in the same feature chain. Stop on the first blocking failure.
6. Stop execution. Do not auto-mark task/issue/feature as `Done`. Wait for the user to explicitly confirm feature completion using `notify_user` with `BlockedOnUser=true` (e.g., `confirm feature <id> done`).
