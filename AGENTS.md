# AGENTS.md

## ⚠️ MANDATORY INITIALIZATION RULE

**BEFORE EXECUTING ANY COMMAND:**
1. Read ALL files in `.agents/rules/` (non-negotiable constraints)
2. When you receive a command matching patterns below, read its workflow immediately
3. Execute the workflow exactly as written — no independent decisions

---

## KNOWN COMMANDS

When you receive text matching these patterns, it IS a command:

- `plan feature {ID}` → `.agents/workflows/plan-feature.md`
- `plan issue {ID}` → `.agents/workflows/plan-issue.md`
- `plan tasks for {ID}` → `.agents/workflows/plan-tasks-for.md`
- `create feature` → `.agents/workflows/create-feature.md`
- `execute feature {ID}` → `.agents/workflows/execute-feature.md`
- `execute issue {ID}` → `.agents/workflows/execute-issue.md`
- `execute issues {ID[, ID...]}` → `.agents/workflows/execute-issues.md`
- `execute task {ID}` → `.agents/workflows/execute-task.md`
- `materialize feature {ID}` → `.agents/workflows/materialize-feature.md`
- `confirm` → `.agents/workflows/confirm.md`
- `reject` → `.agents/workflows/reject.md`
- `init` → `.agents/workflows/init.md`

---

## COMMAND EXECUTION PROTOCOL

When you recognize a KNOWN COMMAND:
1. Read the corresponding workflow file from column 2 above
2. Follow ALL steps in that workflow exactly
3. Do not skip steps
4. Do not use subagents unless workflow explicitly requires it
5. Do not make independent decisions

---

> [!IMPORTANT]
> **Project rules and protocols are in `.agents/`.**
> - **Hard Policies**: See `.agents/rules/` for mandatory constraints.
> - **Procedures**: See `.agents/protocols/` for background information.
> - **Workflows**: See `.agents/workflows/` for command implementation details.

Canonical rules are maintained in the `.agents/` directory.
