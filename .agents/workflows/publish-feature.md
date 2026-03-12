---
description: Publish feature or issue GitHub state under the target-state workflow
---
1. Read `.agents/protocols/feature-planning-protocol.md` and `.agents/protocols/task-execution-protocol.md`.
2. Resolve the target feature or issue in `dev/map/DEV_MAP.json`.
3. Ensure the local plan and ownership fields are coherent before publishing.
4. Use:
   - `python3 dev/workflow publish feature --id <feature_id> [--write]`
   - `python3 dev/workflow publish issue --id <issue_id> [--write]`
   - `python3 dev/workflow publish issue --children-of <feature_id> [--write]`
5. Feature publication creates only the feature-level remote issue.
6. Child issue publication happens only from explicit issue publication scope over existing issue nodes.
7. `sync feature --all-children` and `sync issue --children-of <feature_id>` may update already published child issues, but they must not create new issues from local task decomposition implicitly.
