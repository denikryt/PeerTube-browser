# Feature Workflow Playbook

Operational command flow for milestone/feature execution.

## Command Sequence

1. `create feature <id>`
2. `plan feature <id>`
3. `approve feature plan`
4. `materialize feature`
5. `sync issues to task list`
6. `execute task X`
7. `confirm feature done`
8. `confirm milestone done`

## Command Contracts

## 1) `create feature <id>`

Purpose:
- register a new feature node in `dev/map/DEV_MAP.json` under a milestone.

Required updates:
- `dev/map/DEV_MAP.json`: add feature with status `Planned`, empty issue/task decomposition or draft issue node.
- feature/issue IDs must follow `dev/map/DEV_MAP_SCHEMA.md`.

Validation before next step:
- feature id is unique,
- milestone id exists,
- status is `Planned`.

## 2) `plan feature <id>`

Purpose:
- produce approved-ready decomposition and acceptance plan.

Required updates:
- `dev/FEATURE_PLANNING_PROTOCOL.md`: planning artifacts reference/checklist entry (if needed).
- `dev/map/DEV_MAP.json`: draft issue/task nodes under the feature (status `Planned`).

Validation before next step:
- scope/out-of-scope is explicit,
- acceptance criteria is measurable,
- risks/dependencies are listed.

## 3) `approve feature plan`

Purpose:
- lock scope and decomposition boundaries.

Required updates:
- `dev/map/DEV_MAP.json`: set target feature `status` to `Approved`.

Validation before next step:
- no open planning gaps from protocol gates.

## 4) `materialize feature`

Purpose:
- create/update GitHub feature/work issues and persist external references.

Required updates:
- GitHub milestone/issue state,
- `dev/map/DEV_MAP.json`: write `gh_issue_number` and `gh_issue_url` for feature/work nodes.
 - each materialized GitHub issue must have the corresponding GitHub milestone assigned.

Validation before next step:
- links exist and point to correct repo/milestone,
- no orphan issue node without parent feature.
 - milestone assignment is present on all created/updated issues (not label-only).

## 5) `sync issues to task list`

Purpose:
- synchronize executable tasks and overlap metadata.

Precondition:
- target feature `status` in `dev/map/DEV_MAP.json` is `Approved`.

Required updates:
- `dev/TASK_LIST.md`: add/update tasks with `[M*][F*]` markers,
- `dev/TASK_EXECUTION_PIPELINE.md`: add/update overlaps/dependencies for synced tasks,
- `dev/map/DEV_MAP.json`: task nodes match current task list ids/titles.

Validation before next step:
- every mapped task exists in both `dev/map/DEV_MAP.json` and `dev/TASK_LIST.md`,
- pipeline overlap entries exist for new/changed tasks.

## 6) `execute task X`

Purpose:
- implementation run for one task.

Preconditions:
- steps 1-5 complete for the parent feature,
- task is linked in `dev/map/DEV_MAP.json` and has `[M*][F*]` in `dev/TASK_LIST.md`.

Required updates:
- implementation files for task X,
- status updates stay `Planned` until user confirms done.

## 7) `confirm feature done`

Purpose:
- close feature after review.

Required updates:
- `dev/map/DEV_MAP.json`: feature/issues/tasks set to `Done`,
- related status updates remain in `dev/map/DEV_MAP.json` as source of truth.

Validation before next step:
- all mapped tasks are `Done`,
- mapped work issues are closed (or completed checklist).

## 8) `confirm milestone done`

Purpose:
- close milestone after all features are done.

Required updates:
- no milestone status write (milestone has no `status` field).
- completion is validated from feature statuses under that milestone.

Validation:
- all milestone features are `Done`.
