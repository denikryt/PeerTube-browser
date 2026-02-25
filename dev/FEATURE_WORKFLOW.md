# Feature Workflow Playbook

Compact command index for milestone/feature operations.

## Scope ownership

- This file is an index only.
- Canonical command semantics/order are defined in `dev/TASK_EXECUTION_PROTOCOL.md`.
- Planning-only quality requirements are defined in `dev/FEATURE_PLANNING_PROTOCOL.md`.
- Hard policy constraints are defined in `AGENTS.md`.

## Canonical command sequence (feature path)

1. `create feature <id>`
2. `plan feature <id>`
3. `approve feature plan`
4. `sync issues to task list for <id>`
5. review/refine local decomposition with user
6. `materialize feature <id> --mode bootstrap`
7. `materialize feature <id> --mode issues-create` or `materialize feature <id> --mode issues-sync`
8. `execute task X` or `execute issue <issue_id>` or `execute feature <feature_id>`
9. `confirm task <task_id> done` / `confirm issue <issue_id> done` / `confirm feature <feature_id> done`
10. `confirm milestone done`

## Canonical command sequence (standalone path)

1. `create standalone-issue <id>`
2. `plan standalone-issue <id>`
3. `approve standalone-issue plan`
4. `sync standalone-issue to task list`
5. review/refine local decomposition with user
6. `materialize standalone-issue`
7. `execute task X`
8. `confirm standalone-issue <si_id> done`

## Command index

- `create feature <id>`
  - Purpose: register feature node and feature-level tracker linkage.
  - Canonical contract: `dev/TASK_EXECUTION_PROTOCOL.md` -> `Feature planning/materialization flow`.
- `plan feature <id>`
  - Purpose: produce feature plan artifacts in `dev/FEATURE_PLANS.md`.
  - Canonical planning requirements: `dev/FEATURE_PLANNING_PROTOCOL.md` -> `Planning Input Contract` + `Planning Quality Gates`.
- `approve feature plan`
  - Purpose: approve plan boundaries and unlock sync/materialize path.
  - Canonical contract: `dev/TASK_EXECUTION_PROTOCOL.md` -> `Feature planning/materialization flow`.
- `sync issues to task list for <id>`
  - Purpose: sync local `Issue -> Task` decomposition across `DEV_MAP`/`TASK_LIST`/`PIPELINE`.
  - Canonical contract: `dev/TASK_EXECUTION_PROTOCOL.md` -> `Feature planning/materialization flow`.
- `feature execution-plan --id <feature_id>`
  - Purpose: return pending task order and include the next issue from `Issue Execution Order` in `FEATURE_PLANS`.
  - Canonical contract: `dev/TASK_EXECUTION_PROTOCOL.md` -> `Feature planning/materialization flow`.
- `materialize feature <id> --mode <bootstrap|issues-create|issues-sync>`
  - Purpose: run explicit materialization mode (bootstrap branch context, create flow, or sync flow) for already-synced local issue nodes.
  - Canonical contract: `dev/TASK_EXECUTION_PROTOCOL.md` -> `Feature planning/materialization flow`.
- `execute task X` / `execute issue <issue_id>` / `execute feature <feature_id>`
  - Purpose: run implementation flow for one task, one issue chain, or full feature chain.
  - Canonical contract: `dev/TASK_EXECUTION_PROTOCOL.md` -> `Standard execution flow` + `Issue chain execution flow` + `Feature chain execution flow`.
- `confirm ... done`
  - Purpose: apply completion updates after explicit user confirmation.
  - Canonical contract: `dev/TASK_EXECUTION_PROTOCOL.md` -> `Completion flow`.

This file must not contain duplicated normative procedure text owned by canonical protocol files.
