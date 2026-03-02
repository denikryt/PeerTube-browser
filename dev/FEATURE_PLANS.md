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
4. `I32-F4-M1` - Allow materialize for Pending issues without mandatory issue plan/tasks
5. `I33-F4-M1` - Split DEV_MAP schema ownership into JSON schema and rules doc only
6. `I34-F4-M1` - Enforce explicit task breakdown quality in Issue/Task Decomposition Assessment
### Dependencies
- See issue-level dependency blocks below.

### Decomposition
1. Execute follow-up issues in `Issue Execution Order`.
2. Keep per-issue implementation details inside canonical issue-plan blocks.

### Issue/Task Decomposition Assessment
- Decomposition is maintained per issue block; no extra feature-level split is required.

### I32-F4-M1 - Allow materialize for Pending issues without mandatory issue plan/tasks

#### Dependencies
- `dev/workflow_lib/feature_commands.py` materialize status gate (`_enforce_materialize_issue_status_gate`) and related error contract.
- Runtime `execute issue` command path and its issue-status validation point.
- Canonical command/protocol owners: `dev/TASK_EXECUTION_PROTOCOL.md` and policy owner `AGENTS.md`.
- Secondary index/planning docs that must mirror canonical rules without drift: `dev/FEATURE_WORKFLOW.md`, `dev/FEATURE_PLANNING_PROTOCOL.md`.
- Regression harness for workflow behavior: `tests/check-workflow-cli-smoke.sh`.

#### Decomposition
1. Update policy text in `AGENTS.md` to remove the obsolete `explicit plan approval` dependency and allow `materialize feature` for `Pending` issue nodes before `plan issue`/`plan tasks`.
2. Update canonical command contract in `dev/TASK_EXECUTION_PROTOCOL.md`:
   - keep `plan tasks` gate for `Pending` as-is,
   - relax `materialize feature --mode issues-create|issues-sync` gate for unmapped issues from `Tasked` to active planning states (`Pending`/`Planned`/`Tasked`),
   - keep terminal-status protection (`Done`/`Rejected`) for create-oriented materialize behavior.
3. Align reference docs with canonical contract changes:
   - `dev/FEATURE_WORKFLOW.md` materialize gate wording,
   - `dev/FEATURE_PLANNING_PROTOCOL.md` Gate C checklist.
4. Add strict execution gate for issue-chain execution:
   - `execute issue <issue_id>` is allowed only when both conditions are true at the same time:
     - target issue status is exactly `Tasked`,
     - remote mapping is present and valid: `gh_issue_number` is non-null and `gh_issue_url` is non-empty.
   - if at least one condition is not met, execution must fail with deterministic gate error output and no execution side effects.
   - gate error must explicitly report which condition failed (status gate, mapping gate, or both).
5. Update runtime behavior in `dev/workflow_lib/feature_commands.py`:
   - adjust `_enforce_materialize_issue_status_gate` to match new allowed statuses,
   - keep mapped-issue `issues-sync` exception behavior,
   - replace stale guidance in error text (`run plan tasks ... first`) with gate-specific actionable output.
6. Update smoke coverage in `tests/check-workflow-cli-smoke.sh`:
   - add/adjust fixture where unmapped `Pending` issue succeeds in `feature materialize --mode issues-create`,
   - add execute-issue gate checks that reject `Pending`/`Planned` and allow `Tasked`,
   - ensure no failure expectation remains that requires `Tasked` for materialization of new issues,
   - keep decomposition (`plan tasks`) gate tests for `Pending` unchanged.
7. Run targeted workflow smoke and protocol consistency checks; if any gate mismatch remains, reconcile docs/code/tests in the same change set.

#### Issue/Task Decomposition Assessment
- Scope is intentionally minimal and localized to gate contracts for materialize + execute-issue readiness.
- The change set naturally splits into four implementation tasks:
  1. policy+protocol alignment,
  2. execute-issue status gate update,
  3. materialize gate update,
  4. smoke-test adjustments + final consistency validation.
- No new trackers or process artifacts are required; existing workflow docs/tests are sufficient for acceptance.

### I33-F4-M1 - Split DEV_MAP schema ownership into JSON schema and rules doc only

#### Dependencies
- Existing tracker schema style references: `dev/map/TASK_LIST_JSON_SCHEMA.json`, `dev/map/TASK_EXECUTION_PIPELINE_JSON_SCHEMA.json`.
- Current canonical owner links to migrate: `AGENTS.md`, `dev/TASK_EXECUTION_PROTOCOL.md`, `dev/FEATURE_PLANNING_PROTOCOL.md`.
- DEV_MAP write/read command paths that must remain stable after schema-owner switch.
- Workflow validation and smoke checks (`python3 dev/workflow validate ...`, `tests/check-workflow-cli-smoke.sh`).

#### Decomposition
1. Create `dev/map/DEV_MAP_JSON_SCHEMA.json` as the only structural contract for `dev/map/DEV_MAP.json`:
   - include object hierarchy (`milestones -> features/issues/tasks`, `standalone_issues`, metadata fields),
   - enforce status enums, required fields, ID patterns, and strict `additionalProperties` behavior where appropriate,
   - align schema version contract with current `DEV_MAP.json` (`schema_version`).
2. Create `dev/map/DEV_MAP_RULES.md` as the only semantic/process contract:
   - define lifecycle/gates/transitions and command-level interpretation rules,
   - define ownership map for what belongs to rules vs JSON schema,
   - explicitly prohibit duplicating structural field/type constraints from JSON schema.
3. Remove legacy owner `dev/map/DEV_MAP_SCHEMA.md` from the contract:
   - rewrite all repository dependencies to the two new canonical files,
   - update references in `AGENTS.md`, `dev/TASK_EXECUTION_PROTOCOL.md`, `dev/FEATURE_PLANNING_PROTOCOL.md`, and other process/docs files,
   - do not keep compatibility aliases, redirects, or duplicate fallback docs.
4. Wire strict machine validation into workflow path(s) that mutate DEV_MAP:
   - validate resulting `DEV_MAP.json` against `DEV_MAP_JSON_SCHEMA.json` before/after write operations,
   - fail deterministically with actionable schema error output on violations.
5. Add regression checks for ownership split and dependency rewrite:
   - validate that no canonical doc still points to `DEV_MAP_SCHEMA.md`,
   - validate that both new files are present and used by validation flow,
   - cover at least one negative schema case to confirm hard failure behavior.
6. Run full consistency pass:
   - workflow smoke (`tests/check-workflow-cli-smoke.sh`),
   - feature plan lint for affected feature section,
   - targeted grep audit to ensure no residual canonical references to removed owner.

#### Issue/Task Decomposition Assessment
- Scope is migration-oriented and intentionally breaks backward compatibility by design.
- Work is separated into structural contract, semantic rules, dependency rewrite, and validation enforcement to keep responsibilities non-overlapping.
- Expected outcome is deterministic: two canonical files only (`DEV_MAP_JSON_SCHEMA.json`, `DEV_MAP_RULES.md`) with zero canonical dependency on `DEV_MAP_SCHEMA.md`.

### I34-F4-M1 - Enforce explicit task breakdown quality in Issue/Task Decomposition Assessment

#### Dependencies
- Planning quality owner: `dev/FEATURE_PLANNING_PROTOCOL.md`.
- Command/lint implementation path: `dev/workflow_lib/feature_commands.py` (`plan-issue` write/lint flow).
- Canonical command-order owner references: `dev/TASK_EXECUTION_PROTOCOL.md`, `dev/FEATURE_WORKFLOW.md`.
- Regression harness for quality gates: `tests/check-workflow-cli-smoke.sh`.

#### Decomposition
1. Define strict quality contract for `Issue/Task Decomposition Assessment` in `dev/FEATURE_PLANNING_PROTOCOL.md`:
   - section must contain a numbered task breakdown list (not generic prose),
   - each task item must include implementation target, concrete file/module scope, and validation step,
   - reject vague placeholders (`improve`, `refine`, `etc.` without implementation/validation details).
2. Update canonical references in process docs so this rule is declared once in planning owner and referenced elsewhere:
   - `dev/TASK_EXECUTION_PROTOCOL.md` and `dev/FEATURE_WORKFLOW.md` should reference planning owner without duplicating rule text.
3. Implement enforcement in workflow lint path (`dev/workflow_lib/feature_commands.py`):
   - parse the `Issue/Task Decomposition Assessment` section and require explicit numbered task rows,
   - return deterministic error messages indicating missing task list or incomplete task item fields.
4. Update `feature plan-issue` generation behavior:
   - produced block must include issue-specific task breakdown (not fallback boilerplate),
   - generated tasks must map directly to the issue context (`title`, `description`, affected modules).
5. Align existing active issue plan blocks in `dev/FEATURE_PLANS.md` to the new contract where required.
6. Add smoke coverage for pass/fail cases:
   - fail when assessment contains only abstract text,
   - pass when assessment has explicit task list with implementation + validation details.
7. Run full lint/smoke verification and fix any residual drift in one change set.

#### Issue/Task Decomposition Assessment
1. Task A: Planning contract hardening
   - Deliverable: explicit normative rule text in `dev/FEATURE_PLANNING_PROTOCOL.md`.
   - Validation: `feature plan-lint` rejects issue blocks that miss numbered task breakdown.
2. Task B: Lint parser enforcement
   - Deliverable: parser/validator updates in `dev/workflow_lib/feature_commands.py` for assessment task rows.
   - Validation: deterministic error output identifies exact missing element per task row.
3. Task C: Plan-issue output quality
   - Deliverable: `feature plan-issue` writes issue-specific task list with concrete implementation scope.
   - Validation: generated block includes actionable tasks tied to issue context, no generic stubs.
4. Task D: Existing-plan conformance update
   - Deliverable: normalize affected active issue blocks in `dev/FEATURE_PLANS.md` to new format.
   - Validation: `python3 dev/workflow feature plan-lint --id F4-M1` returns `valid: true`.
5. Task E: Regression coverage
   - Deliverable: smoke cases for failing/good assessment content in `tests/check-workflow-cli-smoke.sh`.
   - Validation: smoke run fails on vague assessment and passes on explicit task breakdown format.

## F6-M1

### Issue Execution Order
1. `I1-F6-M1` - Implement Markdown template parser for CLI inputs
2. `I2-F6-M1` - Wire --input argument to create feature and create issue commands
3. `I3-F6-M1` - Update agent workflows to use draft files for CLI commands

### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — create feature/issue handlers and CLI registration
- [dev/workflow_lib/errors.py](dev/workflow_lib/errors.py) — `WorkflowCommandError` for validation
- [.agents/protocols/feature-planning-protocol.md](.agents/protocols/feature-planning-protocol.md) — planning quality standards
- [.agents/workflows/plan-feature.md](.agents/workflows/plan-feature.md) and [plan-issue.md](.agents/workflows/plan-issue.md) — workflow definitions to update
- `tmp/workflow/` — temporary file directory for agent-generated markdown templates

### Decomposition
1. Implement parser utility in `dev/workflow_lib/markdown_parser.py` that extracts title and description from Markdown templates with flexible heading detection and clear error messages.
2. Wire parser into CLI `create feature` and `create issue` commands via optional `--input` argument while maintaining backward compatibility with existing flag-based mode.
3. Create schema file `dev/map/ISSUE_CREATE_INPUT_SCHEMA.md` defining canonical template structure; update protocol and workflow docs to reference schema and `tmp/workflow/` temporary storage directory.

### Issue/Task Decomposition Assessment
- Decomposition splits into three sequential issues with explicit dependencies on task completion: I1 ← I2 ← I3.
- Expected outcome: agents can safely generate Markdown templates and pass via CLI `--input` argument; workflows updated to document optional agent input mechanism.
- No new trackers required; existing workflow and protocol docs sufficient for schema reference and usage guidance.

### I1-F6-M1 - Implement Markdown template parser for CLI inputs

#### Dependencies
- [dev/workflow_lib/errors.py](dev/workflow_lib/errors.py) — `WorkflowCommandError` for validation with exit codes
- [dev/workflow_lib/tracking_writers.py](dev/workflow_lib/tracking_writers.py#L207) — existing markdown utility patterns for reference
- Python standard library: `pathlib.Path`, `re` for heading pattern detection

#### Decomposition
1. Create new module `dev/workflow_lib/markdown_parser.py`:
   - Input contract: file path to Markdown file (UTF-8 encoded)
   - Output contract: structured dict `{"title": str, "description": str}`
   - Flexible heading detection: extract first two headings (any level: #, ##, ###, etc.)

2. Implement `parse_feature_issue_template(file_path: Path) -> dict`:
   - Read file with UTF-8 encoding; handle `FileNotFoundError` with error message: `"Input file not found: {path}. Ensure the file exists before re-running."`
   - Extract first heading as title using regex pattern `^#+\s+(.+)$` (match any level, trim whitespace)
   - Extract content between first heading and second heading (or EOF) as description
   - Return `{"title": title_str, "description": description_str}`
   - Validation: title must be non-empty (error if missing); description allowed empty (warning)
   - On parse error, raise `WorkflowCommandError` with exit_code=4 and actionable guidance

3. Error handling with deterministic messages:
   - No headings detected: `"No headings detected in {path}. Expected at least one heading for title. Format: # Title followed by content."`
   - Empty title text: `"Title heading is empty. Provide text after the first heading, e.g., '# My Title'"`
   - File read error: wrap OS error with context message

4. Design for testability:
   - Happy path: file with `# Title` + `## Description content`
   - Flexible headings: `### Title` + `# Description` (level and order flexible)
   - Missing title: error with recovery guidance
   - Missing description: title extracted, description empty string
   - File not found: clear error message

#### Issue/Task Decomposition Assessment
- Decomposition state: `planning` (plan only; task allocation deferred to `plan tasks for I1-F6-M1`).
- Expected split: 3-4 tasks
  1. Module setup + core parsing logic (heading extraction, template validation)
  2. Error handling + file I/O + validation
  3. Test coverage for happy paths and failure scenarios
  4. Docstring + usage examples + integration guide

### I2-F6-M1 - Wire --input argument to create feature and create issue commands

#### Dependencies
- [I1-F6-M1](#i1-f6-m1--implement-markdown-template-parser-for-cli-inputs) — parser module and function must exist
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py#L66-L95) — CLI argument registration in create subcommand parsers
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py#L289) — `_handle_feature_create` and `_handle_create_issue` handlers

#### Decomposition
1. Extend CLI argument parsers for both `create feature` and `create issue` subcommands:
   - Add optional argument `--input <path>` accepting file path string
   - Keep all existing flags (`--title`, `--description`, `--track`, etc.) for backward compatibility
   - Add validation: if both `--input` and `--title`/`--description` are provided, error with message: `"Cannot combine --input with --title/--description. Use one input method only."`

2. Update `_handle_feature_create` and `_handle_create_issue` handlers:
   - Check if `args.input` is provided
   - If yes: import and call parser from I1; extract `title` and `description` from parsed result
   - If parsing fails: catch `WorkflowCommandError` and propagate with same exit code (4 for input validation)
   - If `--input` not provided: use existing flag-based logic (backward compatible path)
   - Merge parsed values into command execution (same downstream handler logic as flag-based)

3. Ensure deterministic behavior:
   - `--input` takes precedence if both input methods present (or strict error — choose one mode)
   - Parser errors bubble up with clear messages indicating file/format problem
   - Empty title from parser = error (consistent with flag-based validation)
   - Empty description from parser = allowed with warning

4. Validation and edge cases:
   - Success: parsed template values used for feature/issue creation
   - Parser error: exit code 4 + actionable message re-run guidance
   - Missing input file: exit code 4 + file path in error text
   - Backward compatibility: flag-based mode unchanged when `--input` not provided

#### Issue/Task Decomposition Assessment
- Decomposition state: `planning` (plan only; task allocation deferred to `plan tasks for I2-F6-M1`).
- Expected split: 3-4 tasks
  1. Argument parser extension for both `create feature` and `create issue` commands
  2. Handler update + template value merge + precedence logic
  3. Error handling + backward-compatibility validation tests
  4. Integration smoke tests + command docs update

### I3-F6-M1 - Update agent workflows to use draft files for CLI commands

#### Dependencies
- [I1-F6-M1](#i1-f6-m1--implement-markdown-template-parser-for-cli-inputs) and [I2-F6-M1](#i2-f6-m1--wire--input-argument-to-create-feature-and-create-issue-commands) — parser and CLI wiring must be functional
- [.agents/protocols/feature-planning-protocol.md](.agents/protocols/feature-planning-protocol.md) — planning standards and protocols (read + update allowed)
- [.agents/workflows/plan-feature.md](.agents/workflows/plan-feature.md#L38) — Phase 5 (Insert into FEATURE_PLANS) reference
- [.agents/workflows/plan-issue.md](.agents/workflows/plan-issue.md#L73) — Phase 4 (Execute CLI) reference
- `tmp/workflow/` — temporary file directory (already exists)

#### Decomposition
1. Create schema file `dev/map/ISSUE_CREATE_INPUT_SCHEMA.md`:
   - Define canonical Markdown template format for **feature creation**: title heading + optional description heading + content sections
   - Define canonical Markdown template format for **issue creation**: title heading + optional description heading + content sections
   - Document: any heading level (# ## ###) allowed; parser extracts first two headings by position
   - Document required vs optional fields: title required (non-empty), description optional (empty allowed, warn)
   - Document error scenarios: missing title, missing headings, no file, file not readable
   - Document recovery guidance for each error type
   - Include example templates: good format (correct template), bad format (common mistakes)
   - This file is the single source of truth; both protocol and workflows reference it only

2. Update [.agents/protocols/feature-planning-protocol.md](.agents/protocols/feature-planning-protocol.md):
   - **Section 0 (Planning Prerequisites):** Add note that agents can generate Markdown templates for safe multi-line input
   - **New subsection "Agent Output Method: Markdown Templates":** Reference `dev/map/ISSUE_CREATE_INPUT_SCHEMA.md` for template format and structure
   - Document temp storage convention: `tmp/workflow/` directory for agent-generated draft files (example: `tmp/workflow/feature_draft_<timestamp>.md`)
   - Example workflow: agents write draft to temp file, pass path to `python3 dev/workflow feature create --input <path>`
   - Clarify: temp file approach is optional for humans; recommended for AI agents to avoid JSON corruption

3. Update [.agents/workflows/plan-feature.md](.agents/workflows/plan-feature.md#L38):
   - **Phase 2b (Decompose Feature into Issues):** Add optional agent guidance: If decomposing into new issues, agents may generate Markdown drafts and use `create issue --input <path>` for each issue creation
   - **Phase 5 (Insert into FEATURE_PLANS.md):** Add reference link: agents may write planning drafts; see `dev/map/ISSUE_CREATE_INPUT_SCHEMA.md` for format and `tmp/workflow/` for temp storage directory convention
   - Clarify: human workflows continue unchanged; agent workflow entirely optional

4. Update [.agents/workflows/plan-issue.md](.agents/workflows/plan-issue.md#L42):
   - **Phase 2 (Formulate Issue Plan):** Add optional note: agents formulating plans may write output to Markdown draft file for structured persists before CLI insertion
   - **Phase 4 (Execute CLI):** Reference protocol schema if agents choose file-based input approach; link to `dev/map/ISSUE_CREATE_INPUT_SCHEMA.md`
   - Emphasize: optional enhancement; human-driven workflows use memory-based planning as-is

5. Validation and schema ownership:
   - Schema file exists and contains complete specifications
   - Protocol and both workflow files reference schema (no duplication of schema rules in workflows)
   - Temp directory path consistent: `tmp/workflow/` referenced in protocol
   - No residual schema duplication across canonical docs

#### Issue/Task Decomposition Assessment
- Decomposition state: `planning` (plan only; task allocation deferred to `plan tasks for I3-F6-M1`).
- Expected split: 3-4 tasks
  1. Create `dev/map/ISSUE_CREATE_INPUT_SCHEMA.md` with full template specifications and examples
  2. Update `dev/FEATURE_PLANNING_PROTOCOL.md` with new "Agent Output Method" subsection and schema reference
  3. Update both workflow docs (`plan-feature.md`, `plan-issue.md`) with optional agent guidance and protocol reference
  4. Validation: grep + manual check that schema not duplicated in workflows; verify all canonical references point to schema file
