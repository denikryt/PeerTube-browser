---
description: Run explicit materialization mode or sync GitHub issues
---
1. Pre-Check: Read the local decomposition state and verify compliance with **Gate C: Pre-materialize** in `.agents/protocols/feature-planning-protocol.md`. 
2. Branch Policy Enforcement: Resolve branch naming from **Section 6, Branch policy** in `.agents/protocols/task-execution-protocol.md`.
3. GitHub Policy Enforcement: Follow the body sync and boilerplate rules defined in the materialization section of `.agents/protocols/task-execution-protocol.md`.
4. Only after confirming prerequisites and strict sync rules, execute the materialization script.

// turbo
5. Run: `python3 dev/workflow feature materialize --id <feature_id> --mode <mode> [--issue-id <issue_id> ...]`

6. Post-Check: Return the deterministic reconcile output regarding missing mappings and branch linkage explicitly to the user.
