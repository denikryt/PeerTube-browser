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
4. `I27-F4-M1` - Add dedicated sync feature command for feature-only remote sync
5. `I28-F4-M1` - Add confirm issues batch command for multi-issue completion
### Dependencies
- See issue-level dependency blocks below.

### Decomposition
1. Execute follow-up issues in `Issue Execution Order`.
2. Keep per-issue implementation details inside canonical issue-plan blocks.

### Issue/Task Decomposition Assessment
- Decomposition is maintained per issue block; no extra feature-level split is required.

### I27-F4-M1 - Add dedicated sync feature command for feature-only remote sync
#### Dependencies
- Reuse existing feature/issue materialize helpers for GitHub repository and milestone resolution.
- Keep compatibility with current feature description/body sync behavior.

#### Decomposition
1. Add CLI command surface for `sync feature` with selectors: `--feature-id`, `--milestone-id`, and `--all`.
2. Implement strict target resolution: exactly one selector mode per run, deterministic feature set selection, clear validation errors.
3. Implement feature-only remote sync path that updates feature-level GitHub issue body from `feature.description` without materializing child issues.
4. Return deterministic sync summary fields (`attempted`, `updated`, `skipped`, `errors`) for operator visibility.
5. Add regression smoke coverage and docs updates for all selector modes and validation failures.

#### Issue/Task Decomposition Assessment
- CLI surface, target selection, remote sync execution, and regression coverage are separate risk areas and should be decomposed into independent tasks.

### I28-F4-M1 - Add confirm issues batch command for multi-issue completion
#### Dependencies
- Reuse existing `confirm issue ... done` cleanup and GitHub close logic.
- Preserve current completion semantics and safety checks for child tasks.

#### Decomposition
1. Add CLI command surface for `confirm issues` (plural) with repeatable `--issue-id` queue input.
2. Enforce batch gate: when confirming more than two issues, plural command path is required; preserve single-issue behavior for `confirm issue`.
3. Implement batch executor that runs existing single-issue confirmation semantics per queued issue with deterministic per-item result contract.
4. Add failure handling strategy for partial batch runs (continue vs stop contract) and explicit aggregate summary output.
5. Add smoke coverage for success, duplicate issue ids, cross-feature mismatch, and partial-failure reporting.

#### Issue/Task Decomposition Assessment
- Command parser changes, gate enforcement, batch execution semantics, and result-contract coverage should be decomposed into separate tasks.
