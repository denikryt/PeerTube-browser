# AGENTS.md

Project-level hard constraints for task work in this repository.

## Execution trigger (strict)

1. Do not start implementing any task until the user gives an explicit execution command in one of these exact formats: `execute task X` or `execute feature <feature_id>`.
2. Any message that does not contain an explicit command in one of these formats (`execute task X`, `execute feature <feature_id>`) is non-execution (clarification, planning, task-text edits, review, or discussion only).
3. If user intent looks like execution but the command format is not explicit, ask for a direct command in the required format and do not start implementation.
4. User confirmation that a task is completed is separate from execution start and must still be explicit.
5. Once execution is allowed, follow `dev/TASK_EXECUTION_PROTOCOL.md` as the only process source of truth.
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
2. Keep implemented tasks in their current state (not completed) while awaiting user verification.
3. `dev/map/DEV_MAP.json` is the planning source of truth for hierarchy (`Milestone -> Feature -> Issue -> Task` and `Milestone -> StandaloneIssue -> Task`) and for non-milestone status fields.
4. `dev/TASK_LIST.md`, `dev/TASK_EXECUTION_PIPELINE.md`, and `dev/map/DEV_MAP.json` must stay synchronized when adding/updating tasks/features/standalone issues.
5. Each task entry in `dev/TASK_LIST.md` must include ownership markers:
   - product path: `[M*][F*]`
   - standalone path: `[M*][SI*]`
   If the task node exists in `dev/map/DEV_MAP.json`, markers must match that parent chain.
6. Before reporting a task as implemented, perform a mandatory final check that all requirements from the exact task text are covered; explicitly list any unmet requirement.
7. New tasks in `dev/TASK_LIST.md` must be added only at the end of the file as a single linear list entry; do not place new tasks into category sections and do not regroup existing tasks by categories.
8. New numeric task IDs must be allocated only from `task_count` in `dev/map/DEV_MAP.json` using `new_id = task_count + 1`; then set `task_count = new_id` in the same change set.
9. Do not derive new task IDs by scanning `dev/TASK_LIST.md` or by relying on visible "last task" entries.
10. Every new or rewritten task entry in `dev/TASK_LIST.md` must include a `#### **Concrete steps:**` section with explicit numbered implementation steps (actionable commands/edits/checks), not only conceptual wording.
11. When creating or rewriting tasks, include only minimally sufficient actions/changes required to satisfy the stated requirement and make the result work; do not add optional improvements, extra hardening, refactors, or other non-required work unless explicitly requested by the user.

## Feature planning and materialization constraints

1. Feature work must follow this approval-gated sequence:
   - `plan feature <id>`
   - `approve feature plan`
   - `sync issues to task list for <id>` (local decomposition only)
   - user review/corrections of local decomposition
   - `materialize feature <id>` (GitHub materialization only)
   - `execute task X` or `execute feature <feature_id>`
2. Every `plan feature <id>` result must be written to `dev/FEATURE_PLANS.md`; do not keep feature plans only in chat.
3. In `dev/FEATURE_PLANS.md`, each feature plan must be stored under its own feature ID section and include: scope, out-of-scope, acceptance criteria, risks, dependencies, decomposition.
4. `approve feature plan` always applies to the corresponding feature section in `dev/FEATURE_PLANS.md`; this approved section becomes the source of truth for subsequent decomposition/materialization/execution.
5. If the approved feature section in `dev/FEATURE_PLANS.md` is changed later, continue only after a new explicit `approve feature plan`.
6. `sync issues to task list for <id>` must create/update local `Issue -> Task` decomposition in the same change set across:
   - `dev/map/DEV_MAP.json` (attach under selected parent chain: `Milestone -> Feature -> Issue` or `Milestone -> StandaloneIssue`),
   - `dev/TASK_LIST.md` (with `[M*][F*]` or `[M*][SI*]` markers),
   - `dev/TASK_EXECUTION_PIPELINE.md` (overlaps/dependencies).
7. Do not materialize GitHub feature/work issues before explicit plan approval and before local decomposition is synced/reviewed.
8. During `materialize feature` and `materialize standalone-issue`, create/update GitHub issues strictly from already-defined local issue nodes; do not invent additional decomposition only on GitHub.
9. During `materialize feature` and `materialize standalone-issue`, every created/updated GitHub issue must be assigned to the corresponding GitHub milestone (not label-only assignment).
10. If the target GitHub milestone does not exist or cannot be resolved, stop materialization and ask the user to create/select the milestone first.
11. `sync issues to task list` is mandatory before any related `execute task X`.
12. ID formats are defined in `dev/map/DEV_MAP_SCHEMA.md` and must be used as-is (`F<local>-M<milestone>`, `I<local>-F<feature_local>-M<milestone>`, `SI<local>-M<milestone>`, global task IDs from `dev/TASK_LIST.md`).
13. Before creating any new task/issue mapping, always analyze existing features in `dev/map/DEV_MAP.json` and propose candidate bindings to the user (one or more matching feature IDs, or standalone if no suitable feature exists).
14. Immediately after candidate bindings are prepared, request user binding choice first; do not run extra preparatory checks unrelated to candidate binding before that question.
15. Binding confirmation is mandatory: do not create/update task, issue, feature, or standalone mapping nodes until the user explicitly chooses the target binding.
16. After user binding choice, continue only through the normal sync path (`DEV_MAP` + `TASK_LIST` + pipeline overlaps in the same change set).
17. For standalone (non-product) work, use `Milestone -> StandaloneIssue -> Task` path.
18. Orphan issues are not allowed: every issue must belong either to a feature (`Issue`) or to a milestone standalone container (`StandaloneIssue`).
19. Local/GitHub completion is confirmation-gated:
   - Do not mark local `Issue`/`Feature`/`StandaloneIssue` as `Done` until the user explicitly confirms completion after review.
   - Do not close related GitHub issues before that explicit completion confirmation.
20. When explicit completion confirmation is given for an `Issue`/`Feature`/`StandaloneIssue`, update local status and close corresponding GitHub issue in the same completion update run.
21. GitHub issue content policy for `materialize feature` / `materialize standalone-issue`: write only issue-relevant content (title, scope/problem, planned work/tasks, acceptance context).
22. In GitHub issue bodies, never include process boilerplate blocks such as `Work issue for ...`, `Source of truth`, `Notes`, protocol reminders, confirmation commands, or any `do not close before ...` wording.
23. During feature planning and decomposition, enforce minimal-sufficient scope: include only items required to deliver feature behavior and explicit acceptance criteria.
24. Do not add process artifacts by default (extra checklists, validation gates, signoff docs, protocol docs, contract docs) unless the user explicitly requests them or the feature acceptance criteria explicitly require them.
25. Prefer updating existing docs/files over creating new standalone documentation files when both options satisfy the same requirement.
26. If there is any doubt whether a planned item is required, ask the user before adding it to plan/issues/tasks.

## Pipeline constraints

1. `dev/TASK_EXECUTION_PIPELINE.md` must contain only pending (not completed) tasks/blocks; do not keep completed entries there with markers like `(completed)`.
2. In `dev/TASK_EXECUTION_PIPELINE.md` Functional blocks, always include an explicit `Outcome` line for each block.
3. Each block `Outcome` must be concrete and feature-level: describe what exact behaviors/features/API modes/operational flows will exist after the block is done.
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
