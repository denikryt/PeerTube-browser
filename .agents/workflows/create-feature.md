---
description: Register a new feature in local and GitHub trackers
---
1. Initialization: Verify the provided feature ID and mandatory milestone against the format and policy defined in `.agents/rules/feature-planning.md`.
2. Formulate Details: Prepare the title, description, and metadata for a feature-level GitHub issue.
   - If the user did not provide feature title and/or description explicitly, derive them from the current request context and nearby discussion.
   - Do not block on missing title/description when the intended scope is clear enough to formulate them safely.
   - Keep milestone input mandatory; do not infer or auto-select milestone without explicit user direction.
3. Quality Standard: Ensure compliance with `.agents/rules/feature-planning.md`, especially milestone assignment, registration-only behavior, and materialization prerequisites.
4. Only after verifying rules and standards, execute the CLI registration command.

// turbo
5. Run: `python3 dev/workflow feature create --id <feature_id> --title "<feature_title>" [--description "<feature_description>"] --milestone <milestone_id>`
