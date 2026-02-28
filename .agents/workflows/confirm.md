---
description: Apply completion updates after explicit user confirmation
---
1. Ascertain the target of the `confirm` command.
2. Execute the CLI command to apply completion updates across trackers.

// turbo
3. Run: `python3 dev/workflow confirm <target_type> --id <id> [additional_args]`
   - Task: `python3 dev/workflow confirm task --id <task_id>`
   - Issue: `python3 dev/workflow confirm issue --id <issue_id>`
   - Feature: `python3 dev/workflow confirm feature --id <feature_id>`
   - Standalone: `python3 dev/workflow confirm standalone-issue --id <si_id>`
4. Confirm completion and output the final result.
