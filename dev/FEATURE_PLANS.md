# Feature Plans

Canonical storage for `plan feature <id>` outputs.

## Scope ownership

- This file stores plan artifacts only.
- Command semantics/order are defined in `dev/TASK_EXECUTION_PROTOCOL.md`.
- Planning quality requirements are defined in `dev/FEATURE_PLANNING_PROTOCOL.md`.

## Format

Each feature plan section must use the feature ID as a heading and include:
- Dependencies
- Decomposition
- Issue/Task Decomposition Assessment

Canonical per-issue plan block format inside a feature section:
- Heading: `### <issue_id> - <issue_title>` (one block per issue ID).
- Allowed inner headings: only `#### Dependencies`, `#### Decomposition`, `#### Issue/Task Decomposition Assessment`.
- All three inner headings are mandatory for each issue block.

## Planned Features

<!-- Add or update feature plan sections below, for example: -->
<!-- ## F<local>-M<milestone> -->
<!-- ### Dependencies -->
<!-- ... -->

## F4-M1

### Issue Execution Order
1. `I7-F4-M1` - Issue creation command for feature/standalone with optional plan init
2. `I9-F4-M1` - Add workflow CLI show/status commands for feature/issue/task
3. `I13-F4-M1` - Auto-delete sync delta file after successful decomposition write
4. `I29-F4-M1` - DevMap Viewer: show feature/issue descriptions in expanded rows and hide task timestamps
5. `I30-F4-M1` - Issue creation protocol: require immediate materialization after creating a new issue
### Dependencies
- See issue-level dependency blocks below.

### Decomposition
1. Execute follow-up issues in `Issue Execution Order`.
2. Keep per-issue implementation details inside canonical issue-plan blocks.

### Issue/Task Decomposition Assessment
- Decomposition is maintained per issue block; no extra feature-level split is required.

### I29-F4-M1 - DevMap Viewer: show feature/issue descriptions in expanded rows and hide task timestamps
#### Dependencies
- Existing DevMap Viewer expand/collapse rendering for Feature/Issue/Task rows.
- Current issue metadata rendering that shows GitHub issue number in expanded issue view.

#### Decomposition
1. Update DevMap Viewer rendering for expanded Issue rows to show `description` text next to existing issue metadata.
2. Update DevMap Viewer rendering for expanded Feature rows to show feature `description`.
3. Remove task timestamp rendering from task rows in DevMap Viewer while preserving task title/status visibility.
4. Add/update viewer smoke/manual validation notes for expand/collapse behavior and description visibility.

#### Issue/Task Decomposition Assessment
- UI rendering changes span three separate surfaces (Feature expand, Issue expand, Task row fields), so decomposition should split them into isolated implementation tasks.

### I30-F4-M1 - Issue creation protocol: require immediate materialization after creating a new issue
#### Dependencies
- Canonical command semantics in `dev/TASK_EXECUTION_PROTOCOL.md`.
- Workflow command index in `dev/FEATURE_WORKFLOW.md`.

#### Decomposition
1. Define canonical rule: after local issue creation, immediate materialization is required to create/match GitHub issue mapping.
2. Update canonical protocol section that documents issue creation and next-step command order to include immediate materialization step.
3. Update workflow index references so creation flow and examples reflect the new required step while preserving standalone `materialize` command availability.
4. Add/adjust smoke/docs checks to detect missing materialization step in issue creation guidance.

#### Issue/Task Decomposition Assessment
- Rule definition, protocol edits, workflow index alignment, and regression coverage should be decomposed into separate tasks because they touch different ownership boundaries.
