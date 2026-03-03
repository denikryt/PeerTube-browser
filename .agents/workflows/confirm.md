---
description: Apply completion updates after explicit user confirmation
---
1. Verification: Read the completed work and verify it meets all task requirements.
2. Canonical Sequence: Apply completion updates according to `.agents/protocols/task-execution-protocol.md` (Section 4: Completion state-transition contract) in one edit run.
   - Note: Do NOT mutate GitHub issue checklists; status is tracked by local status and issue close flow.
3. Only after the intellectual update is formulated, execute the CLI confirm command.

// turbo
3. Run: `python3 dev/workflow confirm <target_type> --id <id> [additional_args]`
   - Task: `python3 dev/workflow confirm task --id <task_id>`
   - Issue: `python3 dev/workflow confirm issue --id <issue_id>`
   - Feature: `python3 dev/workflow confirm feature --id <feature_id>`
   - Standalone: `python3 dev/workflow confirm standalone-issue --id <si_id>`
4. Confirm completion and output the final result.
