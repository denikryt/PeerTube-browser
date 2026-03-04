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
10. `plan tasks for issue <issue_id>` is blocked while the target issue status is `Pending`; the issue must be planned first.
11. Successful local issue-to-task decomposition transitions the selected issue nodes to `Tasked`.
12. Before `plan tasks for feature <feature_id>` or `plan tasks for issue <issue_id>`, the agent must read the current code relevant to the scoped issues; task decomposition may not be written from plan text alone.
13. Tasks created during `plan tasks` must describe concrete code changes and validations, including what to remove, add, modify, rename, move, or test.
14. Overlap entries added to `dev/TASK_EXECUTION_PIPELINE.json` during `plan tasks` must be justified by actual shared code surfaces or dependency chains observed in the codebase.
15. Overlap descriptions may include a short generalized summary only if they also state the concrete code-level basis for that overlap.
16. `create feature` is registration-only; it must not auto-run planning, task decomposition, materialization, or execution commands.
17. Materialized GitHub issue bodies must remain issue-focused and must not include local process/protocol instructions or boilerplate sections such as `Work issue for ...`, `Source of truth`, or `Notes`.
18. Before `execute task <id>`, `execute issue <issue_id>`, or `execute feature <feature_id>`, every parent `Issue` in scope must already be mapped with non-null `gh_issue_number` and `gh_issue_url`.
19. Before executing a task attached to `StandaloneIssue`, the parent standalone issue must already be mapped with non-null `gh_issue_number` and `gh_issue_url`.
20. For `create feature`, `milestone_id` remains mandatory input. If the user does not explicitly provide feature title and/or description, derive them from the current request context and nearby discussion instead of blocking for additional wording.
21. Any auto-derived feature title/description used during `create feature` must stay concrete, repository-specific, and consistent with the user request; do not invent unrelated scope.

## Feature branch policy

1. Feature branch naming and materialization must follow `.agents/protocols/task-execution-protocol.md` (Section 5: Branch and materialization standards).
2. Store branch linkage in `dev/map/DEV_MAP.json`: `branch_name` and `branch_url`.

## Feature decomposition policy

1. One feature maps to one primary feature issue (`type:feature`) on GitHub.
2. Feature decomposition into logical issues must strictly follow the criteria and standards defined in `.agents/protocols/feature-planning-protocol.md` (Section 2, Decomposition Rules).
3. Prioritize reusing existing issues in `dev/map/DEV_MAP.json` over creating new ones whenever possible.
