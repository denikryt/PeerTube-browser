description: Generate or update a feature plan in FEATURE_PLANS.md for a given <feature_id>
---
> [!NOTE]
> This is a **planning-only** command. It does NOT write to runtime trackers such as `dev/TASK_LIST.json`, `dev/ISSUE_OVERLAPS.json`, or `dev/ISSUE_DEP_INDEX.json`.
> 
> This command focuses on **feature-level planning**: reads the feature from DEV_MAP, identifies related issues, and creates plans for each.
> - **If feature has existing issues**: plan each issue individually → eventually use `plan issue <issue_id>` for deeper planning
> - **If feature has no issues**: decompose feature into issues, **create them in DEV_MAP** → then plan each
>
> **Important:** Any new issues created during decomposition (Phase 2b) must be added to `dev/map/DEV_MAP.json` BEFORE planning them. Once in DEV_MAP, plan them following `plan-issue.md` workflow.
>
> For detailed planning of a single issue, use `.agents/workflows/plan-issue.md` (`plan issue <issue_id>`)

## Phase 1: Read and Analyze Feature

1. Read `.agents/protocols/feature-planning-protocol.md` (Section 0-2: Planning Prerequisites and Decomposition Rules).
2. Read `dev/map/DEV_MAP.json` and locate the feature by `<feature_id>`.
3. Extract feature metadata:
   - `feature_title`: from feature node title
   - `feature_description`: from feature node description
   - `related_issues`: array of issue IDs already linked to this feature (check `children` nodes with `type: Issue`)
4. **If related issues exist** (Check Existing / Prioritize Existing):
   - Proceed to Phase 2a: Plan each existing issue individually
5. **If no related issues exist** (Adequate Breakdown):
   - Proceed to Phase 2b: Decompose feature into issues

## Phase 2a: Plan Existing Issues

For **each existing related issue**:
1. Read the issue node from `DEV_MAP.json` (title, description).
2. Plan each issue following `.agents/workflows/plan-issue.md` (all phases).
3. Record all drafted issue plans in memory for insertion into `FEATURE_PLANS.md`.

## Phase 2b: Decompose Feature into Issues

**Only if no existing issues are linked to the feature:**
1. Analyze feature scope and required work.
2. Decompose into minimal-sufficient set of issues based on the **Decomposition Rules** in `.agents/protocols/feature-planning-protocol.md` Section 2:
   (Adequacy, Realism, Practicality, Sequence)
3. For each proposed issue, define:
   - `issue_title`: short, concrete title
   - `issue_description`: what must be implemented (connect to codebase paths if relevant)
   - Issue order in execution sequence
4. **Add new issues to `dev/map/DEV_MAP.json`**:
   - For each new issue, create an issue node under the target feature with:
     - `id`: follow ID format from `dev/map/DEV_MAP_SCHEMA.md` (`I<local>-F<feature_local>-M<milestone>`)
     - `title`: issue title
     - `description`: issue description
     - `status`: set to `Pending` (awaiting planning)
     - `type: Issue`
   - Confirm all new nodes are properly linked in feature's `children` array
   - If draft files are used for command input, write them into `tmp/workflow/` and follow `dev/map/ISSUE_CREATE_INPUT_SCHEMA.md`
5. Formulate issue plans following Phase 2a structure (use `.agents/workflows/plan-issue.md`).
6. Record all proposed (and now mapped) issues for insertion into `FEATURE_PLANS.md`.

## Phase 3: Draft Feature-Level Plan

Follow the **canonical structure** in `dev/FEATURE_PLANS.md` header section:

1. Feature-level block:
   - `## <feature_id>`
   - `### Issue Execution Order` (list all issues in execution order: both existing and newly created in Phase 2b)
   - `### Dependencies`
   - `### Decomposition`
   - `### Issue/Task Decomposition Assessment`

2. Issue-level blocks (one per issue, for all issues whether existing or newly created):
   - `### <issue_id> - <issue_title>`
   - `#### Dependencies` using strict lines only:
     `- file: ... | reason: ...`
     `- module: ... | reason: ...`
     `- function: ... | reason: ...`
     `- class: ... | reason: ...`
   - `#### Decomposition` (filled per plan-issue guidelines)
   - `#### Issue/Task Decomposition Assessment` (filled per plan-issue guidelines)

## Phase 4: Quality Verification

Before executing CLI commands:
1. Review `.agents/protocols/feature-planning-protocol.md` Section 3 (**Gate 0: Plan Detail and Formatting Standard** and **Gate A: Pre-decomposition review**).
2. Self-check the drafted feature and issue plans against both Gate 0 and Gate A checklists.
3. If any checks fail, refine the plan before proceeding.

## Phase 5: Insert into FEATURE_PLANS.md

1. Run: `python3 dev/workflow feature plan-init --id <feature_id>`
   - `plan-init` auto-inserts one plain line with `<title>` from `dev/map/DEV_MAP.json` into the feature section scaffold (without `Title:` label).
2. Open `dev/FEATURE_PLANS.md` and locate the newly created feature section.
3. Insert all drafted dependencies, issue execution order, decomposition, and assessments.
4. Ensure all issue-plan blocks follow the canonical format (see `FEATURE_PLANS.md` header).
5. If agent-generated markdown drafts are part of the workflow, keep the schema reference centralized in `dev/map/ISSUE_CREATE_INPUT_SCHEMA.md` instead of duplicating format rules inline.

## Phase 6: Validate and Finalize

1. Run: `python3 dev/workflow feature plan-lint --id <feature_id>`
2. If lint fails, fix `FEATURE_PLANS.md` and re-run until clean.
3. Stop execution and use `notify_user` with `BlockedOnUser=true` to wait for explicit approval (`approve feature plan`).
