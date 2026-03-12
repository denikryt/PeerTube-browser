---
description: Execute one issue under the target-state workflow model
---
1. Read `.agents/protocols/task-execution-protocol.md`.
2. Resolve `<issue_id>` in `dev/map/DEV_MAP.json`.
3. Verify the issue is materialized on GitHub.
4. Read the exact issue plan block in `dev/FEATURE_PLANS.md`.
5. Implement the scoped changes described by the issue and its local task decomposition.
6. Run validations for the touched surfaces.
7. Do not auto-mark the issue done; wait for explicit `done issue <id>`.
