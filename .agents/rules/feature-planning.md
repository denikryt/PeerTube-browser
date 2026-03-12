---
trigger: always_on
glob:
description: Feature and issue planning policy
---

## Canonical entity model

1. `Feature` and `Issue` are the only GitHub-tracked runtime entities.
2. `Task` is local decomposition only and lives in `dev/FEATURE_PLANS.md`.
3. Runtime ownership is explicit:
   - `Feature` stores `milestone_id`
   - `Issue` stores `feature_id` and `milestone_id`
4. Stable local identity must not be derived from current owner placement. Ownership fields carry current placement.

## Lifecycle policy

1. Target-state lifecycle is `Pending -> Draft -> Planned -> Done`.
2. Legacy statuses such as `Approved`, `Tasked`, and `Rejected` may still appear in old nodes until they are rewritten or retired, but they are not target-state planning guidance.
3. Do not mark local state `Done` or close remote issues until the user explicitly requests completion.

## Planning policy

1. `plan feature <id>` and `plan issue <id>` are the canonical planning commands.
2. `plan tasks for ...` is not part of the target-state planning surface.
3. Every planned `Feature` must have at least one local `Task` in its plan.
4. Every planned `Issue` must have at least one local `Task` in its plan.
5. Task decomposition must be authored directly in `dev/FEATURE_PLANS.md`, not as runtime-owned task nodes in `dev/map/DEV_MAP.json`.
6. Dependencies and overlap records must still be justified by real shared code surfaces or dependency chains.

## Materialization and execution policy

1. `Feature` and `Issue` must be GitHub-tracked before tracked execution starts.
2. `publish/materialize feature` creates or syncs only the feature-level remote issue.
3. Child issue creation or sync happens only from explicit issue materialization scope.
4. `sync all children` may update already materialized child issues, but it must not silently create new child issues from local task decomposition.

## Tracker policy

1. `dev/map/DEV_MAP.json` remains the local runtime tracker for `Feature` and `Issue`.
2. `Task` does not need runtime ownership in `DEV_MAP`.
3. Local tracker changes and canonical docs must stay aligned in the same change set whenever lifecycle or command contracts are rewritten.
