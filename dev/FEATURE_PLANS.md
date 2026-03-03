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
1. `I1-F8-M1` - Add canonical action-first feature commands for create and materialize flows
2. `I2-F8-M1` - Add canonical action-first issue commands for create and materialize flows
3. `I3-F8-M1` - Unify workflow CLI routing, help, and docs around action-first grammar

### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — current feature-owned create/materialize handlers that need to move behind explicit action-first entrypoints
- [dev/workflow_lib/cli.py](dev/workflow_lib/cli.py) — top-level CLI tree and help output path for command-surface changes
- [dev/workflow_lib/github_adapter.py](dev/workflow_lib/github_adapter.py) — GitHub create/edit primitives reused by new feature and issue materialize scopes
- [.agents/workflows/create-feature.md](.agents/workflows/create-feature.md) and [.agents/workflows/materialize-feature.md](.agents/workflows/materialize-feature.md) — workflow docs that still assume entity-first command routing
- [dev/TASK_EXECUTION_PIPELINE.json](dev/TASK_EXECUTION_PIPELINE.json) — existing materialize overlaps in F4-M1 (`74`, `78`, `94`, `95`) and draft-input create flows in F6-M1 define the compatibility surface
- Existing feature-level behavior in `feature create --github` is prerequisite context; new command shape must not regress already mapped feature issue updates
- Existing issue-level behavior in `feature create-issue` and `feature materialize --mode bootstrap|issues-create|issues-sync` is prerequisite context; refactor must preserve deterministic GitHub side effects during migration

### Decomposition
1. Define the target command surface and scope ownership:
- Decide the canonical action-first command model for `create` and `materialize` across `feature` and `issue` entities
- Specify `create` versus `sync` semantics for both materialize scopes, including whether `sync` updates only mapped nodes or also creates missing remote mappings
- Define the direct canonical replacement for legacy `feature create`, `feature create-issue`, and `feature materialize --mode bootstrap|issues-create|issues-sync`
   - Expected result: one unambiguous action/entity command contract exists before code changes begin

2. Refactor runtime handlers around action-first routing:
   - Extract feature-level create and materialize behavior into explicit `create feature` and `materialize feature` entrypoints
   - Introduce issue-level `create issue` and `materialize issue` entrypoints that operate on one issue ID or a feature-owned issue set with deterministic create/sync behavior
   - Keep milestone resolution, GitHub retry policy, branch linkage, and output payloads stable across the refactor
   - Expected result: runtime code paths cleanly separate action routing from entity scope and remove hidden feature-owned issue commands

3. Align CLI help, migration behavior, and process docs:
   - Update parser help, examples, and error messages so command discovery matches the new action-first grammar
   - Update workflow/protocol docs to explain the new commands and remove hidden feature issue or issue-create semantics
   - Replace old command references with the new canonical commands instead of preserving compatibility shims
   - Expected result: users can discover the new command model directly from `--help` and workflow docs without reading implementation code

4. Validate the refactor end-to-end:
   - Run `feature plan-lint` for plan quality, then implement task decomposition later from the approved issue split
   - During execution phase, require regression coverage for feature create/materialize, issue create/materialize, and any legacy redirect or rejection path
   - Confirm no command path silently mixes feature-issue and child-issue side effects after the refactor
   - Expected result: the command model is testable, migration-safe, and ready for later task decomposition


### Issue/Task Decomposition Assessment
- Feature scope should split into three sequential issues because feature routing, issue routing, and help/docs alignment concerns are separable but dependent
- Planned issue order is minimal-sufficient:
  1. establish canonical action-first feature commands,
  2. establish canonical action-first issue commands on top of that routing model,
  3. align help/docs after the new runtime behavior is clear
- Expected follow-up: `plan issue I1-F8-M1`, `plan issue I2-F8-M1`, and `plan issue I3-F8-M1`, then `plan tasks for F8-M1` after issue plans are reviewed

### I1-F8-M1 - Add canonical action-first feature commands for create and materialize flows

#### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — current `feature create` handling, `_materialize_feature_registration_issue`, and feature issue body sync behavior
- [dev/workflow_lib/cli.py](dev/workflow_lib/cli.py) — top-level parser tree that currently exposes entity-first feature routing
- [dev/workflow_lib/github_adapter.py](dev/workflow_lib/github_adapter.py) — `gh_issue_create` and `gh_issue_edit` feature issue calls
- [dev/map/DEV_MAP.json](dev/map/DEV_MAP.json) — feature-level `gh_issue_number` and `gh_issue_url` are the local source of truth for feature issue mapping
- Current behavior in `feature create --github` must be preserved or migrated cleanly so existing feature registration flow does not regress during the action-first move

#### Decomposition
1. Audit current feature-level command behavior:
   - Trace how `feature create` registers the local feature and how `feature create --github` creates or updates the feature-level GitHub issue
   - Trace how feature issue state is updated during existing materialize and sync paths when the feature issue is already mapped
   - Identify all output payload fields and local state mutations tied to feature registration and feature issue mapping
   - Expected result: current feature create/materialize semantics are fully cataloged

2. Define the new action-first feature command contract:
   - Introduce canonical `create feature` and `materialize feature` command paths that target the feature entity directly
   - Define how local feature registration, feature issue creation, and feature issue sync are split between those entrypoints
   - Define failure-path behavior for missing feature node, mismatched milestone, and invalid sync-on-unmapped cases if sync is strict
   - Expected result: one explicit feature command contract replaces hidden feature issue behavior and entity-first create routing

3. Refactor runtime implementation:
   - Move feature registration and feature issue create/update logic behind the new action-first feature entrypoints
   - Keep branch linkage persistence and deterministic output fields intact
   - Preserve idempotency so repeated `create` or `sync` runs do not corrupt `DEV_MAP` mappings or duplicate GitHub issues
   - Expected result: feature create/materialize behavior is discoverable, explicit, and behaviorally stable

4. Define acceptance and regression coverage:
   - Success path: register feature through `create feature`
   - Success path: create or sync feature issue through `materialize feature`
   - Failure path: invalid feature ID or invalid materialize mode reports deterministic output
   - Expected result: later task decomposition can split routing refactor and regression checks cleanly

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
  1. audit current feature create/materialize behavior and output contract
  2. implement canonical action-first feature routing and handler path
  3. preserve branch linkage and idempotent mapping behavior
  4. add regression coverage for feature create/materialize paths

### I2-F8-M1 - Add canonical action-first issue commands for create and materialize flows

#### Dependencies
- [I1-F8-M1](#i1-f8-m1--add-canonical-action-first-feature-commands-for-create-and-materialize-flows) — feature-level action-first routing should be explicit before issue commands are redesigned
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — current `feature create-issue`, `bootstrap|issues-create|issues-sync` handlers, issue queue logic, and materialize status gates
- [dev/workflow_lib/cli.py](dev/workflow_lib/cli.py) — command-tree routing that currently nests issue creation under feature commands
- [dev/workflow_lib/github_adapter.py](dev/workflow_lib/github_adapter.py) — issue create/edit adapters and sub-issue reconciliation helpers
- [dev/TASK_EXECUTION_PIPELINE.json](dev/TASK_EXECUTION_PIPELINE.json) — current F4 materialize tasks and overlaps define existing issue-mode guarantees that must be preserved or intentionally replaced

#### Decomposition
1. Audit current issue-level command behavior:
   - Trace `feature create-issue` behavior for local issue registration and optional GitHub materialization
   - Trace `issues-create` and `issues-sync` behavior for mapped versus unmapped issues
   - Trace `--issue-id` queue logic, gating rules, and output payload differences
   - Identify exactly which parts are truly issue-scoped and which parts are residual feature-scoped behavior
   - Expected result: the current issue create/materialize contract is explicit enough to redesign safely

2. Define the new action-first issue command contract:
   - Introduce canonical `create issue` and `materialize issue` command paths that target one issue or a feature-owned issue set
   - Define `create` behavior for local issue registration versus remote issue creation, and `sync` behavior for mapped issues, including whether sync may create missing mappings
   - Define deterministic failure behavior for invalid issue ownership, terminal status, missing mappings, and queue misuse
   - Expected result: issue create/materialize semantics are clear and no longer hidden behind feature-scoped command names

3. Refactor issue runtime:
   - Move issue registration, queue validation, scope resolution, and GitHub create/edit operations behind the new action-first issue command surface
   - Keep milestone assignment, retry policy, and deterministic output payloads stable
   - Preserve or explicitly replace sub-issue reconciliation behavior tied to the parent feature issue
   - Expected result: issue create/materialize works through explicit issue-oriented commands without mixing feature issue semantics

4. Define acceptance and regression coverage:
   - Success path: register one issue through `create issue`
   - Success path: materialize or sync one issue through `materialize issue`
   - Batch path: run issue materialization for all issues owned by one feature if batch mode remains in scope
   - Expected result: later task decomposition can separate routing work from regression checks and compatibility cases

#### Issue/Task Decomposition Assessment
- Expected split: 4 tasks
  1. audit and document current issue create/materialize scope behavior
  2. implement canonical action-first issue routing and validation
  3. preserve milestone/sub-issue/output contracts during refactor
  4. add regression coverage for single-issue and feature-owned issue-set flows

### I3-F8-M1 - Unify workflow CLI routing, help, and docs around action-first grammar

#### Dependencies
- [I1-F8-M1](#i1-f8-m1--add-canonical-action-first-feature-commands-for-create-and-materialize-flows) and [I2-F8-M1](#i2-f8-m1--add-canonical-action-first-issue-commands-for-create-and-materialize-flows) — runtime command semantics must be settled before documentation and compatibility policy can be finalized
- [I1-F8-M1](#i1-f8-m1--add-canonical-action-first-feature-commands-for-create-and-materialize-flows) and [I2-F8-M1](#i2-f8-m1--add-canonical-action-first-issue-commands-for-create-and-materialize-flows) — runtime command semantics must be settled before documentation can be finalized
- [dev/workflow_lib/cli.py](dev/workflow_lib/cli.py) and [dev/workflow_lib/helpers/cli_format.py](dev/workflow_lib/helpers/cli_format.py) — help output path for new command descriptions/examples
- [.agents/workflows/create-feature.md](.agents/workflows/create-feature.md) and [.agents/workflows/materialize-feature.md](.agents/workflows/materialize-feature.md) — workflow text must match the new canonical command surface
- Planning and execution docs that reference create or materialization flow or feature issue mapping expectations

#### Decomposition
1. Update CLI help and examples:
   - Rewrite parser help text so feature-level and issue-level create/materialize flows are discoverable from `--help`
   - Add examples that show the new action-first feature and issue commands directly instead of relying on hidden `feature create --github` or `feature create-issue` semantics
   - Ensure multiline help remains readable under the shared compact formatter
   - Expected result: users can infer the command model from help output alone

2. Update workflow and protocol docs:
   - Rewrite `.agents/workflows/materialize-feature.md`, `.agents/workflows/create-feature.md`, and any linked planning/execution docs that still describe the old command model
   - Clarify how feature-level and issue-level GitHub issue creation now fit into the lifecycle relative to local registration and sync
   - Keep materialization gates, milestone rules, and branch policy wording consistent with the runtime behavior
   - Expected result: canonical docs match the new CLI semantics without hidden exceptions

3. Remove old command references from runtime and documentation:
   - Replace legacy `feature create`, `feature create-issue`, and `feature materialize --mode ...` references with the new canonical commands
   - Keep error text and examples pointed at the new command shape explicitly
   - Expected result: the runtime and docs present one command model instead of parallel legacy and canonical paths

4. Define acceptance and regression coverage:
   - Verify help output, workflow docs, and runtime behavior all point to the same canonical commands
   - Ensure no stale docs/examples remain that instruct users to use entity-first create/materialize paths
   - Expected result: users can adopt the new command model without reading implementation history

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
  1. update CLI help and examples for the new action-first command model
  2. rewrite workflow/protocol docs to the new command surface
  3. remove old command references from runtime/docs surfaces
  4. add regression checks for help/docs consistency

## F9-M1

### Issue Execution Order
1. `I1-F9-M1` - Remove feature plan artifacts during confirm feature only when closure is valid
2. `I2-F9-M1` - Add explicit child-issue cascade mode for confirm feature
3. `I3-F9-M1` - Define issue-scoped execution commit policy and workflow guidance

### Dependencies
- [dev/workflow_lib/confirm_commands.py](dev/workflow_lib/confirm_commands.py) — current confirm task/issue/feature handlers, cleanup helpers, and GitHub close flow
- [dev/FEATURE_PLANS.md](dev/FEATURE_PLANS.md) — feature and issue plan blocks that must be removed deterministically during confirm cleanup
- [.agents/rules/tracking-state.md](.agents/rules/tracking-state.md) — confirmation gating and subtree rules that constrain feature-level cascade behavior
- [.agents/workflows/confirm.md](.agents/workflows/confirm.md) — confirm command contract that must stay aligned with the runtime behavior
- GitHub issue close semantics and parent/sub-issue visibility rules constrain what commit linkage can realistically surface at the feature-issue level
- Existing `confirm issue done` cleanup behavior is prerequisite context; feature-level cleanup and cascade behavior should reuse it instead of reimplementing divergent rules

### Decomposition
1. Tighten feature-level confirm cleanup semantics:
   - Define when `confirm feature done` may remove the full feature section from `FEATURE_PLANS.md`
   - Require the default feature confirm path to succeed only when all child issues are already `Done`
   - Preserve deterministic dry-run output so users can preview plan/tracker cleanup before write mode
   - Expected result: feature-level close flow has explicit, non-ambiguous cleanup rules and no silent issue-state cascade

2. Add an explicit feature-level cascade mode for child issues:
   - Introduce one explicit flag for cascading child issue/task completion instead of overloading generic `--force`
   - Reuse issue cleanup semantics so child issue blocks are removed from `FEATURE_PLANS.md` and mapped GitHub issues are closed in one scripted flow
   - Define failure behavior for unmapped issues, already-done children, and mixed subtree states
   - Expected result: operators can intentionally close the full feature subtree in one command, while the default feature confirm path remains strict

3. Define issue-scoped execution commit policy:
   - Specify whether commit creation is optional or required during `execute issue`
   - Define commit message format tied to the owning issue and document what GitHub does and does not surface on child issues versus the parent feature issue
   - Keep commit behavior explicit and separate from confirm semantics so execution and closure stay independently controllable
   - Expected result: issue execution gains one documented commit contract without assuming unsupported GitHub aggregation behavior at the feature issue level

### Issue/Task Decomposition Assessment
- Feature scope should split into three sequential issues because cleanup semantics, explicit cascade behavior, and execution commit policy are related but should be implemented and validated independently
- Minimal execution order:
  1. lock strict `confirm feature` cleanup rules,
  2. add explicit subtree cascade mode on top of those rules,
  3. define and wire issue-scoped commit behavior after the closure contract is stable
- Expected commit-oriented split:
  - `I1-F9-M1`: 2-3 commits (cleanup contract, cleanup implementation, regression checks)
  - `I2-F9-M1`: 2-3 commits (CLI flag surface, cascade executor, regression checks)
  - `I3-F9-M1`: 2-4 commits (contract/docs, runtime hook if approved, workflow/docs/tests)

### I1-F9-M1 - Remove feature plan artifacts during confirm feature only when closure is valid

#### Dependencies
- [dev/workflow_lib/confirm_commands.py](dev/workflow_lib/confirm_commands.py) — current `confirm feature` path and issue-level cleanup helpers
- [dev/FEATURE_PLANS.md](dev/FEATURE_PLANS.md) — target artifact for feature-section removal
- [I2-F9-M1](#i2-f9-m1--add-explicit-child-issue-cascade-mode-for-confirm-feature) depends on this issue's cleanup contract and should not redefine feature-section deletion rules

#### Decomposition
1. Define the strict feature confirm contract:
   - Require default `confirm feature --id <feature_id> done` to proceed only when every child issue already has status `Done`
   - Define preview output fields for `FEATURE_PLANS` feature-section cleanup alongside existing `TASK_LIST` and pipeline cleanup previews
   - Expected result: default feature confirm behavior becomes explicit, non-cascading, and previewable

2. Implement feature-level `FEATURE_PLANS` cleanup:
   - Add helper logic that removes the full `## <feature_id>` section only when the closure preconditions are satisfied
   - Keep dry-run versus write-mode behavior deterministic and aligned with existing confirm cleanup payloads
   - Expected result: successful feature confirmation removes the feature plan section in the same write run as tracker cleanup

3. Add regression coverage and edge-case checks:
   - Cover blocked feature confirm when any child issue is not `Done`
   - Cover successful feature confirm cleanup when all child issues are already `Done`
   - Cover idempotent repeat behavior after section removal
   - Expected result: feature-level plan cleanup is stable and cannot silently bypass subtree state requirements

#### Issue/Task Decomposition Assessment
- Expected split: 3 tasks / commit slices
  1. define and validate strict `confirm feature` closure gate
  2. implement full feature-section cleanup in `FEATURE_PLANS`
  3. add regression and idempotency coverage

### I2-F9-M1 - Add explicit child-issue cascade mode for confirm feature

#### Dependencies
- [I1-F9-M1](#i1-f9-m1--remove-feature-plan-artifacts-during-confirm-feature-only-when-closure-is-valid) — strict non-cascading feature confirm behavior must be defined first
- [dev/workflow_lib/confirm_commands.py](dev/workflow_lib/confirm_commands.py) — confirm parser, feature confirm executor, and issue cleanup helpers
- [.agents/workflows/confirm.md](.agents/workflows/confirm.md) — command examples and lifecycle guidance must reflect the new explicit cascade mode

#### Decomposition
1. Define the explicit cascade command surface:
   - Choose one explicit flag name such as `--with-child-issues` instead of overloading `--force`
   - Define exactly which states transition in cascade mode: child tasks, child issues, feature node, `FEATURE_PLANS`, tracker cleanup, and GitHub closing
   - Expected result: subtree cascade behavior is discoverable and semantically distinct from the strict default path

2. Implement subtree cascade executor:
   - Reuse issue cleanup primitives so each child issue gets the same plan/tracker cleanup semantics as `confirm issue done`
   - Close mapped child GitHub issues and the feature GitHub issue in one controlled write run
   - Keep deterministic reporting for already-done children, unmapped children, and partial precondition failures
   - Expected result: one explicit feature confirm command can close the full subtree without hidden side effects

3. Add regression coverage and documentation:
   - Cover dry-run preview for cascade mode
   - Cover successful write-mode cascade over mixed not-yet-done child issues/tasks
   - Update confirm workflow docs so users understand the difference between strict feature confirm and explicit subtree cascade
   - Expected result: cascade semantics remain intentional, documented, and test-protected

#### Issue/Task Decomposition Assessment
- Expected split: 3 tasks / commit slices
  1. add explicit CLI flag and contract validation
  2. implement cascade executor with child issue cleanup and GitHub close flow
  3. add regression coverage and workflow documentation

### I3-F9-M1 - Define issue-scoped execution commit policy and workflow guidance

#### Dependencies
- [I1-F9-M1](#i1-f9-m1--remove-feature-plan-artifacts-during-confirm-feature-only-when-closure-is-valid) and [I2-F9-M1](#i2-f9-m1--add-explicit-child-issue-cascade-mode-for-confirm-feature) — execution commit policy should build on the finalized closure semantics rather than drift independently
- [.agents/workflows/execute-issue.md](.agents/workflows/execute-issue.md) and [.agents/workflows/execute-feature.md](.agents/workflows/execute-feature.md) — execution workflow docs that may need commit guidance
- GitHub issue/commit visibility behavior constrains what parent feature issues can display from child-issue-linked commits

#### Decomposition
1. Define commit policy contract:
   - Decide whether commit creation during `execute issue` is optional, required by explicit flag, or documentation-only for now
   - Define canonical commit message format tied to the issue identity (for example `<issue_id>: <summary>` or `#<gh_issue_number>: <summary>`)
   - Expected result: one issue-scoped commit contract exists before any runtime automation is added

2. Evaluate runtime integration points:
   - Inspect where `execute issue` could trigger explicit commit creation without hiding repository state changes from the user
   - Separate documentation-only guidance from actual CLI automation if automatic commits would be too risky by default
   - Expected result: the repository gets a defensible implementation decision instead of implicit commit side effects

3. Document GitHub visibility limits and test chosen behavior:
   - Document what linked commits or closing keywords do and do not surface on child issues and parent feature issues
   - If runtime support is added, cover explicit flag behavior and failure paths; if not, cover workflow/docs consistency
   - Expected result: users get accurate expectations about commit linkage and parent-feature visibility

#### Issue/Task Decomposition Assessment
- Expected split: 2-4 tasks / commit slices
  1. define commit policy and canonical message format
  2. decide and implement explicit runtime hook if warranted
  3. document GitHub visibility limits
  4. add regression or workflow checks for the chosen behavior

## F10-M1

### Issue Execution Order
1. `I1-F10-M1` - Add explicit publish command for feature GitHub issue creation
2. `I2-F10-M1` - Add explicit publish commands for child issues and feature-owned issue batches
3. `I3-F10-M1` - Rewrite help, workflows, and migration guidance around publish semantics

### Dependencies
- [dev/workflow_lib/cli.py](dev/workflow_lib/cli.py) — top-level command tree where the new publish grammar must become discoverable
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — current create/materialize feature and issue flows that need explicit publish-oriented entrypoints
- [dev/workflow_lib/github_adapter.py](dev/workflow_lib/github_adapter.py) — GitHub issue creation/update helpers and milestone validation primitives
- [.agents/workflows/create-feature.md](.agents/workflows/create-feature.md) and [.agents/workflows/materialize-feature.md](.agents/workflows/materialize-feature.md) — workflow docs that currently describe registration/materialize language instead of explicit publication semantics
- [dev/map/DEV_MAP.json](dev/map/DEV_MAP.json) — local source of truth for feature issue mappings, child issue mappings, and milestone ownership
- Existing create-vs-GitHub publication behavior must stay deterministic while the command surface is renamed and clarified
- Milestone assignment must remain automatic from local ownership; the new publish commands must not require redundant milestone input when the target is already mapped under `M1`

### Decomposition
1. Define explicit publish semantics for GitHub issue creation:
   - Replace ambiguous `materialize` terminology with commands that explicitly say they create GitHub issues
   - Separate local registration from remote publication so users can predict side effects from the command name alone
   - Keep milestone assignment automatic from the local ownership chain instead of asking the user to repeat milestone data
   - Expected result: users can read the command and immediately know it creates a GitHub issue

2. Refactor runtime around publish-oriented entity scopes:
   - Add publish flow for one feature issue, one issue, and one feature-owned issue batch
   - Preserve deterministic behavior for already-published targets, dry-run paths, and local mapping updates
   - Keep parent feature issue linkage semantics explicit for child issue publishing
   - Expected result: runtime behavior is clear for `feature issue`, `child issue`, and `all child issues of one feature`

3. Align help and workflow documentation with the new model:
   - Replace materialize-oriented examples with publish-oriented commands
   - Clarify which commands only register local nodes and which ones create remote GitHub issues
   - Document dry-run versus write behavior in terms of publication instead of abstract materialization
   - Expected result: command naming, help output, and workflows all describe one consistent publication model

### Issue/Task Decomposition Assessment
- Feature scope should split into three sequential issues because feature publication, child issue publication, and docs/help migration are related but should be implemented and validated independently
- Minimal execution order:
  1. establish feature issue publication command,
  2. establish child issue and issue-batch publication commands on top of that model,
  3. rewrite help/workflows after the runtime contract is settled
- Expected commit-oriented split:
  - `I1-F10-M1`: 2-3 commits (contract, runtime, regression checks)
  - `I2-F10-M1`: 3-4 commits (single issue publish, feature-owned issue batch publish, linkage behavior, tests)
  - `I3-F10-M1`: 2-3 commits (help/docs rewrite, migration text cleanup, regression checks)

### I1-F10-M1 - Add explicit publish command for feature GitHub issue creation

#### Dependencies
- [dev/workflow_lib/cli.py](dev/workflow_lib/cli.py) — top-level router where `publish feature` must become first-class
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — current feature-level GitHub issue create/sync logic that should be exposed under publish naming
- [dev/workflow_lib/github_adapter.py](dev/workflow_lib/github_adapter.py) — existing milestone validation and issue create/edit helpers reused by the new publish command

#### Decomposition
1. Define the `publish feature` contract:
   - Specify that the command creates the feature issue on GitHub and records local mapping state
   - Define deterministic create-only behavior for already published features versus not-yet-published features
   - Keep milestone assignment implicit from local ownership, not repeated as user input
   - Expected result: one explicit contract replaces ambiguous feature-level materialize wording

2. Implement runtime wiring for `publish feature`:
   - Route the new command to the existing feature issue creation/update primitives with publish-oriented output text
   - Preserve dry-run and write-mode behavior without hiding GitHub side effects
   - Keep branch linkage behavior separate from publication semantics unless explicitly required
   - Expected result: users can publish a feature issue with one clearly named command

3. Add regression coverage:
   - Cover dry-run preview for unpublished feature issues
   - Cover write-mode publication for unpublished features
   - Cover already-published feature behavior so repeat runs stay deterministic
   - Expected result: feature publication semantics remain stable during the command rename

#### Issue/Task Decomposition Assessment
- Expected split: 3 tasks / commit slices
  1. define feature publish contract and output semantics
  2. implement publish feature runtime path
  3. add regression coverage for dry-run, create, and repeat behavior

### I2-F10-M1 - Add explicit publish commands for child issues and feature-owned issue batches

#### Dependencies
- [I1-F10-M1](#i1-f10-m1--add-explicit-publish-command-for-feature-github-issue-creation) — feature-level publish semantics should be explicit first
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — current issue and issue-batch materialize behavior that must be replaced with publish naming
- [dev/map/DEV_MAP.json](dev/map/DEV_MAP.json) — issue ownership and milestone lineage that drive publication targets

#### Decomposition
1. Define `publish issue` and `publish issues --feature-id` contracts:
   - Support one explicit command for a single issue and one for all child issues under a feature
   - Define create behavior for unmapped issues and deterministic skip or error behavior for already published issues
   - Clarify how child issue publication relates to an existing parent feature issue mapping
   - Expected result: users can publish one child issue or the full child issue set without guessing command scope

2. Implement runtime publication paths:
   - Route single-issue and feature-owned issue-batch publication through the existing GitHub issue creation logic
   - Preserve milestone assignment from local ownership and queue-order behavior for batch publication
   - Keep deterministic output for selected issue IDs, created mappings, and skipped already-published issues
   - Expected result: issue publication works through explicit publish commands instead of materialize naming

3. Validate linkage and edge cases:
   - Cover feature-owned issue batch publish when the parent feature issue exists and when it does not
   - Define whether publication only creates issues or also reconciles parent/child linkage in the same run
   - Cover blocked invalid-owner or invalid-queue behavior
   - Expected result: child issue publication semantics are explicit and safe for batch use

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks / commit slices
  1. define single-issue and feature-owned issue-batch publish contracts
  2. implement publish issue runtime path
  3. implement publish issues batch path and linkage behavior
  4. add regression coverage for create/skip/error cases

### I3-F10-M1 - Rewrite help, workflows, and migration guidance around publish semantics

#### Dependencies
- [I1-F10-M1](#i1-f10-m1--add-explicit-publish-command-for-feature-github-issue-creation) and [I2-F10-M1](#i2-f10-m1--add-explicit-publish-commands-for-child-issues-and-feature-owned-issue-batches) — runtime command semantics must be finalized before docs can be rewritten
- [.agents/workflows/create-feature.md](.agents/workflows/create-feature.md) and [.agents/workflows/materialize-feature.md](.agents/workflows/materialize-feature.md) — workflow docs that need publish-oriented terminology
- CLI help output and any repository guidance that still uses materialize wording

#### Decomposition
1. Rewrite help output and examples:
   - Replace materialize-oriented examples with `publish feature`, `publish issue`, and `publish issues` examples
   - Make the local-registration versus GitHub-publication split obvious from `--help`
   - Expected result: users can discover the right publish command directly from help text

2. Update workflow and migration documentation:
   - Rewrite workflow docs so local creation and GitHub publication are described as separate lifecycle steps
   - Document milestone behavior, dry-run behavior, and parent-feature versus child-issue publication paths in publish terminology
   - Expected result: operator guidance matches the new command surface without legacy ambiguity

3. Add regression checks and clean up legacy wording:
   - Ensure help and docs no longer present `materialize` as the canonical way to create GitHub issues
   - Keep compatibility or migration notes explicit if any old command remains temporarily supported
   - Expected result: the repository exposes one clear publish-oriented model for GitHub issue creation

#### Issue/Task Decomposition Assessment
- Expected split: 2-3 tasks / commit slices
  1. rewrite help/examples for publish commands
  2. rewrite workflows and migration guidance
  3. add regression checks for help/docs consistency

## F11-M1

### Issue Execution Order
1. `I1-F11-M1` - Define and persist milestone-level feature execution order structure
2. `I2-F11-M1` - Integrate feature execution order maintenance into planning and sync flows
3. `I3-F11-M1` - Clean feature execution order on confirm and document milestone planning semantics

### Dependencies
- [dev/FEATURE_PLANS.md](dev/FEATURE_PLANS.md) — target document that must gain a milestone-scoped feature execution order block near the top of the file
- [dev/map/DEV_MAP.json](dev/map/DEV_MAP.json) — feature ownership and milestone lineage used to infer where execution-order entries belong
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — `plan feature`, `plan tasks`, and plan-status reconciliation logic that may need new structure awareness
- [dev/workflow_lib/confirm_commands.py](dev/workflow_lib/confirm_commands.py) — feature confirmation cleanup path that should remove completed feature entries from the execution-order block
- [dev/map/ISSUE_CREATE_INPUT_SCHEMA.md](dev/map/ISSUE_CREATE_INPUT_SCHEMA.md) and adjacent planning contracts — likely touchpoints if planning artifacts or delta payloads need to carry recommended feature ordering explicitly
- `.agents/workflows/plan-feature.md`, `.agents/workflows/plan-tasks-for.md`, and `.agents/workflows/confirm.md` — workflows that must describe when execution-order entries are created, maintained, and removed
- The new block should be planning-owned, not registration-owned; features that are only created but not planned should not appear in the recommended execution order

### Decomposition
1. Define the milestone-level feature execution order contract:
   - Add one canonical block near the beginning of `FEATURE_PLANS.md` that stores recommended feature execution order grouped by milestone
   - Make the block planning-owned so only planned features appear there, not every newly registered feature
   - Define how feature IDs, titles, and ordering are represented, and how empty milestone sections behave
   - Expected result: the repository has one authoritative planning artifact for milestone-scoped feature execution order

2. Integrate execution-order maintenance into planning flows:
   - Update planning commands and any related delta/schema contracts so the new block is inserted or updated when a feature plan is created or revised
   - Keep ordering deterministic and safe when a feature is replanned, moved within the recommendation order, or added after other planned features already exist
   - Clarify whether order is user-authored, auto-appended, or partially derived from dependencies at planning time
   - Expected result: feature planning automatically keeps the milestone execution-order block consistent

3. Clean up execution-order entries during confirmation:
   - Remove a feature from the milestone execution order when `confirm feature done` succeeds
   - Keep dry-run versus write-mode cleanup visible in the confirm output contract
   - Ensure milestone execution-order cleanup stays consistent with other planning/tracker cleanup behavior
   - Expected result: completed features no longer remain in the recommended execution queue

### Issue/Task Decomposition Assessment
- Feature scope should split into three sequential issues because structure definition, planning integration, and confirm cleanup are tightly related but need different code paths and validation surfaces
- Minimal execution order:
  1. define the global milestone execution-order structure and any supporting schema changes,
  2. wire that structure into planning/sync flows,
  3. remove completed features from the order during confirm and document the lifecycle
- Expected commit-oriented split:
  - `I1-F11-M1`: 2-3 commits (structure contract, parser/schema support, tests)
  - `I2-F11-M1`: 3-4 commits (planning insertion/update logic, delta/schema flow updates, tests)
  - `I3-F11-M1`: 2-3 commits (confirm cleanup, workflow/docs updates, regression checks)

### I1-F11-M1 - Define and persist milestone-level feature execution order structure

#### Dependencies
- [dev/FEATURE_PLANS.md](dev/FEATURE_PLANS.md) — target file that must gain the new canonical top-level block
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — parsing and lint logic that will need to understand the added structure
- [dev/map/ISSUE_CREATE_INPUT_SCHEMA.md](dev/map/ISSUE_CREATE_INPUT_SCHEMA.md) and adjacent planning contracts if a formal schema or delta payload is chosen for order metadata

#### Decomposition
1. Define the top-level milestone execution-order format:
   - Introduce one canonical block near the top of `FEATURE_PLANS.md`, for example `## Milestone Feature Execution Order` with per-milestone sub-sections
   - Define row format for ordered features: feature ID, feature title, and stable numbering
   - Decide whether milestones without planned features are omitted or retained as empty sections
   - Expected result: the file structure is explicit and parseable before any runtime code is changed

2. Add parser/lint support for the new block:
   - Extend plan parsing and validation code so the added top-level block does not conflict with feature sections
   - If planning delta or schema artifacts need to reference feature-order metadata, extend those contracts explicitly
   - Keep failure behavior deterministic when the block is malformed
   - Expected result: the new structure is safe to parse, lint, and evolve

3. Add regression coverage for structure handling:
   - Cover valid execution-order block parsing and malformed-block rejection where appropriate
   - Ensure existing feature plan sections remain lint-clean when the new global block is present
   - Expected result: the new top-level structure is stable enough for later planning integration

#### Issue/Task Decomposition Assessment
- Expected split: 2-3 tasks / commit slices
  1. define canonical milestone execution-order block format
  2. update parser/lint/schema handling
  3. add regression coverage for structure validity

### I2-F11-M1 - Integrate feature execution order maintenance into planning and sync flows

#### Dependencies
- [I1-F11-M1](#i1-f11-m1--define-and-persist-milestone-level-feature-execution-order-structure) — the top-level structure must exist before planning can maintain it
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — `feature plan-init`, `feature plan-lint`, and planning reconciliation logic
- `.agents/workflows/plan-feature.md` and `.agents/protocols/feature-planning-protocol.md` — planning-stage ownership for when features enter the recommended execution order

#### Decomposition
1. Define planning-stage insertion/update semantics:
   - Make `plan feature <id>` the owning step that inserts a feature into the milestone execution-order block
   - Define whether new planned features are appended by default or inserted according to explicit dependency reasoning
   - Keep unplanned-but-created features out of the execution order
   - Expected result: the planning lifecycle clearly owns the presence of feature entries in the order block

2. Implement planning and sync integration:
   - Update plan initialization or plan write flows so the milestone order block is created or updated when a feature plan is authored
   - If planning uses delta files or schema-backed payloads for ordering metadata, update those inputs so recommended order can be carried explicitly
   - Keep order updates deterministic under repeated planning runs
   - Expected result: planned features appear in the recommended milestone execution order automatically and consistently

3. Add regression coverage and edge-case handling:
   - Cover first planned feature in a milestone, later appended feature, and repeat planning of an existing feature
   - Cover ordering updates when titles change or when replanning should preserve prior order
   - Expected result: planning integration behaves predictably under real workflow usage

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks / commit slices
  1. define planning ownership and insertion rules
  2. implement order maintenance in plan flows
  3. update delta/schema contracts if needed
  4. add regression coverage for append/replan cases

### I3-F11-M1 - Clean feature execution order on confirm and document milestone planning semantics

#### Dependencies
- [I1-F11-M1](#i1-f11-m1--define-and-persist-milestone-level-feature-execution-order-structure) and [I2-F11-M1](#i2-f11-m1--integrate-feature-execution-order-maintenance-into-planning-and-sync-flows) — confirm cleanup should operate on the finalized structure and planning ownership model
- [dev/workflow_lib/confirm_commands.py](dev/workflow_lib/confirm_commands.py) — feature confirm path that must remove completed features from the order block
- `.agents/workflows/confirm.md`, `.agents/workflows/plan-feature.md`, and related planning docs — lifecycle guidance that must explain when entries are added and removed

#### Decomposition
1. Define confirm cleanup behavior:
   - Remove a feature’s row from the milestone execution-order block only when `confirm feature done` succeeds
   - Define dry-run preview fields and write-mode cleanup results for the new block alongside existing tracker cleanup output
   - Expected result: feature completion removes the feature from the recommended execution queue deterministically

2. Implement runtime cleanup:
   - Extend confirm cleanup helpers so milestone execution-order entries are removed in the same write run as other planning artifacts
   - Handle empty milestone sections consistently after removal
   - Expected result: confirm feature keeps the milestone execution-order block pending-only and free of completed features

3. Update workflow docs and regression checks:
   - Document that planning adds entries and confirm removes them
   - Cover dry-run and successful cleanup behavior in tests
   - Expected result: milestone execution-order lifecycle is documented and protected against regressions

#### Issue/Task Decomposition Assessment
- Expected split: 2-3 tasks / commit slices
  1. define confirm cleanup contract for the new order block
  2. implement runtime removal and empty-section handling
  3. add docs and regression checks for planning/confirm lifecycle
