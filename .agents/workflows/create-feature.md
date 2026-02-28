---
description: Register a new feature in local and GitHub trackers
---
1. Initialization: Read the provided feature ID and verify its format against `dev/map/DEV_MAP_SCHEMA.md`.
2. Formulate Issue Details: Prepare the title and metadata for a feature-level GitHub issue.
3. Registration Boundary: Ensure no planning or materialization steps are combined with this creation process.
4. Only after verifying formatting rules, execute the CLI registration command.

// turbo
5. Run: `python3 dev/workflow feature create --id <feature_id> --title "<feature_title>" --milestone <milestone_id>`
