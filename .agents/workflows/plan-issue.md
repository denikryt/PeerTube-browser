---
description: Produce or update an issue-level plan block in FEATURE_PLANS.md
---
> [!NOTE]
> This is a **planning-only** command for single-issue (or multi-issue) detailed planning.
> It produces or updates the issue-plan block in `dev/FEATURE_PLANS.md` following strict quality gates.
>
> This command is called after `plan feature <feature_id>` either:
> - to deepen planning of an **existing** issue that was identified in the feature decomposition, or
> - to plan an **additional** issue if feature decomposition changes

## Phase 1: Read and Resolve Issue Context

1. Resolve the target `<issue_id>` in `dev/map/DEV_MAP.json`.
2. Extract issue metadata:
   - `issue_title`: from issue node title
   - `issue_description`: from issue node description
   - `parent_feature_id`: feature that owns this issue
   - `issue_status`: current status (`Pending`, `Planned`, `Tasked`, etc.)
3. Analyze parent feature in `dev/map/DEV_MAP.json`:
   - confirm issue is properly linked under feature
   - understand feature context and scope

## Phase 2: Formulate Issue Plan

### 2.1 Dependencies (Issue-Level)

Identify dependencies specifically for this issue:
- Other issues that must be completed first
- Feature-level dependencies that affect this issue
- External task dependencies from `dev/TASK_LIST.json`
- Code paths, modules, or APIs this issue touches
- Standards or protocols relevant to implementation (reference `.agents/protocols/`, `.agents/rules/`)

### 2.2 Decomposition (Issue-Level Implementation Flow)

Formulate the issue-level implementation plan following the **Planning Input Contract** in `.agents/protocols/feature-planning-protocol.md` Section 1.

Create numbered top-level steps with concrete sub-points (what to do, input/output contracts, expected result).

If agent-generated draft files are used for create commands, keep them in `tmp/workflow/` and use `dev/map/ISSUE_CREATE_INPUT_SCHEMA.md` as the only schema reference.

Example structure:
```
1. Update policy in AGENTS.md
   - Target file and line range
   - Input: current policy state
   - Output: modified text
   - Validation: grep check for new text
```

### 2.3 Issue/Task Decomposition Assessment

Formulate the explicit decomposition assessment following the **Planning Input Contract** in `.agents/protocols/feature-planning-protocol.md` Section 1.

State clearly:
- What must be done next before task decomposition, if the issue is still plan-only
- Or, if task decomposition already exists, the explicit task count and per-task scope

## Phase 3: Quality Verification

Before executing CLI commands:
1. Review `.agents/protocols/feature-planning-protocol.md` Section 3 (**Gate 0: Plan Detail and Formatting Standard** and **Gate A: Pre-decomposition review**).
2. Self-check the drafted issue plan against both Gate 0 and Gate A checklists.
3. If any checks fail, refine the plan before proceeding.

## Phase 4: Execute CLI and Insert Plan

1. Run: `python3 dev/workflow feature plan-issue --id <issue_id> [--title <optional_title>]`
   - This creates or updates the issue-plan block in `dev/FEATURE_PLANS.md`
   - Block will use heading `### <issue_id> - <issue_title>` under the parent feature section

2. Open `dev/FEATURE_PLANS.md` and verify the generated block:
   - Heading format: `### <issue_id> - <issue_title>` (✓)
   - Allowed inner headings: only `#### Dependencies`, `#### Decomposition`, `#### Issue/Task Decomposition Assessment` (✓)
   - All three inner headings are present (✓)

3. Insert your drafted plan content into the three sections:
   - `#### Dependencies`: paste issue-level dependencies
   - `#### Decomposition`: paste numbered implementation steps
   - `#### Issue/Task Decomposition Assessment`: paste explicit assessment

4. Ensure issue-specific content (not generic templates or fallback stubs):
   - Reference actual files/functions/modules
   - Connect to issue title and description
   - Explain *why* each step is necessary for this specific issue

## Phase 5: Validate and Complete

1. Run: `python3 dev/workflow feature plan-lint --id <issue_id> --type issue`
   - This validates structure and content quality against Gate 0/A requirements
   - If lint fails: read error output, fix `FEATURE_PLANS.md`, and re-run

2. Repeat lint until clean (zero errors)

3. Stop execution and use `notify_user` with `BlockedOnUser=true` to wait for explicit review and approval
