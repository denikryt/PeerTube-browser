---
trigger: always_on
glob: "dev/TASK_EXECUTION_PIPELINE.json"
description: Rules for execution pipeline maintenance
---

## Pipeline entry constraints

1. `dev/TASK_EXECUTION_PIPELINE.json` must contain only pending (not completed) tasks/blocks; do not keep completed entries there with markers like `(completed)`.
2. In `dev/TASK_EXECUTION_PIPELINE.json` `functional_blocks`, always include an explicit `outcome` field for each block.
3. Each block `outcome` must be concrete and feature-level: describe what exact behaviors/features/API modes/operational flows will exist after the block is done.
4. Avoid generic wording in block outcomes (for example "better", "improved", "more stable") unless tied to specific mechanisms or user-visible changes.
