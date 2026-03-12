---
description: Create or refine one issue plan block
---
1. Read `.agents/protocols/feature-planning-protocol.md`.
2. Resolve `<issue_id>` and its owner feature in `dev/map/DEV_MAP.json`.
3. Draft or update the canonical block:
   - `### <issue_id> - <issue_title>`
   - `#### Expected Behaviour`
   - `#### Dependencies`
   - `#### Decomposition`
   - `#### Issue/Task Decomposition Assessment`
4. Ensure the issue block contains at least one local task in plan text and concrete dependency surfaces.
5. Run `python3 dev/workflow plan issue --id <issue_id> --write --strict`.
6. Run `python3 dev/workflow feature plan-lint --id <feature_id>`.
