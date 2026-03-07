---
trigger: always_on
glob:
description: Strict execution triggers for agent tasks
---

1. Do not start implementing any task until the user gives an explicit execution command. Valid formats are:
   - `execute task X` (single task)
   - `execute issue <issue_id>` (all pending tasks in an issue)
   - `execute issues <issue_id>, <issue_id>, ...` (multi-issue package run in the user-provided order)
   - `execute feature <feature_id>` (all pending tasks in a feature)
   - `Execute bundle: <taskA> -> <taskB> -> <taskC>[, mode=strict, no-duplicate-logic]` (multi-task run)
2. Any message that does not contain one of these explicit commands is treated as non-execution (clarification, planning, edits of task text, review, or discussion only).
3. If the user intent looks like execution but the command format is not explicit, ask for a direct command in any of the required formats and do not start implementation.
4. User confirmation that a task is completed is separate from execution start and must still be explicit.
5. On any explicit execution command (task, issue, issues, feature, or bundle), first follow the mandatory read order defined in **Section 1 (Read order)** of `.agents/protocols/task-execution-protocol.md` before implementation.
