# Task Execution Protocol

This file defines execution-stage contracts and state-transition standards.
Hard constraints are defined in `.agents/rules/`.
Step-by-step command procedures are defined in `.agents/workflows/`.

## Scope ownership (canonical)

- This file owns **Execution Read Order**, **Execution Gates**, **Completion State-Transition Contracts**, and **Branch/Materialization Standards**.
- `.agents/rules/` owns **Hard Policy Constraints**, **Permission Gates**, and **Execution Trigger Rules**.
- `.agents/workflows/` owns **Actionable Procedures** and **CLI Command Sequences**.

If any procedural detail differs across docs, the corresponding `.agents/workflows/` file is canonical for steps, while this file is canonical for execution contracts and state-transition requirements.

## Section 1: Read order (mandatory)

1. Read in strict order before coding when executing a tracked task, issue, issue bundle, or feature:
   - exact task text in `dev/TASK_LIST.json`,
   - `dev/ISSUE_OVERLAPS.json`,
   - `dev/FEATURE_PLANS.md` (issue plan context),
   - `dev/map/DEV_MAP.json` context for the target task set and ownership markers,
   - this file (`.agents/protocols/task-execution-protocol.md`).

2. For direct user-requested local changes outside tracked workflow execution, read the relevant local code and configuration needed to make the change safely and coherently. Read tracking artifacts only if the requested change depends on tracked workflow state.

## Section 2: Execution standards

- **Mandatory Read Order**: Section 1 must be completed before implementation work begins within the applicable execution mode.
- **Materialization Gate**: execution is blocked until the parent execution container is materialized on GitHub for tracked task, issue, issue bundle, or feature execution.
- **Requirement Closure**: every stated requirement in the exact task text must be explicitly re-checked before reporting results for tracked execution.
- **Direct Request Closure**: for direct user-requested local changes, the agent must verify that the implemented result matches the explicit request before reporting results.
- **No Auto-Completion**: implementation completion and tracker completion are separate states; completion remains confirmation-gated.
- **Chain Execution Rule**: feature, issue, issues, and bundle execution must run sequentially in dependency order and stop on the first blocking failure.
- **Multi-Issue Package Rule**: `execute issues <issue_id>, <issue_id>, ...` means execute the listed issues as one package ordered by `issue_execution_order` in `dev/ISSUE_OVERLAPS.json`, restricted to the selected subset.

## Section 3: Execution gates

### Task / Issue / Feature execution

- Before `execute task <id>`, `execute issue <issue_id>`, `execute issues <issue_id>, <issue_id>, ...`, or `execute feature <feature_id>`, every parent `Issue` in scope must have non-null `gh_issue_number` and `gh_issue_url` in `dev/map/DEV_MAP.json`.

### Standalone execution

- Before executing a task attached to `StandaloneIssue`, the parent standalone issue must have non-null `gh_issue_number` and `gh_issue_url` in `dev/map/DEV_MAP.json`.

### Direct user-requested local changes

- Direct user-requested local changes do not require a tracked execution command unless the user explicitly asks to operate within tracked task, issue, or feature workflow scope.
- If a direct request would mutate tracked state, create, update, or complete tracker artifacts, or depend on workflow-governed lifecycle transitions, the corresponding workflow and rule set must still be followed.

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
- Materialization and sync workflows must return deterministic reconciliation output for branch linkage and missing issue mappings.

## Execution Triggers

Execution triggers are defined in `.agents/rules/execution-triggers.md`.

- Use tracked workflow commands when the user wants planning, tracked execution, confirmation, rejection, or other workflow-governed operations.
- Use direct user requests as valid execution triggers for ordinary local code, config, docs, or file changes unless blocked by a higher-priority rule.
