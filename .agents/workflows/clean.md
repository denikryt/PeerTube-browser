---
description: Clean local plan and tracker artifacts for one feature or issue scope
---
1. Resolve the target entity in `dev/map/DEV_MAP.json`.
2. Build the cleanup preview for:
   - `dev/FEATURE_PLANS.md`
   - `dev/TASK_LIST.json`
   - `dev/ISSUE_OVERLAPS.json`
   - `dev/ISSUE_DEP_INDEX.json`
3. Run one canonical command:
   - `python3 dev/workflow clean issue --id <issue_id> [--write]`
   - `python3 dev/workflow clean feature --id <feature_id> [--write]`
4. `clean` is local only. It must not close or edit GitHub issues.
