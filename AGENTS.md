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
2. Do not move entries from `dev/TASK_LIST.md` to `dev/COMPLETED_TASKS.md` until explicit user confirmation is received.
3. Keep implemented tasks in their current state (not completed) while awaiting user verification.
4. Keep wording/style consistent with existing entries in `dev/COMPLETED_TASKS.md`.
5. Keep `dev/TASK_LIST.md`, `dev/TASK_EXECUTION_PIPELINE.md`, and `dev/TASK_EXECUTION_PROTOCOL.md` consistent when adding/updating tasks.
6. Before reporting a task as implemented, perform a mandatory final check that all requirements from the exact task text are covered; explicitly list any unmet requirement.

## Changelog constraints

1. `CHANGELOG.json` is a public task board (human-readable roadmap-style tasks), not only a done-history log.
2. Every public changelog task must have an explicit status (allowed: `Planned`, `Done`).
3. Update an item in `CHANGELOG.json` to `Done` only after explicit user confirmation of completion.
4. Keep public changelog task wording human-readable and maintain stable task identity so status updates are deterministic.
5. When creating any new task in `dev/TASK_LIST.md`, add the corresponding task entry to `CHANGELOG.json` in the same edit run with status `Planned`.
6. When changing task text/scope/title/ID in `dev/TASK_LIST.md`, explicitly check whether the matching item in `CHANGELOG.json` must be updated; apply that changelog update in the same edit run when needed.
7. Never skip changelog synchronization for task create/update/complete actions; treat it as a mandatory blocking rule.
8. `CHANGELOG.json` task `id` must be exactly the task number from `dev/TASK_LIST.md` (for example: `1`, `30`, `45`, `8b`, `12a`, `16l`) and must not use text slugs.
9. Task-number identity is canonical: one task number in `dev/TASK_LIST.md` -> one entry with the same `id` in `CHANGELOG.json` (no duplicates, no aliases).
10. New tasks in `CHANGELOG.json` must be added only at the end of the `entries` array (append-only); do not insert/reorder by category or any other grouping.
11. New tasks in `dev/TASK_LIST.md` must be added only at the end of the file as a single linear list entry; do not place new tasks into category sections and do not regroup existing tasks by categories.
12. Every `CHANGELOG.json` entry must include both `date` (`YYYY-MM-DD`) and `time` (`HH:MM:SS`).
13. For newly created changelog entries, set `time` from the current local time at write moment (`time.now` semantics).
14. When bulk-updating existing entries with missing `time`, keep the current entry order unchanged and assign times in that same order (monotonic by entry sequence).

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
