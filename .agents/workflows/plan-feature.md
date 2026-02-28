---
description: Generate or update a feature plan in FEATURE_PLANS.md
---
1. Read `dev/FEATURE_PLANNING_PROTOCOL.md` (Gate 0 and Gate A quality requirements).
2. Formulate dependencies: Identify task, feature, and issue dependencies required for this feature.
3. Formulate overlaps: Identify affected tasks in `dev/TASK_EXECUTION_PIPELINE.json`.
4. Formulate step flow: Create a strict command sequence defining what to run, script actions, executor actions, and expected step results.
5. Formulate assessment: Write an explicit `Issue/Task Decomposition Assessment` evaluating if splitting is necessary.
6. Only after completing the intellectual formulation, execute the CLI plan initialization.

// turbo
7. Run: `python3 dev/workflow feature plan-init --id <feature_id>`

8. Insert your drafted dependencies, decomposition flow, and assessment into `dev/FEATURE_PLANS.md` under the newly created block.
9. Validate structure:
// turbo
10. Run: `python3 dev/workflow feature plan-lint --id <feature_id>`
11. Stop execution and use `notify_user` with `BlockedOnUser=true` to wait for explicit approval (`approve feature plan`).
