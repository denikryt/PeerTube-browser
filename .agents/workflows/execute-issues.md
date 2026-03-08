---
description: Execute multiple issues as one ordered package
---
1. Initialization: Parse the provided issue ID list as the seed package scope.
2. Scope Validation: Resolve every `<issue_id>` in `dev/map/DEV_MAP.json` and verify all issues belong to one valid owner chain. If any ID is missing, duplicated, or invalid, stop and report the error.
3. Materialization Gate: For every issue in the package, enforce the **Materialization Gate** defined in `.agents/protocols/task-execution-protocol.md`. Stop if any issue mapping is missing.
4. Read Order: Before coding for each issue, follow the mandatory read order from `.agents/protocols/task-execution-protocol.md` Section 1.
5. Execution Order: Resolve the package issue order from `issue_execution_order` in `dev/ISSUE_OVERLAPS.json`, restricted to the selected issue subset. Within each issue, follow `.agents/workflows/execute-issue.md`.
6. Overlap Check: After finishing each issue, re-check overlaps and dependency constraints that affect the next issue in the package. Stop on the first blocking failure.
7. Stop execution. Do not auto-mark any task or issue as `Done`. Wait for explicit user confirmation for completion commands after review.
