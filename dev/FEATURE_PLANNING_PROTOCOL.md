# Feature Planning Protocol

This protocol defines mandatory planning gates before implementation starts.
`dev/map/DEV_MAP.json` is the planning source of truth.
Canonical structure and ID formats are defined in `dev/map/DEV_MAP_SCHEMA.md`.

## 1) Planning Input Contract

Required input for `plan feature <id>`:
- `feature_id`: stable feature id in schema format (for example `F1-M1`).
- `feature_title`: short title.
- `milestone_id`: target milestone (`M1..Mn`).
- `dependencies`: task/feature/issue dependencies.
- `overlaps`: affected tasks in `dev/TASK_EXECUTION_PIPELINE.md`.
- `step_flow`: strict command sequence with per-step actions (`what to run`, `what script does`, `what executor does`, `step result`).
- `issue_task_decomposition_assessment`: explicit assessment whether to split or not split; if split, minimal logical issues/tasks.

Required output:
- dependencies section for the feature,
- decomposition section with strict step-by-step flow,
- `Issue/Task Decomposition Assessment`,
- draft decomposition (`Feature -> Issue(s) -> Task(s)`) only if splitting is actually needed.

## 2) Decomposition Rules

- One feature maps to one primary feature issue (`type:feature`) on GitHub.
- Additional work issues (`type:work`) are allowed when scope is too large for one implementation thread.
- Tasks stay in `dev/TASK_LIST.md` and are not forced into 1-task-1-issue mapping.
- Every task must be attached to a parent chain in `dev/map/DEV_MAP.json`:
  `Milestone -> Feature -> Issue -> Task`.
  If parent nodes do not exist yet, create them first using `dev/map/DEV_MAP_SCHEMA.md`.
- Every task in `dev/TASK_LIST.md` must carry markers `[M*][F*]` that match `dev/map/DEV_MAP.json`.

## 3) Quality Gates

### Gate A: Pre-approve

Checklist:
- strict step flow exists and is executable,
- manual vs script responsibilities are explicit for each step,
- `Issue/Task Decomposition Assessment` exists,
- decomposition is minimal-sufficient (no unnecessary splitting).

### Gate B: Pre-materialize

- `approve feature plan` is required.
- No GitHub issue creation/update before approval.
- Materialized GitHub issues must be assigned to the target GitHub milestone.
- If target milestone is missing on GitHub, materialization is blocked until milestone is created/selected.

### Gate C: Pre-execute

Before `execute task X`:
- `dev/map/DEV_MAP.json` has feature/issue/task mapping,
- `dev/TASK_LIST.md` has synced tasks with `[M*][F*]`,
- `dev/TASK_EXECUTION_PIPELINE.md` has overlaps/dependencies for those tasks.

### Gate D: Pre-done

Before `confirm feature done`:
- mapped work issues are closed (or checklists are complete),
- mapped tasks are `Done` in `dev/map/DEV_MAP.json`,
- required validation checks from the approved plan/protocol are green.

## 4) Completion Semantics

- `confirm feature done`:
  allowed only when all mapped issues/tasks satisfy Gate D.
- `confirm milestone done`:
  allowed only when all milestone features in `dev/map/DEV_MAP.json` are `Done` (milestone completion is derived; no milestone `status` field is stored).

## 5) New Entity Creation Paths

### New task (no new feature)

Allowed direct path:
1. Add task under existing feature issue in `dev/map/DEV_MAP.json`.
2. Add/update task in `dev/TASK_LIST.md` with `[M*][F*]`.
3. Add/update overlaps in `dev/TASK_EXECUTION_PIPELINE.md`.

All three updates must be in one change set.

### New feature

Required command-gated path:
1. `create feature <id>`
2. `plan feature <id>`
3. `approve feature plan`
4. `materialize feature`
5. `sync issues to task list`

Only after step 5 is `execute task X` allowed.
