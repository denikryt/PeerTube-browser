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

## F7-M1

### Issue Execution Order
1. `I1-F7-M1` - Implement validate issue command with Pending→Planned transition
2. `I2-F7-M1` - Wire --input argument to plan issue command for markdown draft parsing
3. `I3-F7-M1` - Rename feature.plan-issue command to plan issue in CLI routing
4. `I4-F7-M1` - Update task-execution-protocol and workflow docs for new planning lifecycle

### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — CLI routing, command handlers, DEV_MAP write paths
- [dev/workflow_lib/markdown_parser.py](dev/workflow_lib/markdown_parser.py) — parser from F6-M1 (prerequisite: I1-F6-M1 or I2-F6-M1 must be completed)
- [dev/workflow_lib/errors.py](dev/workflow_lib/errors.py) — `WorkflowCommandError` for validation
- [.agents/protocols/task-execution-protocol.md](.agents/protocols/task-execution-protocol.md) — command execution standards (read + update allowed)
- [.agents/workflows/plan-feature.md](.agents/workflows/plan-feature.md) and [plan-issue.md](.agents/workflows/plan-issue.md) — workflow procedures (read + update allowed)
- `dev/FEATURE_PLANS.md` — issue plan blocks (target for `plan issue` writes)
- `dev/map/DEV_MAP.json` — issue node storage (status updates)

### Decomposition
1. Implement explicit `validate issue` command with quality gate enforcement and status transition logic.
2. Wire `--input <draft_file>` argument to `plan issue` command to parse Markdown templates from agent-generated draft files.
3. Consolidate CLI command structure by renaming legacy `feature plan-issue` to canonical `plan issue`.
4. Update all canonical protocol and workflow documentation to reflect new Pending→Planned→Tasked lifecycle with explicit validation gates.

### Issue/Task Decomposition Assessment
- Decomposition splits into four sequential issues: I1 (validate command) → I2 (input wiring) → I3 (rename) → I4 (docs update).
- Expected outcome: unified planning workflow with explicit validation gate; agents can safely generate draft files and parse them via CLI.
- New command dependency: I2-F7-M1 requires markdown parser from F6-M1; gate enforcement requires both I1 + I2 before code integration.

### I1-F7-M1 - Implement validate issue command with Pending→Planned transition

#### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — command registration, handler implementation, DEV_MAP write paths
- [dev/workflow_lib/errors.py](dev/workflow_lib/errors.py) — `WorkflowCommandError` for validation failures
- [.agents/protocols/feature-planning-protocol.md](.agents/protocols/feature-planning-protocol.md) — Gate 0 quality standards for reference
- `dev/FEATURE_PLANS.md` — issue-plan block location and validation target
- `dev/map/DEV_MAP.json` — issue node storage for status updates

#### Decomposition
1. Create new CLI command handler `_handle_validate_issue`:
   - Input: `issue_id` (required), `--write` flag (optional dry-run vs commit)
   - Resolve target issue in `DEV_MAP.json`; validate ownership chain and status precondition (must be Pending)
   - Read FEATURE_PLANS.md and extract issue-plan block for target issue
   - Return error if issue section/block not found with actionable guidance (run `plan issue` first)

2. Implement quality validation against Gate 0 requirements:
   - Issue-plan block exists and contains all three mandatory sections: `#### Dependencies`, `#### Decomposition`, `#### Issue/Task Decomposition Assessment`
   - `#### Decomposition` has numbered top-level steps with concrete sub-points (not generic prose)
   - `#### Issue/Task Decomposition Assessment` contains explicit expected split/task breakdown (not vague placeholders)
   - Return deterministic error messages for each validation failure (e.g., "Missing numbered steps in Decomposition section")

3. Implement status transition logic (only when `--write` is provided):
   - If validation passes: update issue status in DEV_MAP.json from Pending → Planned
   - Write DEV_MAP changes in same edit run
   - Return success with explicit status field: `"status": "Planned"`, `"validation": "passed"`
   - If validation fails: make no DEV_MAP changes, return error with validation details

4. Deterministic output contract:
   - Dry-run (`--write` absent): return action "would-plan-validate"
   - Commit (`--write` present): return action "validated-planned", include updated issue status

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
  1. Handler registration in CLI feature_commands module + argument parser setup
  2. Quality validation logic implementation (headings, numbered steps, assessment content checks)
  3. DEV_MAP status update logic + error handling for edge cases (missing block, bad status, ownership mismatch)
  4. Test coverage for validation pass/fail paths and status transition idempotency

### I2-F7-M1 - Wire --input argument to plan issue command for markdown draft parsing

#### Dependencies
- [I1-F7-M1](#i1-f7-m1--implement-validate-issue-command-with-pendingplanned-transition) — validate issue command should exist first for clarity
- [I1-F6-M1](dev/FEATURE_PLANS.md#i1-f6-m1--implement-markdown-template-parser-for-cli-inputs) — markdown parser from F6-M1 must be available
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — `plan issue` command handler and argument parser
- [dev/workflow_lib/markdown_parser.py](dev/workflow_lib/markdown_parser.py) — `parse_feature_issue_template()` parser function

#### Decomposition
1. Extend CLI argument parser for `plan issue` subcommand:
   - Add optional `--input <file_path>` argument accepting file path string
   - Keep existing manual arguments (`--title`, `--description`, etc.) for backward compatibility
   - Validation: if both `--input` and manual args are provided, error with message: `"Cannot combine --input with --title/--description. Use one input method only."`

2. Update `_handle_feature_plan_issue` handler logic:
   - Check if `args.input` is provided
   - If yes: import and call parser from F6-M1; extract title/description from parsed result (catches parser errors with exit code 4)
   - If no: use existing manual args as-is (backward compatible)
   - Merge extracted values into same downstream plan-block generation logic (no duplication)

3. Ensure deterministic behavior:
   - `--input` takes precedence; flags ignored when `--input` provided (or strict mutual-exclusion error)
   - Parser errors propagate with original error messages and exit codes (4 for input validation)
   - Successfully parsed values use same validation/defaults as manual args (empty description allowed, empty title errors)

4. Deterministic output contract:
   - Both input modes produce identical output; only source differs (file vs args)
   - Return action "created-plan" or "updated-plan" based on block mutation, not input method
   - Backward compatibility: no breaking API changes; existing flag-based workflows unchanged

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
  1. Argument parser extension for `--input` in plan-issue CLI registration
  2. Handler logic update: conditional parser call + value extraction + merge with existing flow
  3. Error handling + backward-compatibility validation tests (both input modes)
  4. Integration smoke tests + command docs update (clarify both modes supported)

### I3-F7-M1 - Rename feature.plan-issue command to plan issue in CLI routing

#### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — CLI command registration and routing
- [dev/workflow_lib/cli.py](dev/workflow_lib/cli.py) — command-line interface module
- [I2-F7-M1](#i2-f7-m1--wire--input-argument-to-plan-issue-command-for-markdown-draft-parsing) — should be ready before rename to avoid duplicate code paths

#### Decomposition
1. Audit existing command registration:
   - Search for `feature.plan-issue` in CLI router (feature_commands.py, cli.py)
   - Identify all subcommand registration points and help text references
   - List all validation/routing logic that depends on command structure

2. Implement CLI routing change:
   - Remove `feature plan-issue` registration from feature command group
   - Add new top-level `plan issue` command registration (separate from feature group)
   - Update argument parser bindings and handler references
   - Preserve all existing functionality; only namespace/structure changes

3. No backward compatibility: remove `feature plan-issue` entirely and replace with `plan issue` as the canonical command.
   - Remove all code paths and registrations for old `feature.plan-issue` command
   - Update all error messages and docs to reject old command name explicitly
   - Document breaking change clearly in release notes

4. Return deterministic output:
   - `plan issue --help` shows new command structure
   - Command execution behavior unchanged (same handler, same output contract)
   - CLI help text references new command naming throughout

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
  1. Audit and mapping of all command registration points (feature_commands.py, cli.py)
  2. Implement new `plan issue` routing + remove old `feature plan-issue` path entirely
  3. Update all help text, error messages, docs references to reject old command name
  4. Smoke tests: verify `plan issue --help` works, `feature plan-issue` explicitly rejected with error

### I4-F7-M1 - Update task-execution-protocol and workflow docs for new planning lifecycle

#### Dependencies
- [I1-F7-M1](#i1-f7-m1--implement-validate-issue-command-with-pendingplanned-transition), [I2-F7-M1](#i2-f7-m1--wire--input-argument-to-plan-issue-command-for-markdown-draft-parsing), [I3-F7-M1](#i3-f7-m1--rename-featureplan-issue-command-to-plan-issue-in-cli-routing) — all prior issues should be completed before doc updates
- [.agents/protocols/task-execution-protocol.md](.agents/protocols/task-execution-protocol.md) — command/feature planning flow section
- [.agents/protocols/feature-planning-protocol.md](.agents/protocols/feature-planning-protocol.md) — planning quality gates section
- [.agents/workflows/plan-feature.md](.agents/workflows/plan-feature.md) — feature planning workflow procedure
- [.agents/workflows/plan-issue.md](.agents/workflows/plan-issue.md) — issue planning workflow procedure

#### Decomposition
1. Update `task-execution-protocol.md` Section "Feature planning/materialization flow":
   - Clarify `plan feature <id>` purpose: initialize Feature Execution Order + Dependencies + Decomposition + Assessment (feature-level only; no issue plans)
   - Issue plans are invoked separately: `plan issue <id>` with optional `--input <draft_file>` for each issue
   - Add step for batch-issue workflow: `plan issue --input <draft_file>` for each feature issue (enables F6-M1 parser-based insertion)
   - Add new command: `validate issue <id>` validates issue plan and transitions Pending → Planned
   - Update status gate contract: `plan tasks for issue` requires Pending → Planned transition (via validate command)

2. Update `feature-planning-protocol.md` Section 3 (Planning Quality Gates):
   - Remove references to "decomposition state" from Gate 0 (status tracking is DEV_MAP, not plans)
   - Update Gate A/Gate B to reference validate gate explicitly
   - Remove any `"planning"` / `"tasked"` status terminology from planning protocol; keep in task-execution-protocol only

3. Update `plan-feature.md` procedure:
   - Clarify purpose: `plan feature <id>` initializes **feature-level structure only** (Issue Execution Order, Dependencies, Decomposition, Assessment)
   - Per-issue planning is **separate concern**: after `plan feature` completes, loop over issues with `plan issue --input <draft> --id <issue_id>`
   - Document batch-planning pattern: agents generate drafts to `tmp/workflow/`, then loop with `plan issue --input` for each issue
   - Add Phase 5 step: validate all issues with loop: `validate issue --id <issue_id> --write` to approve plans

4. Update `plan-issue.md` procedure:
   - Replace Phase 4 (Execute CLI) to reflect `plan issue --input <draft_file>` workflow (parser from F6-M1)
   - Add reference to validation as separate step: `validate issue --id <issue_id> --write`
   - Document plan-vs-validate split (plan = insertion to FEATURE_PLANS, validate = approval + Pending→Planned status transition)

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
  1. Update task-execution-protocol.md with validate command, rename plan-issue, document --input
  2. Update feature-planning-protocol.md to remove status terminology, align gates with validate
  3. Update plan-feature.md and plan-issue.md with new command sequence and draft-file workflow
  4. Smoke/validation: grep-check for old `feature plan-issue` naming, verify no references remain

## F8-M1

### Issue Execution Order
1. `I1-F8-M1` - Add explicit materialize feature scope for feature-level GitHub issue create and sync
2. `I2-F8-M1` - Add explicit materialize issue scope for issue-level create and sync flows
3. `I3-F8-M1` - Align CLI help, workflow docs, and legacy compatibility for explicit materialize scopes

### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — current feature materialize router, feature create GitHub wiring, and mode handlers to refactor
- [dev/workflow_lib/cli.py](dev/workflow_lib/cli.py) — top-level CLI tree and help output path for command-surface changes
- [dev/workflow_lib/github_adapter.py](dev/workflow_lib/github_adapter.py) — GitHub create/edit primitives reused by new feature and issue materialize scopes
- [.agents/workflows/materialize-feature.md](.agents/workflows/materialize-feature.md) — workflow documentation that currently describes only the old feature-scoped materialize entrypoint
- [dev/TASK_EXECUTION_PIPELINE.json](dev/TASK_EXECUTION_PIPELINE.json) — existing materialize overlaps in F4-M1 (`74`, `78`, `94`, `95`) that define the current command contract and compatibility risks
- Existing feature-level materialization behavior in `feature create --github` is prerequisite context; new command shape must not regress already mapped feature issue updates
- Existing issue-level `bootstrap|issues-create|issues-sync` behavior is prerequisite context; refactor must preserve deterministic GitHub side effects during migration

### Decomposition
1. Define the target command surface and scope ownership:
   - Decide the canonical command model for feature-level and issue-level materialization so each command maps to one entity scope
   - Specify `create` versus `sync` semantics for both scopes, including whether `sync` updates only mapped nodes or also creates missing remote mappings
   - Define backward-compatibility behavior for legacy `feature materialize --mode bootstrap|issues-create|issues-sync`
   - Expected result: one unambiguous command contract exists before code changes begin

2. Refactor runtime materialization handlers around explicit scopes:
   - Extract feature-level materialization behavior from `feature create --github` into an explicit materialize path for the feature issue itself
   - Introduce issue-level materialize entrypoints that operate on one issue ID or a feature-owned issue set with deterministic create/sync behavior
   - Keep milestone resolution, GitHub retry policy, branch linkage, and output payloads stable across the refactor
   - Expected result: runtime code paths cleanly separate feature issue materialization from child issue materialization

3. Align CLI help, migration behavior, and process docs:
   - Update parser help, examples, and error messages so command discovery matches the new scope model
   - Update workflow/protocol docs to explain the new commands and remove hidden feature issue materialization semantics
   - Decide whether legacy commands remain as aliases, emit guided errors, or are removed entirely, and document that policy consistently
   - Expected result: users can discover the new command model directly from `--help` and workflow docs without reading implementation code

4. Validate the refactor end-to-end:
   - Run `feature plan-lint` for plan quality, then implement task decomposition later from the approved issue split
   - During execution phase, require regression coverage for feature issue create/sync, issue create/sync, and any legacy redirect or rejection path
   - Confirm no command path silently mixes feature-issue and child-issue side effects after the refactor
   - Expected result: the command model is testable, migration-safe, and ready for later task decomposition
    

### Issue/Task Decomposition Assessment
- Feature scope should split into three sequential issues because command semantics, runtime behavior, and migration/docs concerns are separable but dependent
- Planned issue order is minimal-sufficient:
  1. define explicit feature-level materialization scope,
  2. define explicit issue-level materialization scope on top of that command model,
  3. align help/docs/compatibility after the new runtime behavior is clear
- Expected follow-up: `plan issue I1-F8-M1`, `plan issue I2-F8-M1`, and `plan issue I3-F8-M1`, then `plan tasks for F8-M1` after issue plans are reviewed

### I1-F8-M1 - Add explicit materialize feature scope for feature-level GitHub issue create and sync

#### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — `_handle_feature_create`, `_materialize_feature_registration_issue`, and feature issue body sync behavior
- [dev/workflow_lib/github_adapter.py](dev/workflow_lib/github_adapter.py) — `gh_issue_create` and `gh_issue_edit` feature issue calls
- [dev/map/DEV_MAP.json](dev/map/DEV_MAP.json) — feature-level `gh_issue_number` and `gh_issue_url` are the local source of truth for feature issue mapping
- Current behavior in `feature create --github` must be preserved or migrated cleanly so existing feature registration flow does not regress

#### Decomposition
1. Audit current feature-level materialization behavior:
   - Trace how `feature create --github` creates or updates the feature-level GitHub issue
   - Trace how `issues-sync` updates feature issue body when the feature issue is already mapped
   - Identify all output payload fields and local state mutations tied to feature issue mapping
   - Expected result: current feature issue create/update semantics are fully cataloged

2. Define the new explicit feature-scope command contract:
   - Introduce a materialize command path that targets the feature entity itself rather than child issues
   - Define `create` behavior for unmapped feature issues and `sync` behavior for mapped feature issues
   - Define failure-path behavior for mismatched milestone, missing feature node, and invalid sync-on-unmapped cases if sync is strict
   - Expected result: one explicit feature materialize contract replaces hidden feature issue behavior

3. Refactor runtime implementation:
   - Move feature issue create/update logic behind the new feature-scope materialize handler
   - Keep branch linkage persistence and deterministic output fields intact
   - Preserve idempotency so repeated `create` or `sync` runs do not corrupt `DEV_MAP` mappings or duplicate GitHub issues
   - Expected result: feature issue materialization is discoverable, explicit, and behaviorally stable

4. Define acceptance and regression coverage:
   - Success path: create feature issue when unmapped
   - Success path: sync feature issue title/body/milestone when mapped
   - Failure path: invalid feature ID or invalid materialize mode reports deterministic output
   - Expected result: later task decomposition can split runtime refactor and regression checks cleanly

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
  1. audit current feature issue materialize behavior and output contract
  2. implement explicit feature-scope create/sync handler path
  3. preserve branch linkage and idempotent mapping behavior
  4. add regression coverage for feature issue create/sync paths

### I2-F8-M1 - Add explicit materialize issue scope for issue-level create and sync flows

#### Dependencies
- [I1-F8-M1](#i1-f8-m1--add-explicit-materialize-feature-scope-for-feature-level-github-issue-create-and-sync) — feature-level scope should be explicit before child issue commands are redesigned
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — current `bootstrap|issues-create|issues-sync` handlers, issue queue logic, and materialize status gates
- [dev/workflow_lib/github_adapter.py](dev/workflow_lib/github_adapter.py) — issue create/edit adapters and sub-issue reconciliation helpers
- [dev/TASK_EXECUTION_PIPELINE.json](dev/TASK_EXECUTION_PIPELINE.json) — current F4 materialize tasks and overlaps define existing issue-mode guarantees that must be preserved or intentionally replaced

#### Decomposition
1. Audit current issue-level materialization behavior:
   - Trace `issues-create` and `issues-sync` behavior for mapped versus unmapped issues
   - Trace `--issue-id` queue logic, gating rules, and output payload differences
   - Identify exactly which parts are truly issue-scoped and which parts are residual feature-scoped behavior
   - Expected result: the current issue materialize contract is explicit enough to redesign safely

2. Define the new issue-scope command contract:
   - Introduce an explicit issue-level materialize path that targets one issue or a feature-owned issue set
   - Define `create` behavior for unmapped issues and `sync` behavior for mapped issues, including whether sync may create missing mappings
   - Define deterministic failure behavior for invalid issue ownership, terminal status, missing mappings, and queue misuse
   - Expected result: issue create/sync semantics are clear and no longer hidden behind feature-scoped mode names

3. Refactor issue materialize runtime:
   - Move queue validation, scope resolution, and GitHub create/edit operations behind the new issue-scope command surface
   - Keep milestone assignment, retry policy, and deterministic output payloads stable
   - Preserve or explicitly replace sub-issue reconciliation behavior tied to the parent feature issue
   - Expected result: issue materialization works through explicit issue-oriented commands without mixing feature issue semantics

4. Define acceptance and regression coverage:
   - Success path: create one unmapped issue
   - Success path: sync one mapped issue
   - Batch path: run issue materialization for all issues owned by one feature
   - Expected result: later task decomposition can separate parser/routing work from regression checks and compatibility cases

#### Issue/Task Decomposition Assessment
- Expected split: 4 tasks
  1. audit and document current issue materialize scope behavior
  2. implement explicit issue-scope create/sync routing and validation
  3. preserve milestone/sub-issue/output contracts during refactor
  4. add regression coverage for single-issue and feature-owned issue-set flows

### I3-F8-M1 - Align CLI help, workflow docs, and legacy compatibility for explicit materialize scopes

#### Dependencies
- [I1-F8-M1](#i1-f8-m1--add-explicit-materialize-feature-scope-for-feature-level-github-issue-create-and-sync) and [I2-F8-M1](#i2-f8-m1--add-explicit-materialize-issue-scope-for-issue-level-create-and-sync-flows) — runtime command semantics must be settled before documentation and compatibility policy can be finalized
- [dev/workflow_lib/cli.py](dev/workflow_lib/cli.py) and [dev/workflow_lib/helpers/cli_format.py](dev/workflow_lib/helpers/cli_format.py) — help output path for new command descriptions/examples
- [.agents/workflows/materialize-feature.md](.agents/workflows/materialize-feature.md) — workflow text must match the new canonical command surface
- Planning and execution docs that reference materialization flow or feature issue mapping expectations

#### Decomposition
1. Update CLI help and examples:
   - Rewrite parser help text so feature-level and issue-level materialization are discoverable from `--help`
   - Add examples that show the new feature and issue commands directly instead of relying on hidden `feature create --github` semantics
   - Ensure multiline help remains readable under the shared compact formatter
   - Expected result: users can infer the command model from help output alone

2. Update workflow and protocol docs:
   - Rewrite `.agents/workflows/materialize-feature.md` and any linked planning/execution docs that still describe the old command model
   - Clarify how feature-level GitHub issue creation now fits into the lifecycle relative to child issue materialization
   - Keep materialization gates, milestone rules, and branch policy wording consistent with the runtime behavior
   - Expected result: canonical docs match the new CLI semantics without hidden exceptions

3. Define and implement compatibility policy:
   - Decide whether legacy `feature materialize --mode ...` paths stay as aliases, emit deprecation guidance, or fail with migration instructions
   - If aliases remain, keep output deterministic and clearly mark the canonical replacement
   - If aliases are removed, error text must point to the new command shape explicitly
   - Expected result: migration from the old command surface is predictable and documented

4. Define acceptance and regression coverage:
   - Verify help output, workflow docs, and runtime behavior all point to the same canonical commands
   - Add checks for any chosen alias or deprecation path
   - Ensure no stale docs/examples remain that instruct users to materialize feature issues through `feature create --github`
   - Expected result: users can adopt the new command model without reading implementation history

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
  1. update CLI help and examples for the new materialize model
  2. rewrite workflow/protocol docs to the new command surface
  3. implement alias/deprecation or rejection behavior for legacy commands
  4. add regression checks for help/docs/compatibility consistency
