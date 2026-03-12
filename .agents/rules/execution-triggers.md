---
trigger: always_on
glob:
description: Canonical execution trigger rules
---

1. Start implementation only when the user gives either:
   - a tracked workflow execution command, or
   - a direct imperative request to change repository files.
2. Canonical tracked execution commands are:
   - `execute feature <feature_id>`
   - `execute issue <issue_id>`
3. Direct imperative follow-up inside an already active feature or issue scope remains a valid continuation trigger.
4. Completion commands (`done ...`) are separate from execution triggers.
