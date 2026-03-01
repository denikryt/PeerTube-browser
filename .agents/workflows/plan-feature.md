description: Generate or update a feature plan in FEATURE_PLANS.md for a given <feature_id>
---
> [!NOTE]
> This is a **planning-only** command. It does NOT write to or modify `dev/TASK_EXECUTION_PIPELINE.json`.

1. Read `.agents/protocols/feature-planning-protocol.md` (Gate 0 and Gate A quality requirements).
2. Formulate dependencies: Identify task, feature, and issue dependencies required for the feature specified by `<feature_id>`.
3. Formulate overlaps: Identify affected tasks in `dev/TASK_EXECUTION_PIPELINE.json` (for documentation in `FEATURE_PLANS.md` only).
4. Formulate step flow: Create a strict command sequence defining what to run, script actions, executor actions, and expected step results.
5. Formulate assessment: Evaluate the feature's issue/task decomposition against Section 2 (Decomposition Rules) of `.agents/protocols/feature-planning-protocol.md`. Ensure existing issues in `dev/map/DEV_MAP.json` are prioritized; if new issues are needed, verify they meet the criteria for adequacy, realism, practicality, and sequence.
6. Only after completing the intellectual formulation, execute the CLI plan initialization.

// turbo
7. Run: `python3 dev/workflow feature plan-init --id <feature_id>`

8. Insert your drafted dependencies, decomposition flow, and assessment into `dev/FEATURE_PLANS.md` under the newly created block.
9. Validate structure:
// turbo
10. Run: `python3 dev/workflow feature plan-lint --id <feature_id>`
11. Stop execution and use `notify_user` with `BlockedOnUser=true` to wait for explicit approval (`approve feature plan`).
