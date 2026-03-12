---
description: Execute one feature under the target-state workflow model
---
1. Read `.agents/protocols/task-execution-protocol.md`.
2. Resolve `<feature_id>` in `dev/map/DEV_MAP.json`.
3. Verify the feature issue is published and every pending child issue has GitHub mapping metadata.
4. Build issue order from `dev/ISSUE_OVERLAPS.json`, then fall back to feature issue order in `DEV_MAP`.
5. Read the relevant task decomposition from `dev/FEATURE_PLANS.md`.
6. Implement the scoped code/doc/config changes in dependency order.
7. Run validations for the touched areas before reporting completion.
8. Do not auto-mark the feature or issues done; wait for explicit `done ...` action.
