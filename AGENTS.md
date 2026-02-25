# AGENTS.md

Project-level hard constraints for task work in this repository.

## Process document ownership matrix

Use this matrix to avoid responsibility sprawl when process rules are updated.

- `AGENTS.md` (this file): hard policy constraints and non-negotiable gates (`allowed/forbidden`, explicit command requirements, tracking constraints).
- `dev/TASK_EXECUTION_PROTOCOL.md`: canonical command semantics and command order (execution, completion commands, feature/standalone execution flow).
- `dev/FEATURE_PLANNING_PROTOCOL.md`: planning-only requirements (planning input contract, decomposition rules, planning quality gates).
- `dev/FEATURE_WORKFLOW.md`: lightweight command index that links to canonical owners; no standalone normative contracts.
- `dev/FEATURE_PLANS.md`: storage for feature plan artifacts only; not a procedure/command semantics source.

Conflict handling:
- For command semantics/order conflicts, `dev/TASK_EXECUTION_PROTOCOL.md` is canonical.
- For policy gate conflicts (`allowed/forbidden`), `AGENTS.md` is canonical.
- Process change rule: when updating rules/protocol/workflow docs, change normative text only in the canonical owner file; in non-owner files keep only short references. Do not duplicate the same rule across multiple files.

Canonical rule map (to prevent duplication drift):
- Feature and standalone command order/step contracts:
  owner = `dev/TASK_EXECUTION_PROTOCOL.md`.
- Completion command semantics (`confirm ... done` cascade behavior):
  owner = `dev/TASK_EXECUTION_PROTOCOL.md`;
  policy gate references remain in `AGENTS.md`.
- Task creation/update procedure (`binding`, `task_count`, `DEV_MAP/TASK_LIST/PIPELINE` sync):
  owner = `dev/TASK_EXECUTION_PROTOCOL.md`;
  policy constraints remain in `AGENTS.md`.
- Planning input/decomposition quality gates:
  owner = `dev/FEATURE_PLANNING_PROTOCOL.md`.

## Execution trigger (strict)

1. Do not start implementing any task until the user gives an explicit execution command in one of these exact formats: `execute task X`, `execute issue <issue_id>`, or `execute feature <feature_id>`.
2. Any message that does not contain an explicit command in one of these formats (`execute task X`, `execute issue <issue_id>`, `execute feature <feature_id>`) is non-execution (clarification, planning, task-text edits, review, or discussion only).
3. If user intent looks like execution but the command format is not explicit, ask for a direct command in the required format and do not start implementation.
4. User confirmation that a task is completed is separate from execution start and must still be explicit.
5. Once execution is allowed, use `dev/TASK_EXECUTION_PROTOCOL.md` as the source of truth for command semantics/order, and use this file as the source of truth for hard policy constraints.
6. Exception for corrective fixes: if the user asks to fix a bug/regression introduced by the assistant in already changed files, apply that fix immediately without requiring an execution command; keep the scope strictly limited to correcting that mistake (no new task scope).
7. Direct `AGENTS.md` maintenance override: when the user explicitly instructs to edit `AGENTS.md`, apply the requested edits immediately, without requiring an execution command.
8. For direct `AGENTS.md` edit requests, do not block on process-format arguments; execute the edit and report the exact changes.
9. Direct edit command override (repository-wide): when the user explicitly instructs to make concrete code/config/script/file edits, apply those edits immediately without requiring an execution command.
10. Treat such direct edit commands as side edits (outside task execution flow) unless the user explicitly frames them as task execution.
11. For direct edit commands, do not block on task-command format; execute the requested edits and report changes.
12. Never make any file/code/config/script changes unless the user has explicitly asked for those concrete edits in the current message.
13. Hard no-edit default: if the user message is discussion, question, planning, or clarification, do not run any edit command and do not change any file.
14. Before any edit, require an explicit edit intent in the current user message (examples: "edit", "change", "update", "create file", "delete", "apply patch", "внеси изменения", "измени", "создай", "удали").
15. If explicit edit intent is missing, respond with analysis/instructions only and keep repository files untouched.

## Task and tracking state constraints

1. Do not mark any task or task block as completed until the user explicitly confirms completion after review.
   - Completion command semantics (including cascade behavior such as `confirm feature <id> done`) are defined in `dev/TASK_EXECUTION_PROTOCOL.md` (`Completion flow` section).
2. Keep implemented tasks in their current state (not completed) while awaiting user verification.
3. `dev/map/DEV_MAP.json` is the planning source of truth for hierarchy (`Milestone -> Feature -> Issue -> Task` and `Milestone -> StandaloneIssue -> Task`) and for non-milestone status fields.
4. `dev/TASK_LIST.json`, `dev/TASK_EXECUTION_PIPELINE.json`, and `dev/map/DEV_MAP.json` must stay synchronized when adding/updating tasks/features/standalone issues.
5. Each task entry in `dev/TASK_LIST.json` must include ownership markers:
   - product path: `[M*][F*]`
   - standalone path: `[M*][SI*]`
   If the task node exists in `dev/map/DEV_MAP.json`, markers must match that parent chain.
6. Before reporting a task as implemented, perform a mandatory final check that all requirements from the exact task text are covered; explicitly list any unmet requirement.
7. New tasks in `dev/TASK_LIST.json` must be appended only at the end of the `tasks` array as a linear list; do not regroup existing tasks.
8. New numeric task IDs must be allocated only from `task_count` in `dev/map/DEV_MAP.json` using `new_id = task_count + 1`; then set `task_count = new_id` in the same change set.
9. Do not derive new task IDs by scanning `dev/TASK_LIST.json` or by relying on visible "last task" entries.
10. Every new or rewritten task entry in `dev/TASK_LIST.json` must include a `concrete_steps` field with explicit numbered implementation steps (actionable commands/edits/checks), not only conceptual wording.
11. When creating or rewriting tasks, include only minimally sufficient actions/changes required to satisfy the stated requirement and make the result work; do not add optional improvements, extra hardening, refactors, or other non-required work unless explicitly requested by the user.

## Feature planning and materialization constraints

1. `create feature <id>` is a standalone registration step:
   - create a new feature node in `dev/map/DEV_MAP.json` by schema/ID rules;
   - create/update the corresponding feature-level GitHub issue and assign it to the target GitHub milestone;
   - persist feature `gh_issue_number`/`gh_issue_url` in `dev/map/DEV_MAP.json` in the same change set;
   - do not auto-run planning/materialization/execution steps.
2. Feature work must follow this approval-gated sequence (only after explicit next commands):
   - `plan feature <id>`
   - `approve feature plan`
   - `sync issues to task list for <id>` (local decomposition only)
   - user review/corrections of local decomposition
   - `materialize feature <id>` (GitHub materialization only)
   - `execute task X` or `execute issue <issue_id>` or `execute feature <feature_id>`
3. Every `plan feature <id>` result must be written to `dev/FEATURE_PLANS.md`; do not keep feature plans only in chat.
4. In `dev/FEATURE_PLANS.md`, each feature plan must be stored under its own feature ID section and include:
   - dependencies,
   - decomposition (strict step-by-step command flow),
   - `Issue/Task Decomposition Assessment`.
   Do not require `Scope`, `Out-of-scope`, `Acceptance criteria`, or `Risks` sections unless the user explicitly asks for them.
5. `approve feature plan` always applies to the corresponding feature section in `dev/FEATURE_PLANS.md` and must set the target feature `status` to `Approved` in `dev/map/DEV_MAP.json`.
6. Feature `status` in `dev/map/DEV_MAP.json` is the approval source of truth. If status is not `Approved`, no further feature step is allowed (`sync issues to task list`, `materialize feature`, `execute task X`, `execute issue <issue_id>`, `execute feature <feature_id>`).
7. If the approved feature section in `dev/FEATURE_PLANS.md` is changed later, continue only after a new explicit `approve feature plan` and status re-set to `Approved` in `dev/map/DEV_MAP.json`.
8. `sync issues to task list for <id>` must run only when the target feature status in `dev/map/DEV_MAP.json` is `Approved`, and it must create/update local `Issue -> Task` decomposition in the same change set across:
   - `dev/map/DEV_MAP.json` (attach under selected parent chain: `Milestone -> Feature -> Issue` or `Milestone -> StandaloneIssue`),
   - `dev/TASK_LIST.json` (with `[M*][F*]` or `[M*][SI*]` markers),
   - `dev/TASK_EXECUTION_PIPELINE.json` (overlaps/dependencies).
9. Do not materialize GitHub work issues before explicit plan approval and before local decomposition is synced/reviewed.
   - Exception: feature-level GitHub issue creation/update is allowed during `create feature <id>`.
10. During `materialize feature` and `materialize standalone-issue`, create/update GitHub issues strictly from already-defined local issue nodes; do not invent additional decomposition only on GitHub.
11. During `create feature`, `materialize feature`, and `materialize standalone-issue`, every created/updated GitHub issue must be assigned to the corresponding GitHub milestone (not label-only assignment).
12. If the target GitHub milestone does not exist or cannot be resolved, stop `create feature`/materialization and ask the user to create/select the milestone first.
13. `sync issues to task list` is mandatory before any related `execute task X` / `execute issue <issue_id>`.
14. ID formats are defined in `dev/map/DEV_MAP_SCHEMA.md` and must be used as-is (`F<local>-M<milestone>`, `I<local>-F<feature_local>-M<milestone>`, `SI<local>-M<milestone>`, global task IDs from `dev/TASK_LIST.json`).
15. Before creating any new task/issue mapping, always analyze existing features in `dev/map/DEV_MAP.json` and propose candidate bindings to the user (one or more matching feature IDs, or standalone if no suitable feature exists).
16. Immediately after candidate bindings are prepared, request user binding choice first; do not run extra preparatory checks unrelated to candidate binding before that question.
17. Binding confirmation is mandatory: do not create/update task, issue, feature, or standalone mapping nodes until the user explicitly chooses the target binding.
18. After user binding choice, continue only through the normal sync path (`DEV_MAP` + `TASK_LIST` + pipeline overlaps in the same change set).
19. For standalone (non-product) work, use `Milestone -> StandaloneIssue -> Task` path.
20. Orphan issues are not allowed: every issue must belong either to a feature (`Issue`) or to a milestone standalone container (`StandaloneIssue`).
21. Local/GitHub completion is confirmation-gated:
   - Do not mark local `Issue`/`Feature`/`StandaloneIssue` as `Done` until the user explicitly confirms completion after review.
   - Do not close related GitHub issues before that explicit completion confirmation.
22. When explicit completion confirmation is given for an `Issue`/`Feature`/`StandaloneIssue`, update local status and close corresponding GitHub issue in the same completion update run.
   - Use exact command semantics from `dev/TASK_EXECUTION_PROTOCOL.md` (`Completion flow`) for cascade updates.
23. GitHub issue content policy for `materialize feature` / `materialize standalone-issue`: write only issue-relevant content (title, scope/problem, planned work/tasks, acceptance context).
24. In GitHub issue bodies, never include process boilerplate blocks such as `Work issue for ...`, `Source of truth`, `Notes`, protocol reminders, confirmation commands, or any `do not close before ...` wording.
25. During feature planning and decomposition, enforce minimal-sufficient scope: include only items required to deliver feature behavior and the approved step/decomposition flow.
26. Do not add process artifacts by default (extra checklists, validation gates, signoff docs, protocol docs, contract docs) unless the user explicitly requests them or the approved feature plan structure explicitly requires them.
27. Prefer updating existing docs/files over creating new standalone documentation files when both options satisfy the same requirement.
28. If there is any doubt whether a planned item is required, ask the user before adding it to plan/issues/tasks.
29. Feature branch policy for `materialize feature <id>` is mandatory:
   - Canonical branch name format: `feature/<feature_id>`.
   - Example: `feature/F1-M1`.
30. On every `materialize feature <id>`, switch work context to canonical feature branch using this order:
   - if local `feature/<feature_id>` exists: checkout it;
   - else if remote `origin/feature/<feature_id>` exists: create local tracking branch from it and checkout;
   - else: create local branch `feature/<feature_id>` and checkout.
31. Never create duplicate feature branches for the same feature id (for example, `feature/F1-M1-2`, `feature/F1-M1-new`).
32. Default scope is one branch per feature; do not create per-issue branches during materialization unless user explicitly requests issue-level branches.
33. After `materialize feature <id>`, explicitly report active feature branch in the result message using format: `Active feature branch: feature/<feature_id>`.
34. `dev/map/DEV_MAP.json` feature nodes must store branch linkage fields:
   - `branch_name` (canonical value: `feature/<feature_id>`),
   - `branch_url` (canonical value: `<repo_url>/tree/feature/<feature_id>`).
35. During `materialize feature <id>`, when branch context is resolved/created, update `branch_name`/`branch_url` for that feature in the same change set as materialization metadata updates.

## Pipeline constraints

1. `dev/TASK_EXECUTION_PIPELINE.json` must contain only pending (not completed) tasks/blocks; do not keep completed entries there with markers like `(completed)`.
2. In `dev/TASK_EXECUTION_PIPELINE.json` `functional_blocks`, always include an explicit `outcome` field for each block.
3. Each block `outcome` must be concrete and feature-level: describe what exact behaviors/features/API modes/operational flows will exist after the block is done.
4. Avoid generic wording in block outcomes (for example "better", "improved", "more stable") unless tied to specific mechanisms or user-visible changes.

## Code docstring constraints

1. Any new or modified functional code must include docstrings/comments in the language-appropriate format.
2. Coverage is mandatory for:
   - modules/files,
   - classes,
   - functions/methods.
3. Existing docstrings in touched code must be updated when outdated or inaccurate.
4. Exclusions: `*.md`, `*.html`, `*.json`, and generated/vendor build artifacts.
5. Format by language:
   - Python: triple-quoted docstrings.
   - JS/TS: JSDoc-style block comments above module/class/function/method declarations.
