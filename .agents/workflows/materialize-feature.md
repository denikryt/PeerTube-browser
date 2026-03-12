---
description: Materialize feature or issue GitHub state under the target-state workflow
---
1. Read `.agents/protocols/feature-planning-protocol.md` and `.agents/protocols/task-execution-protocol.md`.
2. Resolve the target feature or issue in `dev/map/DEV_MAP.json`.
3. Ensure the local plan and ownership fields are coherent before publishing.
4. Use:
   - `python3 dev/workflow materialize feature --id <feature_id> --mode <create|sync> [--write]`
   - `python3 dev/workflow materialize issue --feature-id <feature_id> --mode <create|sync> [--write]`
   - `python3 dev/workflow materialize issue --id <issue_id> --mode <create|sync> [--write]`
5. Feature materialization creates or syncs only the feature-level remote issue.
6. Child issue publication happens only from explicit issue materialization scope.
7. `sync all children` may update already materialized child issues, but it must not create new issues from local task decomposition implicitly.
