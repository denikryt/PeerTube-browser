---
trigger: always_on
glob:
description: Strict execution triggers for agent tasks
---

1. Do not start implementing any task until the user gives an explicit execution command in this exact format: `выполни задачу X`.
2. Any message that does not contain an explicit command in the format `выполни задачу X` is treated as non-execution (clarification, planning, edits of task text, review, or discussion only).
3. If the user intent looks like execution but the command format is not explicit, ask for a direct command in the required format and do not start implementation.
4. User confirmation that a task is completed is separate from execution start and must still be explicit.
5. On every explicit execution command `выполни задачу X`, first re-read in this order: task `X` in `dev/TASK_LIST.json` -> `dev/TASK_EXECUTION_PIPELINE.json` -> `.agents/protocols/task-execution-protocol.md`; only after that start implementation.

