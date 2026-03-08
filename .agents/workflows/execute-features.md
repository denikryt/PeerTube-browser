---
description: Execute multiple features sequentially as a thin wrapper over execute-feature
---
1. Initialization: Parse the provided feature ID list in the exact user-supplied order.
2. Scope Validation: Resolve every `<feature_id>` in `dev/map/DEV_MAP.json`. If any ID is missing, duplicated, or invalid, stop and report the error.
3. Wrapper Contract: Treat this workflow as a thin sequential wrapper only. Do not invent package-level planning, global reordering, cross-feature merge logic, or new dependency semantics.
4. Execution: For each `<feature_id>` in the original user order, execute the full workflow from `.agents/workflows/execute-feature.md` exactly as written.
5. Failure Policy: If any feature execution blocks or fails at any step, stop the batch immediately. Do not continue to later feature IDs.
6. Stop execution. Do not auto-mark any task, issue, or feature as `Done`. Wait for explicit user confirmation commands after review.
