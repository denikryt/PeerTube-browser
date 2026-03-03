---
description: Run explicit feature-level or issue-level GitHub materialization
---
1. Pre-Check: Read the local decomposition state and verify compliance with **Gate C: Pre-materialize** in `.agents/protocols/feature-planning-protocol.md`. 
2. Branch Policy Enforcement: Resolve branch naming from `.agents/protocols/task-execution-protocol.md` (Section 5: Branch and materialization standards).
3. GitHub Policy Enforcement: Follow the milestone/body policy defined in `.agents/rules/feature-planning.md` and the branch/materialization standards in `.agents/protocols/task-execution-protocol.md`.
4. Only after confirming prerequisites and strict sync rules, execute the materialization script.

// turbo
5. Run one canonical action-first materialize command:
   - feature-level issue: `python3 dev/workflow materialize feature --id <feature_id> --mode <create|sync>`
   - child issue set: `python3 dev/workflow materialize issue --feature-id <feature_id> --mode <create|sync> [--issue-id <issue_id> ...]`
   - single child issue: `python3 dev/workflow materialize issue --id <issue_id> --mode <create|sync>`

6. Post-Check: Return the deterministic reconcile output regarding missing mappings and branch linkage explicitly to the user.
