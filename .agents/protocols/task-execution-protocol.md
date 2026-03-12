# Task Execution Protocol

This protocol defines target-state execution and completion contracts.

## Read order

Before implementing tracked work:

1. Read the exact target plan block in `dev/FEATURE_PLANS.md`.
2. Read overlap/dependency context from `dev/ISSUE_OVERLAPS.json`.
3. Read runtime ownership and mapping state from `dev/map/DEV_MAP.json`.
4. Read the relevant code, workflows, schemas, and tests touched by the planned change.

## Execution model

1. `execute feature <id>` and `execute issue <id>` are the canonical tracked execution scopes.
2. `Task` is a local decomposition unit inside the plan and does not require a separate tracked execution command.
3. Execution is blocked until the target `Feature` or `Issue` has GitHub publication metadata.
4. Execution must respect issue overlap order where applicable.

## Completion model

1. Completion remains explicit and user-driven.
2. The canonical completion command is `done feature <id>` or `done issue <id>`.
3. `done` updates local state to `Done`.
4. `done feature <id> --cascade` is the explicit mode for marking child issues `Done` together with the feature; add `--remote` only when remote child issue closure is also intended.
4. Remote close/sync must only happen when `--remote` is explicitly provided.

## Publication and branch policy

1. Canonical feature branch naming remains `feature/<feature_id>`.
2. Feature publication owns the feature-level remote issue and branch linkage.
3. Issue publication owns child or standalone issue publication.
4. Child sync may update already published issue state, but task decomposition must not create GitHub issues implicitly.
