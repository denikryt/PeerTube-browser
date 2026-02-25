# Feature Planning Protocol

This protocol defines planning-only requirements before implementation starts.
`dev/map/DEV_MAP.json` is the planning source of truth.
Canonical structure and ID formats are defined in `dev/map/DEV_MAP_SCHEMA.md`.

## Scope ownership

- This file owns planning artifacts and planning quality gates only.
- Command semantics/order (`create/plan/plan issue/plan tasks for/materialize/execute/confirm`) are owned by `dev/TASK_EXECUTION_PROTOCOL.md`.
- Hard constraints are owned by `AGENTS.md`.

## 1) Planning Input Contract

Required input for `plan feature <id>`:
- `feature_id`: stable feature id in schema format (for example `F1-M1`).
- `feature_title`: short title.
- `milestone_id`: target milestone (`M1..Mn`).
- `dependencies`: task/feature/issue dependencies.
- `overlaps`: affected tasks in `dev/TASK_EXECUTION_PIPELINE.json`.
- `step_flow`: strict command sequence with per-step actions (`what to run`, `what script does`, `what executor does`, `step result`).
- `issue_task_decomposition_assessment`: explicit assessment whether to split or not split; if split, minimal logical issues/tasks.

Required input for `plan issue <issue_id>`:
- `issue_id`: stable issue id in schema format (for example `I16-F4-M1`).
- `parent_feature_id`: resolved owner feature id from `DEV_MAP`.
- `dependencies`: issue-specific dependencies.
- `step_flow`: strict issue-level implementation flow (ordered actions and expected result per step).
- `issue_task_decomposition_assessment`: explicit minimal-sufficient split decision for this issue.

Required output in `dev/FEATURE_PLANS.md`:
- dependencies section for the feature,
- decomposition section with strict step-by-step flow,
- `Issue Execution Order` block with ordered active issue rows (``<issue_id>`` - `<issue_title>`),
- `Issue/Task Decomposition Assessment`,
- draft decomposition (`Feature -> Issue(s) -> Task(s)`) only if splitting is actually needed.

Required output for `plan issue <issue_id>` in `dev/FEATURE_PLANS.md`:
- output must be persisted through `feature plan-issue --id <issue_id>` (no chat-only issue plan updates),
- exactly one canonical issue-plan block under the parent feature section for the target issue id,
  - heading format: `### <issue_id> - <issue_title>` (one issue per block),
  - only `####` headings are allowed inside that block.
- mandatory issue-specific `#### Dependencies`,
- mandatory issue-specific `#### Decomposition` with strict step flow,
- mandatory issue-specific `#### Issue/Task Decomposition Assessment`,
- `Issue Execution Order` is read-only for `plan-issue`; active issue row for the target issue must already exist.

## 2) Decomposition Rules

- One feature maps to one primary feature issue (`type:feature`) on GitHub.
- Additional work issues (`type:work`) are allowed when scope is too large for one implementation thread.
- Tasks stay in `dev/TASK_LIST.json` and are not forced into 1-task-1-issue mapping.
- Every task must be attached to a parent chain in `dev/map/DEV_MAP.json`:
  `Milestone -> Feature -> Issue -> Task`.
  If parent nodes do not exist yet, create them first using `dev/map/DEV_MAP_SCHEMA.md`.
- Every task in `dev/TASK_LIST.json` must carry markers `[M*][F*]` that match `dev/map/DEV_MAP.json`.

## 3) Planning Quality Gates

### Gate 0: Plan Detail and Formatting Standard (mandatory for all new/updated plans)

Checklist:
- `#### Decomposition` uses numbered top-level steps (`1.`, `2.`, ...) and each step has concrete sub-points with implementation actions.
- Every decomposition step states expected result/output (not only action wording).
- For CLI/automation changes, decomposition explicitly includes:
  - input contract,
  - output contract,
  - failure-path behavior,
  - idempotency/stability behavior.
- `#### Issue/Task Decomposition Assessment` includes:
  - explicit `task_count`,
  - per-task scope,
  - concrete file/module targets,
  - acceptance checks per task.
- Avoid generic wording (`improve`, `enhance`, `refine`) without concrete mechanism, files, or validation criteria.

### Gate A: Pre-decomposition review

Checklist:
- strict step flow exists and is executable,
- manual vs script responsibilities are explicit for each step,
- `Issue/Task Decomposition Assessment` exists,
- decomposition is minimal-sufficient (no unnecessary splitting).

### Gate B: Pre-sync (local decomposition)

Checklist:
- target feature plan is lint-clean and reviewed,
- target issue nodes are not `Pending` (pending issues must be planned first via `plan issue <issue_id>`),
- decomposition is represented as local `Issue -> Task` structure,
- planned task markers/ownership are consistent with `DEV_MAP` parent chain,
- decomposition scope is minimal and executable,
- successful decomposition is expected to transition selected issues to `Tasked`.

### Gate C: Pre-materialize

Checklist:
- local decomposition has been synced and reviewed,
- selected unmapped issue nodes for `issues-create`/`issues-sync` have status `Tasked` (mapped issues may be updated in `issues-sync` regardless of status),
- GitHub materialization uses only already-defined local issue nodes,
- every created/updated GitHub issue is assigned to the target milestone,
- milestone resolution is confirmed before issuing materialization actions.

## 4) Execution Procedure References

Use canonical execution sections from `dev/TASK_EXECUTION_PROTOCOL.md`:
- `Feature planning/materialization flow` for command order and command contracts.
- `Standalone issue flow` for non-product work.
- `Completion flow` for `confirm ... done` semantics.
- `New/edited task update flow` for task allocation/sync procedure.

This file must not duplicate those execution procedures.
