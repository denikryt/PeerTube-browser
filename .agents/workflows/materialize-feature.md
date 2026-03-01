---
description: Run explicit materialization mode or sync GitHub issues
---
1. Pre-Check: Read the local decomposition state and verify that selected unmapped issue nodes have a status of `Tasked`.
2. Branch Policy Enforcement: Resolve the canonical feature branch format (e.g., `feature/<feature_id>`) from `.agents/protocols/task-execution-protocol.md`.
3. GitHub Policy Enforcement: Ensure that the intended GitHub issue body will NOT include local process/protocol boilerplate instructions (like "Work issue for").
4. Only after confirming prerequisites and strict sync rules, execute the materialization script.

// turbo
5. Run: `python3 dev/workflow feature materialize --id <feature_id> --mode <mode> [--issue-id <issue_id> ...]`

6. Post-Check: Return the deterministic reconcile output regarding missing mappings and branch linkage explicitly to the user.
