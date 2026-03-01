description: Generate or update a feature plan in FEATURE_PLANS.md for a given <feature_id>
---
> [!NOTE]
> This is a **planning-only** command. It does NOT write to or modify `dev/TASK_EXECUTION_PIPELINE.json`.

1. Read `.agents/protocols/feature-planning-protocol.md` (Gate 0 and Gate A quality requirements).
2. Formulate dependencies: Identify task, feature, and issue dependencies required for the feature specified by `<feature_id>`.
3. Formulate overlaps (Drafting): Identify affected tasks in `dev/TASK_EXECUTION_PIPELINE.json` for **documentation purposes in `FEATURE_PLANS.md` only**. This command does not modify the pipeline.
4. Formulate step flow: Create a strict command sequence defining what to run, script actions, executor actions, and expected step results.
5. Formulate assessment: Evaluate the feature's issue/task decomposition against Section 2 (Decomposition Rules) of `.agents/protocols/feature-planning-protocol.md`. Verify the decomposition meets the standards for Adequacy, Realism, Practicality, and Sequence.
6. Verify quality: Ensure the formulated plan meets the "Gate A: Pre-decomposition review" checklist in `.agents/protocols/feature-planning-protocol.md`.
7. Only after completing the intellectual formulation and quality check, execute the CLI plan initialization.

// turbo
7. Run: `python3 dev/workflow feature plan-init --id <feature_id>`

8. Insert your drafted dependencies, decomposition flow, and assessment into `dev/FEATURE_PLANS.md` under the newly created block.
9. Validate structure:
// turbo
10. Run: `python3 dev/workflow feature plan-lint --id <feature_id>`
11. Stop execution and use `notify_user` with `BlockedOnUser=true` to wait for explicit approval (`approve feature plan`).
