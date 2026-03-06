# Task Execution Protocol

This file defines execution-stage contracts and state-transition standards.
Hard constraints are defined in `.agents/rules/`.
Step-by-step command procedures are defined in `.agents/workflows/`.

## Scope ownership (canonical)

- This file owns **Execution Read Order**, **Execution Gates**, **Completion State-Transition Contracts**, and **Branch/Materialization Standards**.
- `.agents/rules/` owns **Hard Policy Constraints** and **Permission Gates**.
- `.agents/workflows/` owns **Actionable Procedures** and **CLI Command Sequences**.

If any procedural detail differs across docs, the corresponding `.agents/workflows/` file is canonical for steps, while this file is canonical for execution contracts and state-transition requirements.

## Section 1: Read order (mandatory)

1. Read in strict order before coding:
   - exact task text in `dev/TASK_LIST.json`,
   - `dev/ISSUE_OVERLAPS.json`,
   - `dev/FEATURE_PLANS.md` (issue execution order / issue plan context),
   - `dev/map/DEV_MAP.json` context for the target task set and ownership markers,
   - this file (`.agents/protocols/task-execution-protocol.md`).

## Section 2: Execution standards

- **Mandatory Read Order**: Section 1 must be completed before any implementation work.
- **Materialization Gate**: execution is blocked until the parent execution container is materialized on GitHub.
- **Requirement Closure**: every stated requirement in the exact task text must be explicitly re-checked before reporting results.
- **No Auto-Completion**: implementation completion and tracker completion are separate states; completion remains confirmation-gated.
- **Chain Execution Rule**: feature/issue/bundle execution must run sequentially in dependency order and stop on the first blocking failure.

## Section 3: Execution gates

### Task / Issue / Feature execution

- Before `execute task <id>`, `execute issue <issue_id>`, or `execute feature <feature_id>`, every parent `Issue` in scope must have non-null `gh_issue_number` and `gh_issue_url` in `dev/map/DEV_MAP.json`.

### Standalone execution

- Before executing a task attached to `StandaloneIssue`, the parent standalone issue must have non-null `gh_issue_number` and `gh_issue_url` in `dev/map/DEV_MAP.json`.

## Section 4: Completion state-transition contract

- Completion updates are allowed only after explicit user confirmation.
- Completion updates must be applied in one edit run across all affected tracking artifacts.
- `confirm issue <issue_id> done` may require additional explicit confirmation before cascading unfinished child tasks to `Done`.
- `confirm feature <feature_id> done` is treated as explicit confirmation for the full feature subtree.
- `confirm standalone-issue <si_id> done` requires all mapped child tasks to already be confirmed done.
- `reject issue <issue_id>` uses materialization-aware behavior:
  - mapped issue: keep local node and transition status to `Rejected`,
  - unmapped issue: remove the local issue node from its owner chain.
- Completion and rejection flows must not mutate GitHub checklist rows; status is tracked by local state and issue close flow.

## Section 5: Branch and materialization standards

- Canonical feature branch naming is `feature/<feature_id>`.
- Do not create duplicate branches for the same feature id.
- Default branch model is one branch per feature; issue-level branches require explicit user request.
- Persist branch linkage on the target feature node in `dev/map/DEV_MAP.json`:
  - `branch_name = feature/<feature_id>`,
  - `branch_url = <repo_url>/tree/feature/<feature_id>` or `null` if the repository URL cannot be resolved.
- Materialization/sync workflows must return deterministic reconciliation output for branch linkage and missing issue mappings.

## Execution Command Format

Mandatory execution trigger formats are defined in `.agents/rules/execution-triggers.md`.
