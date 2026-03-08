---
trigger: always_on
glob:
description: Execution triggers for agent tasks and direct user-requested changes
---

1. Do not start implementing changes unless the user explicitly requests a code, config, docs, or file modification, or provides a tracked workflow execution command.
2. Any explicit user request to make changes is a valid execution trigger. This includes direct imperatives and clearly action-oriented requests such as "do this", "make this change", "fix it", "add this", "remove that", "rewrite this", "implement this", or equivalent phrasing in any language.
3. Valid tracked workflow formats remain:
   - `execute task X` (single task)
   - `execute issue <issue_id>` (all pending tasks in an issue)
   - `execute issues <issue_id>, <issue_id>, ...` (multi-issue package run in the user-provided order)
   - `execute feature <feature_id>` (all pending tasks in a feature)
   - `Execute bundle: <taskA> -> <taskB> -> <taskC>[, mode=strict, no-duplicate-logic]` (multi-task run)
4. Messages that are exploratory, analytical, planning-oriented, or otherwise not explicit requests to modify something are treated as non-execution.
5. If the user intent is ambiguous, prefer asking one short clarifying question instead of starting implementation.
6. If the user directly requests a concrete follow-up code fix inside an already active implementation scope, the agent may execute it without requiring any repeated command.
7. Follow-up execution is allowed only when:
   - the change is a direct continuation of the same feature, issue, or local modification scope already being implemented,
   - the request does not expand scope into a different tracked feature or issue unless the user explicitly asks for that expansion,
   - the change is not destructive.
8. In such cases, direct user imperatives like "fix it", "add this", "remove that", and "change this behavior" are valid continuation triggers.
9. Tracked workflow commands remain mandatory when the user explicitly wants workflow-governed execution for a task, issue, issue bundle, or feature.
10. Destructive, unsafe, or higher-risk actions may still require separate confirmation under higher-priority safety rules.
