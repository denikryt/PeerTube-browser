---
trigger: always_on
glob:
description: Mandatory pre-task and implementation constraints
---

## Mandatory pre-task checks

Before implementing any task or task bundle, always follow the mandatory pre-task checks defined in Section 1 of `.agents/protocols/task-execution-protocol.md`.

## Implementation requirements

1. Implement shared primitives first when tasks overlap.
2. Avoid duplicate logic across parallel modules.
3. Avoid local one-off implementations that would force duplicate rewrites in upcoming related tasks.
4. Run one integration pass for the whole task bundle or multi-task execution run.
5. Never skip changelog synchronization for task create/update/complete actions; treat it as a mandatory blocking rule.
6. New tasks in `CHANGELOG.json` must be added only at the end of the `entries` array (append-only for new items). Status updates (e.g., `Planned` -> `Done`) must be performed in-place.
7. New tasks in `dev/TASK_LIST.json` must be added only at the end of the file as a single linear list entry.

