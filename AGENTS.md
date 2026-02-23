# AGENTS.md

Project-level hard constraints for task work in this repository.

## Execution trigger (strict)

1. Do not start implementing any task until the user gives an explicit execution command in this exact format: `execute task X`.
2. Any message that does not contain an explicit command in the format `execute task X` is non-execution (clarification, planning, task-text edits, review, or discussion only).
3. If user intent looks like execution but the command format is not explicit, ask for a direct command in the required format and do not start implementation.
4. User confirmation that a task is completed is separate from execution start and must still be explicit.
5. Once execution is allowed, follow `dev/TASK_EXECUTION_PROTOCOL.md` as the only process source of truth.
6. Exception for corrective fixes: if the user asks to fix a bug/regression introduced by the assistant in already changed files, apply that fix immediately without requiring `execute task X`; keep the scope strictly limited to correcting that mistake (no new task scope).
7. Direct `AGENTS.md` maintenance override: when the user explicitly instructs to edit `AGENTS.md`, apply the requested edits immediately, without requiring `execute task X`.
8. For direct `AGENTS.md` edit requests, do not block on process-format arguments; execute the edit and report the exact changes.
9. Direct edit command override (repository-wide): when the user explicitly instructs to make concrete code/config/script/file edits, apply those edits immediately without requiring `execute task X`.
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

## Feature planning and materialization constraints

1. Feature work must follow approval-gated flow: `plan feature` -> `approve feature plan` -> `materialize feature`.
2. Do not materialize GitHub feature/work issues before explicit plan approval.
3. `sync issues to task list` is mandatory before any related `execute task X`.
4. ID formats are defined in `dev/map/DEV_MAP_SCHEMA.md` and must be used as-is (`F<local>-M<milestone>`, `I<local>-F<feature_local>-M<milestone>`, `SI<local>-M<milestone>`, global task IDs from `dev/TASK_LIST.md`).
5. New task direct path is allowed only with same-change synchronization in all three files:
   - `dev/map/DEV_MAP.json` (attach under selected parent chain: `Milestone -> Feature -> Issue` or `Milestone -> StandaloneIssue`),
   - `dev/TASK_LIST.md` (with `[M*][F*]` or `[M*][SI*]` markers),
   - `dev/TASK_EXECUTION_PIPELINE.md` (overlaps/dependencies).
6. Before creating any new task/issue mapping, always analyze existing features in `dev/map/DEV_MAP.json` and propose candidate bindings to the user (one or more matching feature IDs, or standalone if no suitable feature exists).
7. Binding confirmation is mandatory: do not create/update task, issue, feature, or standalone mapping nodes until the user explicitly chooses the target binding.
8. After user binding choice, continue only through the normal sync path (`DEV_MAP` + `TASK_LIST` + pipeline overlaps in the same change set).
9. For standalone (non-product) work, use `Milestone -> StandaloneIssue -> Task` path.
10. Orphan issues are not allowed: every issue must belong either to a feature (`Issue`) or to a milestone standalone container (`StandaloneIssue`).

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
