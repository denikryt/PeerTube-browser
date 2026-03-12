---
description: Create or refine one feature plan section
---
1. Read `.agents/protocols/feature-planning-protocol.md`.
2. Resolve `<feature_id>` in `dev/map/DEV_MAP.json`.
3. Ensure the feature section exists in `dev/FEATURE_PLANS.md`.
4. Draft or update `### Expected Behaviour` for the feature and canonical issue plan blocks under it.
5. Ensure every planned feature and every planned issue has at least one local task in the plan text.
6. Run `python3 dev/workflow plan feature --id <feature_id> --write` when scaffolding or reconciling the feature section.
7. Run `python3 dev/workflow feature plan-lint --id <feature_id>`.
