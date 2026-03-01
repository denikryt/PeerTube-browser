---
description: Persist local Issue -> Task decomposition across trackers
---
1. Analyze existing bindings: Review `dev/map/DEV_MAP.json` to prepare candidate targets for tasks.
2. Formulate Task Scopes: For each issue, define minimal-sufficient task scopes including mandatory `concrete_steps` fields with explicit numbered actions.
3. Ensure task marker correctness: Formulate `[M*][F*]` or `[M*][SI*]` strings for tasks based on their parent chain.
4. Check overlaps: Ascertain target task priority and ordering within `dev/TASK_EXECUTION_PIPELINE.json`. Note that this command **is the owner** of `dev/TASK_EXECUTION_PIPELINE.json` updates and tracker synchronization.
5. Only after task decomposition is completely mapped out conceptually, utilize the CLI to synchronize everything.

// turbo
6. Run: `python3 dev/workflow plan tasks --feature-id <feature_id>` OR `python3 dev/workflow plan tasks --issue-id <issue_id> ...`

7. Review the synced tasks in `dev/TASK_LIST.json` to ensure `concrete_steps` and markers were applied correctly.
8. Stop and use `notify_user` with `BlockedOnUser=true` to await explicitly synced local decomposition review.
