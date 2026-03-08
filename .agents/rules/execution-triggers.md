---
trigger: always_on
glob:
description: Canonical execution trigger rules
---

1. This file is the single source of truth for execution trigger semantics. Other files may reference it, but must not redefine or extend its trigger rules.
2. Do not start implementation unless one of the following is true:
   - the user gives a tracked workflow execution command,
   - the user gives a direct imperative request to change code, config, docs, or files.
3. Valid tracked workflow formats remain:
   - `execute task X` (single task)
   - `execute issue <issue_id>` (all pending tasks in an issue)
   - `execute issues <issue_id>, <issue_id>, ...` (multi-issue package run in the user-provided order)
   - `execute feature <feature_id>` (all pending tasks in a feature)
   - `Execute bundle: <taskA> -> <taskB> -> <taskC>[, mode=strict, no-duplicate-logic]` (multi-task run)
4. A direct imperative request is explicit action language such as `do this`, `make this change`, `fix it`, `add this`, `remove that`, `rewrite this`, `implement this`, `change this behavior`, or equivalent phrasing in any language.
5. Phrasing that is exploratory, advisory, or suggestive does not by itself authorize implementation. Examples include `let's`, `maybe`, `I think`, `what if`, `it would be good`, or similar wording when not paired with a direct imperative.
6. If the user intent is ambiguous, ask one short clarifying question instead of starting implementation.
7. If a tracked execution scope is already active, direct imperative follow-up requests inside that same scope remain valid continuation triggers without a repeated `execute ...` command.
8. Follow-up execution without a repeated tracked command is allowed only when:
   - the change is a direct continuation of the same feature, issue, or local modification scope already being implemented,
   - the request does not expand scope into a different tracked feature or issue unless the user explicitly asks for that expansion,
   - the change is not destructive.
9. Tracked workflow commands remain mandatory when the user explicitly wants workflow-governed execution for a task, issue, issue bundle, or feature.
10. Destructive, unsafe, or higher-risk actions may still require separate confirmation under higher-priority safety rules.
