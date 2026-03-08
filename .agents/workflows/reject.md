---
description: Reject mapped/unmapped issues or full feature subtrees and clean up artifacts
---
1. Identify the target to reject (`issue` or `feature`).
2. Execute the CLI command to reject the target and clean up artifacts.

// turbo
3. Issue reject: `python3 dev/workflow reject issue --id <issue_id>`
4. Feature reject: `python3 dev/workflow reject feature --id <feature_id>`
5. Output results and explicitly list missing fields for any unmapped issue nodes in the rejection payload.
