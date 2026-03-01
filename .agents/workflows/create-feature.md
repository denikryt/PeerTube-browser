---
description: Register a new feature in local and GitHub trackers
---
1. Initialization: Verify the provided feature ID and title against the format and policy defined in `.agents/rules/feature-planning.md`.
2. Formulate Details: Prepare the title and metadata for a feature-level GitHub issue.
3. Quality Standard: Ensure compliance with the **Feature planning/materialization flow** in `.agents/protocols/task-execution-protocol.md`.
4. Only after verifying rules and standards, execute the CLI registration command.

// turbo
5. Run: `python3 dev/workflow feature create --id <feature_id> --title "<feature_title>" --milestone <milestone_id>`
