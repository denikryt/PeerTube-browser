---
description: Produce or update an issue-level plan block in FEATURE_PLANS.md
---
1. Read the target `<issue_id>` and resolve its parent feature in `dev/map/DEV_MAP.json`.
2. Formulate dependencies specifically for this issue context.
3. Formulate decomposition: Create a strict issue-level implementation flow with numbered top-level steps and concrete sub-points specifying input/output contracts and expected results.
4. Formulate assessment: Write an explicit `Issue/Task Decomposition Assessment` for this issue (pre-task vs tasked state).
5. Only after formulating the plan, execute the CLI issue initialization.

// turbo
6. Run: `python3 dev/workflow feature plan-issue --id <issue_id> [--title <optional_title>]`

7. Update `dev/FEATURE_PLANS.md` by inserting your drafted plan into the generated issue block. Do NOT mutate `Issue Execution Order` or parent feature sections.
8. Stop and wait for user review using `notify_user` with `BlockedOnUser=true`.
