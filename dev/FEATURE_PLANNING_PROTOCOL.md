# Feature Planning Protocol

This protocol defines mandatory planning gates before implementation starts.
`dev/map/DEV_MAP.json` is the planning source of truth.
Canonical structure and ID formats are defined in `dev/map/DEV_MAP_SCHEMA.md`.

## 1) Planning Input Contract

Required input for `plan feature <id>`:
- `feature_id`: stable feature id in schema format (for example `F1-M1`).
- `feature_title`: short title.
- `milestone_id`: target milestone (`M1..Mn`).
- `scope`: in-scope behavior and boundaries.
- `out_of_scope`: explicitly excluded behavior.
- `dependencies`: task/feature/issue dependencies.
- `overlaps`: affected tasks in `dev/TASK_EXECUTION_PIPELINE.md`.

Required output:
- draft decomposition (`Feature -> Issue(s) -> Task(s)`),
- acceptance criteria,
- risk list,
- validation strategy,
- rollback notes.

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
- scope and out-of-scope are explicit,
- decomposition exists,
- acceptance criteria are measurable,
- risks and rollback are defined.

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
- acceptance criteria validation is green.

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
