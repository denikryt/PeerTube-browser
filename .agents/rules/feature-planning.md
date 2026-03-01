---
trigger: always_on
glob:
description: Feature planning and decomposition policy
---

## Feature planning rules

1. ID formats are defined in `dev/map/DEV_MAP_SCHEMA.md` and must be used as-is (`F<local>-M<milestone>`, `I<local>-F<feature_local>-M<milestone>`, `SI<local>-M<milestone>`, global task IDs from `dev/TASK_LIST.json`).
2. Before creating any new task/issue mapping, always analyze existing features in `dev/map/DEV_MAP.json` and propose candidate bindings to the user.
3. Binding confirmation is mandatory: do not create/update task, issue, feature, or standalone mapping nodes until the user explicitly chooses the target binding.
4. Feature `status` in `dev/map/DEV_MAP.json` is the approval source of truth. If status is not `Approved`, no further feature step is allowed.
5. Do not materialize GitHub work issues before explicit plan approval and before local decomposition is synced/reviewed.
6. During `create feature`, `materialize feature`, and `materialize standalone-issue`, every created/updated GitHub issue must be assigned to the corresponding GitHub milestone.
7. Orphan issues are not allowed: every issue must belong either to a feature (`Issue`) or to a milestone standalone container (`StandaloneIssue`).
8. Local/GitHub completion is confirmation-gated: Do not mark local state as `Done` or close GitHub issues until explicit user confirmation is received.
9. For any explicit user request to plan an issue (`plan issue ...`), update the target issue block in `dev/FEATURE_PLANS.md` in the same turn and enforce full compliance with `.agents/protocols/feature-planning-protocol.md` (mandatory headings + Gate 0 quality).

## Feature branch policy

1. Feature branch naming and materialization must follow the procedure defined in `.agents/protocols/task-execution-protocol.md` (Section 6, Branch policy).
2. Store branch linkage in `dev/map/DEV_MAP.json`: `branch_name` and `branch_url`.

## Feature decomposition policy

1. One feature maps to one primary feature issue (`type:feature`) on GitHub.
2. Feature decomposition into logical issues must strictly follow the criteria and standards defined in `.agents/protocols/feature-planning-protocol.md` (Section 2, Decomposition Rules).
3. Prioritize reusing existing issues in `dev/map/DEV_MAP.json` over creating new ones whenever possible.

