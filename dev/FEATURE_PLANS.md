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
1. `I1-F7-M1` - Introduce Draft planning status and validate issue/feature transitions
2. `I2-F7-M1` - Wire --input argument to plan issue command for markdown draft parsing
3. `I3-F7-M1` - Add canonical status/plan CLI surface and remove legacy feature.plan-issue path
4. `I4-F7-M1` - Update task-execution-protocol and workflow docs for Pending→Draft→Planned lifecycle

### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — current issue-planning handlers, DEV_MAP write paths, and legacy `feature plan-issue` surface
- [dev/workflow_lib/cli.py](dev/workflow_lib/cli.py) — top-level CLI tree for `plan`, `validate`, and `status`
- [dev/workflow_lib/validate_commands.py](dev/workflow_lib/validate_commands.py) — existing validate surface to extend with issue/feature validation
- [dev/workflow_lib/markdown_parser.py](dev/workflow_lib/markdown_parser.py) — parser from F6-M1 for `--input <draft_file>` flows
- [dev/workflow_lib/errors.py](dev/workflow_lib/errors.py) — `WorkflowCommandError` for deterministic lifecycle and validation failures
- [.agents/protocols/task-execution-protocol.md](.agents/protocols/task-execution-protocol.md) — execution and planning lifecycle standards
- [.agents/protocols/feature-planning-protocol.md](.agents/protocols/feature-planning-protocol.md) — Gate 0 and planning-gate wording
- [.agents/workflows/plan-feature.md](.agents/workflows/plan-feature.md) and [plan-issue.md](.agents/workflows/plan-issue.md) — workflow procedures that must align with runtime behavior
- `dev/FEATURE_PLANS.md` — issue plan blocks written during draft planning
- `dev/map/DEV_MAP.json` — source of truth for lifecycle status (`Pending`, `Draft`, `Planned`, `Tasked`)

### Decomposition
1. Introduce explicit planning lifecycle states `Pending -> Draft -> Planned -> Tasked` so plan creation and plan approval are separate operations.
2. Make `plan issue` write or update draft issue plans, including parser-backed `--input` flows, without silently promoting status to `Planned`.
3. Consolidate the CLI around canonical top-level `plan issue`, `validate issue|feature`, and cheap `status issue|feature` commands while deleting the legacy `feature plan-issue` path.
4. Rewrite protocol and workflow docs so `plan feature` remains a useful cascading planning command that can draft child issues without contradicting single-issue planning and validation flows.

### Issue/Task Decomposition Assessment
- Decomposition splits into four sequential issues: I1 defines the lifecycle contract, I2 makes draft creation practical, I3 exposes the canonical command surface, and I4 rewrites the workflow/protocol text around the final model.
- Expected outcome: agents and scripts can determine planning state from status alone, inspect it with low-token `status` commands, and distinguish between draft plan insertion and validated plan approval.
- Dependency note: I2-F7-M1 depends on the markdown parser from F6-M1, while I3-F7-M1 depends on I1 and I2 so the new CLI exposes the finalized lifecycle rather than an intermediate contract.

### I1-F7-M1 - Introduce Draft planning status and validate issue/feature transitions

#### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — shared DEV_MAP mutation helpers and current planning-related handlers
- [dev/workflow_lib/validate_commands.py](dev/workflow_lib/validate_commands.py) — extend validate surface with entity-specific commands
- [dev/workflow_lib/errors.py](dev/workflow_lib/errors.py) — deterministic validation and bad-state errors
- [.agents/protocols/feature-planning-protocol.md](.agents/protocols/feature-planning-protocol.md) — Gate 0 quality requirements
- `dev/FEATURE_PLANS.md` — issue-plan blocks to validate
- `dev/map/DEV_MAP.json` — issue and feature node storage for lifecycle status writes

#### Decomposition
1. Introduce new planning status semantics in DEV_MAP:
   - `Pending` means no draft plan has been recorded yet
   - `Draft` means a plan block exists but has not passed validation
   - `Planned` means the draft passed validation and is eligible for task decomposition
   - Keep downstream `Tasked` semantics unchanged

2. Implement entity-specific validation commands:
   - `validate issue --id <issue_id>` validates one issue plan block and transitions `Draft -> Planned`
   - `validate feature --id <feature_id>` validates all child issue plans in one pass and transitions validated children plus the parent feature to `Planned`
   - Reject validation for `Pending` issues with guidance to run `plan issue` or `plan feature` first

3. Enforce Gate 0 validation rules during validation:
   - issue-plan block exists and contains `#### Dependencies`, `#### Decomposition`, and `#### Issue/Task Decomposition Assessment`
   - `#### Decomposition` contains numbered top-level steps with concrete sub-points
   - `#### Issue/Task Decomposition Assessment` contains explicit next-step or task-split guidance
   - validation failures return deterministic actionable errors

4. Define deterministic output contract:
   - dry-run (`--write` absent) returns action `would-validate` plus the target status
   - commit (`--write` present) returns action `validated` and the updated `status`
   - payloads stay compact enough to support repeated scripted checks

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
1. Add `Draft` lifecycle support to DEV_MAP status helpers and validation preconditions.
2. Implement `validate issue` and `validate feature` handlers with Gate 0 checks.
3. Wire lifecycle transitions and edge-case handling for missing blocks, bad statuses, and ownership mismatches.
4. Add tests for `Pending -> Draft -> Planned` transitions and feature-level cascading validation.

### I2-F7-M1 - Wire --input argument to plan issue command for markdown draft parsing

#### Dependencies
- [I1-F7-M1](#i1-f7-m1--introduce-draft-planning-status-and-validate-issuefeature-transitions) — lifecycle semantics must exist before draft insertion behavior is finalized
- [I1-F6-M1](dev/FEATURE_PLANS.md#i1-f6-m1--implement-markdown-template-parser-for-cli-inputs) — markdown parser from F6-M1 must be available
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — canonical `plan issue` handler and argument parser
- [dev/workflow_lib/markdown_parser.py](dev/workflow_lib/markdown_parser.py) — `parse_feature_issue_template()` parser function

#### Decomposition
1. Extend CLI argument parsing for `plan issue`:
   - add optional `--input <file_path>` accepting a markdown draft file
   - keep explicit flag-based inputs (`--title`, `--description`, etc.) for non-file planning flows
   - reject mixed input modes with a deterministic mutual-exclusion error

2. Update `plan issue` handler logic:
   - if `args.input` is provided, parse the file through the F6-M1 parser and extract normalized values
   - if `args.input` is absent, continue using explicit CLI args
   - feed both modes into the same downstream plan-block generation path

3. Define draft-state write behavior:
   - successful plan insertion or update transitions `Pending -> Draft`
   - if the issue is already `Draft`, update the plan block without changing status
   - if the issue is already `Planned`, require explicit overwrite semantics or reject silent downgrades
   - parser errors propagate with original validation messages and exit codes

4. Define deterministic output contract:
   - both input modes return the same shape; only the source differs
   - return action `created-draft` or `updated-draft` based on the resulting block mutation
   - return resulting status explicitly as `Draft`

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
1. Extend parser/arg registration for `--input` in canonical `plan issue`.
2. Route parsed values and explicit args through one draft-generation path.
3. Add lifecycle tests for `Pending`, `Draft`, and `Planned` issue states.
4. Add integration smoke coverage and docs notes for both input modes.

### I3-F7-M1 - Add canonical status/plan CLI surface and remove legacy feature.plan-issue path

#### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — current legacy command registration and planning handlers
- [dev/workflow_lib/cli.py](dev/workflow_lib/cli.py) — top-level CLI routing
- [I1-F7-M1](#i1-f7-m1--introduce-draft-planning-status-and-validate-issuefeature-transitions) — lifecycle statuses must be settled before exposing `status`
- [I2-F7-M1](#i2-f7-m1--wire--input-argument-to-plan-issue-command-for-markdown-draft-parsing) — canonical `plan issue` semantics should be stable before final routing cleanup

#### Decomposition
1. Audit current planning command routing:
   - find every `feature.plan-issue` registration and reference in CLI/help/error paths
   - map all handlers and validation logic coupled to the old namespace
   - identify all call sites that should move to top-level `plan` and `status`

2. Implement canonical top-level command surface:
   - add `plan issue --id <issue_id>` as the only issue-planning entrypoint
   - add `status issue --id <issue_id>` and `status feature --id <feature_id>`
   - keep output intentionally compact for low-token polling and shell scripting

3. Define status output contract:
   - `status issue` returns minimal JSON like `{ "command": "status.issue", "issue_id": "<id>", "status": "Draft" }`
   - `status feature` returns minimal JSON like `{ "command": "status.feature", "feature_id": "<id>", "status": "Draft" }`
   - avoid extra derived fields unless they are required to disambiguate state

4. Remove the legacy path:
   - delete `feature plan-issue` registration and related code paths entirely
   - update help text and error messages to point to canonical commands
   - keep `plan feature` as a valid higher-level workflow; only the legacy issue-planning namespace is removed

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
1. Audit all command-registration points in `feature_commands.py` and `cli.py`.
2. Implement canonical `plan issue` and cheap `status issue|feature` routing.
3. Remove the old `feature plan-issue` path and align help/error text.
4. Add smoke tests for `plan issue --help`, `status issue`, `status feature`, and rejection of legacy syntax.

### I4-F7-M1 - Update task-execution-protocol and workflow docs for Pending→Draft→Planned lifecycle

#### Dependencies
- [I1-F7-M1](#i1-f7-m1--introduce-draft-planning-status-and-validate-issuefeature-transitions), [I2-F7-M1](#i2-f7-m1--wire--input-argument-to-plan-issue-command-for-markdown-draft-parsing), [I3-F7-M1](#i3-f7-m1--add-canonical-statusplan-cli-surface-and-remove-legacy-featureplan-issue-path) — doc updates should reflect the final runtime contract
- [.agents/protocols/task-execution-protocol.md](.agents/protocols/task-execution-protocol.md) — command and lifecycle flow sections
- [.agents/protocols/feature-planning-protocol.md](.agents/protocols/feature-planning-protocol.md) — planning quality gates
- [.agents/workflows/plan-feature.md](.agents/workflows/plan-feature.md) — feature planning workflow
- [.agents/workflows/plan-issue.md](.agents/workflows/plan-issue.md) — issue planning workflow

#### Decomposition
1. Update `task-execution-protocol.md`:
   - document the lifecycle `Pending -> Draft -> Planned -> Tasked`
   - document `status issue|feature` as the cheap lifecycle check surface
   - document `validate issue` and `validate feature` as explicit approval gates before task decomposition

2. Update `feature-planning-protocol.md`:
   - align gate terminology with `Draft` as the post-planning pre-validation state
   - clarify that status lives in DEV_MAP and plans are validated against Gate 0 before promotion to `Planned`
   - remove wording that implies plan existence must be inferred from markdown parsing instead of status

3. Update `plan-feature.md`:
   - keep `plan feature <id>` as a valid cascading planning command
   - define safe behavior when some child issues are already `Draft` or `Planned` so existing work is not blindly overwritten
   - document the batch pattern for drafting only missing issue plans, followed by `validate issue` or `validate feature`

4. Update `plan-issue.md`:
   - replace legacy `feature plan-issue` references with canonical `plan issue`
   - document the split between planning (`Draft`) and validation (`Planned`)
   - add a compact status-check step before and after validation

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
1. Rewrite protocol wording around `Draft` and explicit validate gates.
2. Update feature-planning protocol so Gate 0 and lifecycle text match runtime behavior.
3. Update `plan-feature.md` and `plan-issue.md` for cascading feature planning and compact status checks.
4. Add smoke validation for old `feature-only` planning claims and old `feature plan-issue` naming.

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

## F12-M1

### Issue Execution Order
1. `I1-F12-M1` - Define GitHub label and project-status sync contract
2. `I2-F12-M1` - Integrate metadata sync into publish, planning, validation, and confirmation flows
3. `I3-F12-M1` - Add docs, project-setup guidance, and regression coverage for GitHub metadata sync

### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — publish-oriented feature and issue flows that should create and update GitHub issue metadata after F10 removes `materialize` as the canonical surface
- [dev/workflow_lib/github_adapter.py](dev/workflow_lib/github_adapter.py) — GitHub API helpers for issue creation/editing and the likely integration point for labels and Project field updates
- [dev/workflow_lib/confirm_commands.py](dev/workflow_lib/confirm_commands.py) — confirm flows that should move GitHub Project status to `Done` and keep labels consistent during closure
- [dev/workflow_lib/cli.py](dev/workflow_lib/cli.py) — command tree where publish, plan, validate, and confirm entrypoints are exposed
- [dev/map/DEV_MAP.json](dev/map/DEV_MAP.json) — local source of truth for issue type, feature ownership, and workflow state that must map to GitHub metadata
- [dev/TASK_LIST.json](dev/TASK_LIST.json) and [dev/TASK_EXECUTION_PIPELINE.json](dev/TASK_EXECUTION_PIPELINE.json) — local task decomposition and execution state whose transitions may drive later GitHub metadata updates
- GitHub labels must remain structural (`feature`, `engine`, `client`, `workflow`) while GitHub Project `Status` must carry the workflow-state projection (`Pending -> Open`, `Draft/Planned/Tasked -> In progress`, `Done -> Done`)
- The implementation should assume the post-F10 command model: feature and issue publication happens through explicit `publish` commands, not through `materialize` as the canonical user-facing name

### Decomposition
1. Define the GitHub metadata sync contract:
   - Map local entity classification to labels such as `feature`, `engine`, `client`, and `workflow`
   - Map local workflow states to GitHub Project status values: `Pending -> Open`, `Draft/Planned/Tasked -> In progress`, `Done -> Done`
   - Define which transitions create metadata, which update metadata, and what happens when GitHub Project configuration is unavailable
   - Expected result: one explicit contract exists for labels versus Project status instead of ad hoc metadata mutations

2. Wire metadata sync into the workflow runtime:
   - Apply structural labels during publish-oriented GitHub issue creation
   - Update Project status during planning, validation, task decomposition, execution, and confirmation transitions
   - Keep repeated runs deterministic and avoid forcing metadata changes when the target GitHub issue or Project item is missing
   - Expected result: GitHub issue metadata reflects the local workflow lifecycle without replacing DEV_MAP as the source of truth

3. Document setup, fallback behavior, and regression expectations:
   - Describe required GitHub labels and the Project `Status` field configuration
   - Document fallback behavior when labels are missing or the issue is not attached to the configured Project
   - Add regression coverage for label assignment, Project status mapping, and no-op behavior on unsupported GitHub surfaces
   - Expected result: operators can configure the repo and understand exactly which local transitions do or do not sync to GitHub metadata

### Issue/Task Decomposition Assessment
- Feature scope should split into three sequential issues because contract definition, runtime integration, and docs/tests touch different layers and should be validated independently
- Minimal execution order:
  1. define the metadata mapping contract,
  2. wire publish and lifecycle transitions to that contract,
  3. document the required GitHub Project setup and lock behavior with tests
- Expected commit-oriented split:
  - `I1-F12-M1`: 2-3 commits (mapping contract, adapter contract, deterministic fallback semantics)
  - `I2-F12-M1`: 3-4 commits (publish label assignment, Project status updates across lifecycle transitions, repeat-run/idempotency handling, tests)
  - `I3-F12-M1`: 2-3 commits (docs/setup guidance, fallback behavior docs, regression checks)

### I1-F12-M1 - Define GitHub label and project-status sync contract

#### Dependencies
- [dev/workflow_lib/github_adapter.py](dev/workflow_lib/github_adapter.py) — likely home for reusable label and Project-field update primitives
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — publish-oriented feature and issue flows that will consume the metadata contract
- [dev/workflow_lib/confirm_commands.py](dev/workflow_lib/confirm_commands.py) — closure path that must map local `Done` to GitHub Project `Done`

#### Decomposition
1. Define structural label assignment:
   - Specify which issues receive labels such as `feature`, `engine`, `client`, and `workflow`
   - Decide whether multiple structural labels may coexist and how they are derived from local ownership or scope
   - Expected result: label semantics are explicit and stable before runtime code starts mutating GitHub issues

2. Define Project status mapping:
   - Map local workflow states to GitHub Project `Status` values: `Pending -> Open`, `Draft/Planned/Tasked -> In progress`, `Done -> Done`
   - Define exactly which commands are responsible for writing each transition (`publish`, `plan`, `validate`, `plan tasks`, `execute`, `confirm`)
   - Expected result: one canonical state projection exists from DEV_MAP to GitHub Project status

3. Define deterministic fallback behavior:
   - Specify behavior when the target GitHub labels do not exist, the issue is not attached to a Project item, or the Project does not expose the expected `Status` field
   - Keep fallback behavior explicit and non-destructive so local state remains authoritative
   - Expected result: runtime integration can fail safely without making metadata sync mandatory for core local workflow progression

#### Issue/Task Decomposition Assessment
- Expected split: 2-3 tasks / commit slices
  1. define structural label semantics
  2. define Project status mapping and command ownership
  3. define deterministic fallback behavior for missing GitHub metadata surfaces

### I2-F12-M1 - Integrate metadata sync into publish, planning, validation, and confirmation flows

#### Dependencies
- [I1-F12-M1](#i1-f12-m1--define-github-label-and-project-status-sync-contract) — metadata semantics must be explicit before runtime integration
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — publish, plan-issue, and plan-tasks flows that should trigger GitHub metadata updates
- [dev/workflow_lib/confirm_commands.py](dev/workflow_lib/confirm_commands.py) — confirm flows that should project `Done`
- [dev/workflow_lib/github_adapter.py](dev/workflow_lib/github_adapter.py) — helper layer for GitHub issue and Project metadata mutations

#### Decomposition
1. Add metadata sync on publish:
   - During `publish feature`, `publish issue`, and feature-owned issue-batch publish flows, assign the correct structural labels on the created GitHub issue
   - Attach or update the GitHub Project status as `Open` for newly published `Pending` work items
   - Expected result: publication creates GitHub issues with the right initial metadata shape

2. Add metadata sync on lifecycle transitions:
   - Update Project status to `In progress` when the local issue moves into `Draft`, `Planned`, or `Tasked`
   - Update Project status to `Done` during successful confirm flows
   - Decide whether `execute` should also touch Project status or only rely on the already-collapsed `In progress` state
   - Expected result: GitHub Project status follows the local workflow progression without introducing new local authority rules

3. Keep idempotency and partial-sync behavior deterministic:
   - Repeated runs should not duplicate labels or oscillate Project status unnecessarily
   - Missing GitHub issue mappings or missing Project items should degrade to explicit warnings or no-op metadata sync, not hard failures for local planning writes
   - Expected result: metadata sync stays safe across partial materialization and repeated command runs

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks / commit slices
  1. implement publish-time label assignment and initial Project status
  2. implement lifecycle-driven Project status updates
  3. add idempotent and partial-sync behavior
  4. add regression coverage for create/update/no-op cases

### I3-F12-M1 - Add docs, project-setup guidance, and regression coverage for GitHub metadata sync

#### Dependencies
- [I1-F12-M1](#i1-f12-m1--define-github-label-and-project-status-sync-contract) and [I2-F12-M1](#i2-f12-m1--integrate-metadata-sync-into-publish-planning-validation-and-confirmation-flows) — docs and tests must reflect the finalized runtime contract
- [.agents/workflows/create-feature.md](.agents/workflows/create-feature.md), [.agents/workflows/plan-issue.md](.agents/workflows/plan-issue.md), [.agents/workflows/plan-tasks-for.md](.agents/workflows/plan-tasks-for.md), and [.agents/workflows/confirm.md](.agents/workflows/confirm.md) — workflows that will need metadata-sync guidance
- any GitHub setup docs or operator notes describing repo labels and Project configuration

#### Decomposition
1. Document GitHub setup requirements:
   - Describe the required repository labels (`feature`, `engine`, `client`, `workflow`)
   - Describe the required GitHub Project `Status` field and the intended values `Open`, `In progress`, and `Done`
   - Expected result: operators know what must exist on GitHub before metadata sync can work end-to-end

2. Document runtime behavior and fallback rules:
   - Explain which commands write labels, which commands write Project status, and which local transitions remain local-only when GitHub metadata surfaces are unavailable
   - Clarify that DEV_MAP remains the source of truth even when GitHub metadata is stale or unavailable
   - Expected result: users can predict metadata side effects without reading implementation code

3. Add regression coverage and consistency checks:
   - Cover label assignment, Project status updates, and no-op or warning behavior when labels or Project metadata are unavailable
   - Keep workflow docs and runtime help aligned with the finalized metadata-sync contract
   - Expected result: GitHub metadata sync remains deterministic and documented after future command-surface changes

#### Issue/Task Decomposition Assessment
- Expected split: 2-3 tasks / commit slices
  1. document GitHub label and Project setup
  2. document runtime and fallback behavior
  3. add regression checks for metadata sync and docs consistency

## F13-M1

### Issue Execution Order
1. `I1-F13-M1` - Add canonical `workflow get context feature <id>` and `workflow get context issue <id>` commands
2. `I2-F13-M1` - Wire execute-feature workflow to use `workflow get context feature <id>` as the mandatory source
3. `I3-F13-M1` - Add post-reorg compatibility checks and regression tests for renamed command/script surfaces

### Dependencies
- Hard dependency: this feature is implemented only after `F7-M1`, `F9-M1`, `F10-M1`, `F11-M1`, and `F12-M1` are completed and merged.
- `F7-M1` is required first because planning/validation/status command surfaces are being reorganized and must be stable before this feature binds to them.
- `F10-M1` and `F12-M1` are required first because publish-oriented naming and metadata-sync lifecycle become canonical command surfaces consumed by execution workflows.
- `F11-M1` is required first because milestone-level execution-order planning structure affects how feature execution context is interpreted.
- `F9-M1` is required first because confirm/cleanup semantics define which plan and tracker blocks are considered active and should be returned by the collector.
- Runtime targets: `dev/workflow_lib/feature_commands.py`, `dev/workflow_lib/tracker_store.py`, `dev/workflow_lib/context.py`.
- Workflow/protocol targets: `.agents/workflows/execute-feature.md`, `.agents/workflows/execute-task.md`, `.agents/protocols/task-execution-protocol.md`.
- Tracking artifacts consumed by the collector: `dev/FEATURE_PLANS.md`, `dev/TASK_LIST.json`, `dev/TASK_EXECUTION_PIPELINE.json`, `dev/map/DEV_MAP.json`.

### Decomposition
1. Define canonical context commands under one namespace:
   - `workflow get context feature <feature_id>`,
   - `workflow get context issue <issue_id>`.
2. Ensure `workflow get context feature <feature_id>` returns:
   - full feature plan section block from `FEATURE_PLANS.md`,
   - all mapped task objects from `TASK_LIST.json` for the feature issue chain resolved through `DEV_MAP.json`,
   - overlap/intersection payload from `TASK_EXECUTION_PIPELINE.json` where overlap task IDs intersect with the feature task set.
3. Ensure `workflow get context issue <issue_id>` returns explicit issue-scoped context:
   - full issue plan block (`### <issue_id> - <issue_title>`) from the owning feature section in `FEATURE_PLANS.md`,
   - all mapped task objects for that issue from `TASK_LIST.json` resolved via `DEV_MAP.json`,
   - overlap/intersection payload from `TASK_EXECUTION_PIPELINE.json` where overlap task IDs intersect with the issue task set.
4. Make `execute feature <id>` and `execute issue <id>` workflows consume the new context commands as mandatory read sources instead of manual multi-file scanning.
5. Normalize command/help/workflow naming to the post-reorg canonical surfaces introduced by `F7/F10/F12` so the new context commands do not bind to legacy aliases.
6. Add deterministic validation and regression checks for context integrity, intersection detection, and failure messages on missing/invalid IDs.

### Issue/Task Decomposition Assessment
- Feature scope is split into three issues because data-aggregation runtime, workflow contract wiring, and post-reorg hardening must be validated independently.
- Minimal execution order:
  1. implement canonical context collector payload,
  2. make execute-feature workflow depend on it,
  3. lock behavior with post-reorg compatibility/regression checks.
- Expected commit-oriented split:
  - `I1-F13-M1`: 3-4 commits (payload contract, extractor implementation, deterministic error behavior, unit tests)
  - `I2-F13-M1`: 2-3 commits (workflow/protocol update, command-integration checks, output contract alignment)
  - `I3-F13-M1`: 2-3 commits (post-reorg naming audit, migration notes, regression coverage)

### I1-F13-M1 - Add canonical `workflow get context feature|issue <id>` commands

#### Dependencies
- `F7-M1` command-surface reorganization must be completed so this issue binds only to canonical plan/validate/status naming.
- `F11-M1` milestone execution-order structure must be stabilized so feature plan parsing and section resolution are deterministic.
- `dev/workflow_lib/feature_commands.py` — add the collector subcommand and shared resolvers.
- `dev/workflow_lib/tracker_store.py` and `dev/workflow_lib/context.py` — load canonical tracker payloads and paths.
- `dev/FEATURE_PLANS.md`, `dev/TASK_LIST.json`, `dev/TASK_EXECUTION_PIPELINE.json`, `dev/map/DEV_MAP.json` — primary data sources.

#### Decomposition
1. Define command contracts with compact deterministic JSON output:
   - `workflow get context feature <feature_id>`
   - `workflow get context issue <issue_id>`
2. Resolve feature ownership and tasks from `DEV_MAP.json`, then join mapped task IDs with full task objects from `TASK_LIST.json`.
3. Extract the full `## <feature_id>` block from `FEATURE_PLANS.md` as plain markdown text, including planned issue blocks.
4. Compute overlap intersections from `TASK_EXECUTION_PIPELINE.json`:
   - include overlap rows where `overlap.tasks ∩ feature_task_ids != empty`,
   - return both matched IDs and the full overlap row to keep debugging actionable.
5. Add issue-scoped collector path:
   - resolve owning feature + issue from `DEV_MAP.json`,
   - extract exact issue plan block from `FEATURE_PLANS.md`,
   - join issue task IDs with `TASK_LIST.json`,
   - compute issue-level overlap intersections from `TASK_EXECUTION_PIPELINE.json`.
6. Add deterministic error contract for missing feature/issue, malformed tracker payloads, and unresolved mapped task IDs.

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
  1. command registration and payload schema
  2. feature-task resolution and task-list join
  3. feature-plan block extraction and overlap-intersection collector
  4. error handling and unit tests

### I2-F13-M1 - Wire execute feature/issue workflows to consume `workflow get context ...`

#### Dependencies
- [I1-F13-M1](#i1-f13-m1--add-canonical-workflow-get-context-featureissue-id-commands) — collector output must exist first.
- `F10-M1` publish command model and `F12-M1` metadata-sync lifecycle must be canonical before workflow wording is frozen.
- `.agents/workflows/execute-feature.md` — execution procedure that currently describes manual multi-source reads.
- `.agents/workflows/execute-issue.md` — issue execution procedure that also needs collector-first read flow.
- `.agents/protocols/task-execution-protocol.md` and `.agents/workflows/execute-task.md` — read-order and per-task execution rules that must remain consistent.

#### Decomposition
1. Update execute-feature and execute-issue workflow steps so:
   - `workflow get context feature <id>` is mandatory for feature-chain execution,
   - `workflow get context issue <id>` is mandatory for issue-chain execution.
2. Define one explicit check that collector output includes:
   - non-empty relevant plan block (feature or issue),
   - resolved mapped tasks for all pending tasks in scope,
   - overlap intersections payload (empty list allowed, missing field not allowed).
3. Keep materialization/status gates unchanged; only replace data acquisition mechanism.
4. Add workflow examples with canonical command names only (no legacy aliases), including issue-scoped examples.

#### Issue/Task Decomposition Assessment
- Expected split: 2-3 tasks
  1. workflow/protocol text update for feature + issue collector-first read order
  2. execution gate checks against feature/issue collector payload completeness
  3. docs consistency checks for canonical command examples

### I3-F13-M1 - Add post-reorg compatibility checks and regression coverage

#### Dependencies
- `I1-F13-M1` and `I2-F13-M1` — runtime and workflow wiring must be complete first.
- `F9-M1` confirm cleanup behavior must be finalized so tests assert only active artifacts.
- `F10-M1`/`F12-M1` canonical naming and lifecycle must be finalized so tests reject stale command terms.
- Test targets: `tests/workflow/test_core.py`, `tests/workflow/test_feature_lifecycle.py`, and any workflow smoke harness that validates command help/output.

#### Decomposition
1. Add regression tests for collector output fields and intersection correctness on representative feature fixtures.
2. Add guard tests that fail on stale command names in execute-feature workflow instructions once post-reorg naming is active.
3. Add negative tests:
   - unknown feature ID,
   - feature with unresolved task references in DEV_MAP vs TASK_LIST,
   - malformed overlap row shape in pipeline payload.
4. Add migration notes describing this feature as blocked until `F7/F9/F10/F11/F12` are done.

#### Issue/Task Decomposition Assessment
- Expected split: 2-3 tasks
  1. runtime regression tests for collector payload and overlap intersections
  2. naming-surface regression checks for post-reorg command vocabulary
  3. negative/error-path coverage and migration-note consistency

## F14-M1

Issue-level overlaps-only planning workflow

### Issue Execution Order
1. `I9-F14-M1` - Remove feature plan section on confirm feature done

### Dependencies
- Depends on completion and stabilization of `F13-M1` context-command work because overlap-build workflow reuses issue/feature plan-block extraction and scoped planning surfaces.
- Runtime targets: `dev/workflow_lib/cli.py`, `dev/workflow_lib/feature_commands.py`, `dev/workflow_lib/confirm_commands.py`, `dev/workflow_lib/tracker_json_contracts.py`.
- Data/schema targets: `dev/ISSUE_OVERLAPS.json`, `dev/map/ISSUE_OVERLAPS_JSON_SCHEMA.json`, and dependency-index artifact (`dev/ISSUE_DEP_INDEX.json`).
- Workflow/rule targets: `.agents/workflows/plan-feature.md`, `.agents/workflows/plan-issue.md`, `.agents/workflows/plan-tasks-for.md`, `.agents/workflows/build-overlaps.md`, `.agents/rules/pipeline-constraints.md`.

### Decomposition
1. Introduce dependency-index and plan-block retrieval command surfaces so overlap analysis can stay scoped and avoid full-file context scans.
2. Move overlap storage to dedicated artifact (`dev/ISSUE_OVERLAPS.json`) with strict issue-level overlap contracts (`dependency | conflict | shared_logic`, optional `order: "A->B"` for dependency).
3. Add dedicated build/show/apply overlap command cycle and remove append-only overlap updates from legacy plan-tasks path.
4. Make `plan tasks for ...` consume issue-overlaps as read-only planning input, while confirmation commands perform deterministic overlap/index cleanup.
5. Remove overlap ownership from `TASK_EXECUTION_PIPELINE` and keep overlap lifecycle fully isolated in overlaps-only files.
6. Migrate all affected CLI and agent workflows (`plan-tasks`, `build-overlaps`, `confirm`, related read paths) to overlaps-only sources and explicitly remove overlap reads/writes via `TASK_EXECUTION_PIPELINE`.

### Issue/Task Decomposition Assessment
- Feature scope now has one remaining active issue (`I9-F14-M1`); previous issues are already complete and stay documented below only as historical plan records until feature-section cleanup is fixed.
- Current active execution order is `I9` only.
- Expected outcome: completed feature confirmation removes the obsolete feature section from `FEATURE_PLANS.md` deterministically, so no historical issue blocks remain after `confirm feature done`.

### I7-F14-M1 - Enforce strict Dependencies format for planning parser compatibility

#### Dependencies
- file: .agents/protocols/feature-planning-protocol.md | reason: canonical owner of planning content requirements
- file: .agents/workflows/plan-feature.md | reason: feature-planning workflow must require strict dependency lines
- file: .agents/workflows/plan-issue.md | reason: issue-planning workflow must require strict dependency lines
- function: dev/workflow_lib/feature_commands.py::_handle_feature_plan_lint | reason: plan-lint must enforce dependency-line format in issue blocks

#### Decomposition
1. Define strict one-line dependency token format for issue `#### Dependencies` entries:
   - `file: <repo/path.ext>`
   - `module: <module.name>`
   - `function: <repo/path.ext>::<symbol>`
   - `class: <repo/path.ext>::<ClassName>`
   - optional suffix `| reason: <text>`.
2. Update planning protocols/workflows so dependency lines without supported prefixes are invalid for newly drafted issue plans.
3. Add deterministic lint checks that reject free-form dependency prose and report offending issue/block line.
4. Ensure parser-facing normalization guidance is documented (trim rules, case handling for lookup keys, raw value preservation for display).
5. Add regression tests for valid dependency rows, invalid rows, and deterministic lint error messages.

#### Issue/Task Decomposition Assessment
- Expected split: 3 tasks
  1. protocol/workflow rule updates for strict dependency format
  2. lint enforcement implementation
  3. regression coverage for valid/invalid dependency lines

### I1-F14-M1 - Add dependency index and plan-block extraction CLI

#### Dependencies
- module: dev.workflow_lib.feature_commands | reason: existing feature and issue resolvers plus new plan command handlers live here
- file: dev/workflow_lib/cli.py | reason: command tree must expose index-dependencies, show-related, and get-plan-block
- file: dev/FEATURE_PLANS.md | reason: issue Dependencies blocks are the parser input source
- module: dev.workflow_lib.context | reason: dependency index artifact path must become part of canonical workflow context

#### Decomposition
1. Add command registration for canonical CLI commands in router:
   - `workflow plan index-dependencies [--feature-id <id> | --all] [--write]`
   - `workflow plan show-related --feature-id <id> | --issue-id <id>`
   - `workflow plan get-plan-block --feature-id <id> | --issue-id <id>`
   - keep deterministic parser failures for missing selector or mixed selectors.
2. Implement `Dependencies` parser for issue-plan blocks in `FEATURE_PLANS.md`:
   - resolve canonical issue heading `### I*-F*-M* - ...`,
   - read only `#### Dependencies` body for that issue block,
   - extract dependency surfaces from inline code tokens and file-style paths,
   - normalize surfaces (trim, lowercase for map-key, preserve original token for display payload).
3. Define and persist dependency index artifact (`dev/ISSUE_DEP_INDEX.json`) in deterministic shape:
   - `feature_scope`: scope used during index build (`all` or specific feature); needed so consumers can reject mismatched scope reads.
   - `by_issue`: `{ "<issue_id>": { "surfaces": [...], "feature_id": "...", "status": "..." } }`:
     - `surfaces`: normalized dependency targets extracted from issue `Dependencies`; needed as direct input for related-candidate discovery.
     - `feature_id`: owner feature of issue; needed for cross-feature vs same-feature filtering in overlap build.
     - `status`: current issue status snapshot; needed to skip terminal issues from overlap candidate sets when required by workflow.
   - `by_surface`: `{ "<surface_key>": { "surface": "...", "issue_ids": [...] } }`:
     - `surface_key`: normalized key used for search/join (so `Dev/Workflow_lib/Feature_Commands.py` and `dev/workflow_lib/feature_commands.py` map to one bucket).
     - `surface`: human-readable canonical form shown in command output/logs.
     - `issue_ids`: all issues touching same surface; needed to compute candidate related issues without scanning full plan text.
   - stable ordering for `issue_ids` and `surfaces` to keep diffs minimal and simplify review of index changes.
4. Define `workflow plan index-dependencies` scoped upsert behavior:
   - command supports `--feature-id <id>` and `--issue-id <id>` for partial index refresh, plus `--all` for full rebuild,
   - command also supports cleanup mode: `--remove-index --feature-id <id>` or `--remove-index --issue-id <id>` to delete index rows for selected scope without rebuilding,
   - for scoped runs, command removes old index rows for selected scope and inserts freshly parsed rows for that scope only,
   - data for other features/issues already in index remains unchanged (append-like accumulation across multiple runs),
   - rerun for same scope acts as refresh (replace only that scope's rows),
   - if resulting index is byte-equivalent to previous state, action is `unchanged` and file write is skipped to avoid git noise.
   - scoped output must include deterministic counters:
     - `scope_type`, `scope_id`,
     - `issues_reindexed`,
     - `surfaces_added`, `surfaces_updated`, `surfaces_removed`,
     - `changed: true|false`.
   - cleanup-mode output must include:
     - `issues_removed`,
     - `surfaces_pruned`,
     - `changed: true|false`.
5. Implement `workflow plan show-related` contract:
   - `--issue-id`: return candidate issue IDs sharing at least one indexed surface with target issue,
   - `--feature-id`: return grouped candidate issue pairs for all issues in feature scope,
   - include `matched_surfaces` in output so overlap-build stage can explain why issue was selected.
6. Implement `workflow plan get-plan-block` contract:
   - command returns only `Dependencies` content (no extra section switches/flags),
   - `--issue-id`: return exact `#### Dependencies` body for selected issue block,
   - `--feature-id`: return grouped `Dependencies` bodies for all issue blocks in selected feature,
   - deterministic failure when target block/owner cannot be resolved.
7. Add tests for:
   - parse success on multiple issue blocks with mixed dependency token formats,
   - deterministic parse output ordering,
   - `index-dependencies` scoped refresh behavior (feature and issue scopes),
   - scoped accumulation behavior across multiple runs for different features,
   - scoped rerun replacement behavior (same scope reindexed without touching other scopes),
   - `--remove-index` behavior for feature and issue scopes,
   - cleanup no-op behavior when selected scope is absent in index,
   - `changed` flag and index counters in output payload,
   - missing block / invalid selector errors,
   - `show-related` correctness for shared vs non-shared surface candidates,
   - `get-plan-block` exact `Dependencies` extraction for issue and feature scopes.

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 tasks
  1. CLI registration and command plumbing
  2. dependency-block parser and JSON index writer
  3. scoped dependencies-block retrieval command
  4. regression tests

### I2-F14-M1 - Introduce issue-level overlap schema and validators

#### Dependencies
- file: dev/map/ISSUE_OVERLAPS_JSON_SCHEMA.json | reason: canonical machine-readable overlap shape lives here
- module: dev.workflow_lib.tracker_json_contracts | reason: runtime overlap validation must mirror schema rules
- file: dev/ISSUE_OVERLAPS.json | reason: dedicated overlap storage artifact must replace pipeline overlap ownership

#### Decomposition
1. Define strict issue-level overlap JSON contract in schema:
   - top-level object: `{ "overlaps": [ ... ] }`,
   - each `overlaps[]` entry has `issues`, `type`, optional `order`, `surface`, `description`,
   - `issues`: array with exactly 2 issue IDs (`I*-F*-M*`),
   - `type`: one of `dependency | conflict | shared_logic`,
   - `order`: optional for `conflict/shared_logic`, required for `dependency` in format `<issue_id>-><issue_id>`,
   - `surface`: non-empty string describing shared module/file/symbol,
   - `description`: required human-readable explanation of overlap meaning.
2. Define strict `description` content template by `type`:
   - `dependency`: explain why one issue must run before the other, what breaks without order, and the required direction (`A->B`).
   - `conflict`: explain what exactly conflicts and what must be aligned before parallel changes.
   - `shared_logic`: explain what shared module/symbol is touched and what architectural consideration prevents duplication/drift.
   - short template: `why: ...; impact: ...; action: ...`.
3. Add schema-level semantic checks:
   - `issues[0] != issues[1]`,
   - reject duplicate pairs regardless of order (`A,B` equals `B,A`),
   - for `dependency`, ensure `order` direction references exactly the same two issue IDs from `issues`.
4. Update runtime validator (`tracker_json_contracts.py`) to mirror schema checks with deterministic error messages:
   - invalid ID format,
   - missing/invalid `order` for dependency,
   - empty `surface/description`,
   - invalid `description` template (missing `why`/`impact`/`action` segments),
   - duplicate pair collisions.
5. Remove legacy task-level overlap acceptance from validator path and require dedicated overlaps-file shape only.
6. Define migration gate behavior:
   - if overlap data is still read from `TASK_EXECUTION_PIPELINE`, validation fails with actionable migration error.
7. Add tests:
   - valid dependency/conflict/shared_logic samples,
   - invalid dependency without order,
   - invalid order with unknown issue IDs,
   - invalid description template per overlap type,
   - duplicate pair detection (`A,B` + `B,A`),
   - old-format rejection.

#### Issue/Task Decomposition Assessment
- Expected split: 4 tasks
  1. strict schema contract and pair constraints
  2. runtime validator parity and deterministic errors
  3. legacy-format rejection + migration gate
  4. regression coverage for valid/invalid overlap payloads

### I3-F14-M1 - Add build/show/apply overlap commands

#### Dependencies
- module: dev.workflow_lib.feature_commands | reason: candidate discovery, draft generation, and apply handlers are implemented here
- module: dev.workflow_lib.tracker_store | reason: overlap reads and writes need dedicated helpers for ISSUE_OVERLAPS
- file: .agents/workflows/build-overlaps.md | reason: agent workflow must define the exact CLI plus analysis sequence
- file: dev/ISSUE_DEP_INDEX.json | reason: build-overlaps needs indexed related-issue candidates before draft generation

#### Decomposition
1. Add canonical command `workflow plan show-overlaps --feature-id <id> | --issue-id <id> | --all` to read overlaps from `dev/ISSUE_OVERLAPS.json`.
2. Add canonical command `workflow plan build-overlaps --feature-id <id> | --issue-id <id> --delta-file <path>` that:
   - loads candidate issues from dependency index,
   - fetches dependencies blocks via `workflow plan get-plan-block ...` (dependencies-only output),
   - fetches current overlaps via `workflow plan show-overlaps ...`,
   - builds overlap delta skeleton (candidate pairs + existing overlap references) without semantic classification,
   - writes deterministic draft payload structure that is ready for agent-side enrichment.
3. Add canonical command `workflow plan apply-overlaps --delta-file <path>` to write overlap updates through parser/validator flow.
4. Add new agent workflow `.agents/workflows/build-overlaps.md` with strict execution sequence and artifact flow:
   - Step 1 (CLI): run `workflow plan index-dependencies --feature-id <id>` (or `--issue-id <id>`) to refresh dependency index for current scope.
   - Step 2 (CLI): run `workflow plan show-related --feature-id <id>` (or `--issue-id <id>`) to get candidate issue IDs and matched surfaces.
   - Step 3 (CLI): run `workflow plan get-plan-block ...` for each candidate issue to fetch dependencies-only text used for overlap reasoning.
   - Step 4 (CLI): run `workflow plan show-overlaps ...` to fetch current overlap state for the same scope.
   - Step 5 (CLI): run `workflow plan build-overlaps ... --delta-file tmp/workflow/<scope>-overlaps-draft.json` to write draft overlap delta skeleton.
   - Step 6 (agent analysis): agent reads draft delta + fetched dependencies blocks, classifies each overlap as `dependency | conflict | shared_logic`, and writes `description` in `why/impact/action` format.
   - Step 7 (agent edit): agent saves enriched payload to `tmp/workflow/<scope>-overlaps-final.json`.
   - Step 8 (CLI): run `workflow plan apply-overlaps --delta-file tmp/workflow/<scope>-overlaps-final.json` to validate and persist overlaps into `dev/ISSUE_OVERLAPS.json`.
   - Step 9 (verification): run command output checks (counts + changed flag) and fail workflow when classification/description coverage is incomplete.
5. Remove old append-only overlap write behavior from legacy plan-tasks overlap path.
6. Add command-level regression tests for scope filtering, deterministic summaries, and workflow-contract compliance.

#### Issue/Task Decomposition Assessment
- Expected split: 4 tasks
  1. show-overlaps command
  2. build-overlaps command + analysis engine for type/description generation
  3. apply-overlaps command + legacy append removal
  4. new `build-overlaps` workflow contract and end-to-end tests

### I4-F14-M1 - Integrate plan-tasks with issue-level overlaps

#### Dependencies
- function: dev/workflow_lib/feature_commands.py::_handle_feature_sync | reason: plan-tasks runtime integration happens in the shared decomposition handler
- file: .agents/workflows/plan-tasks-for.md | reason: workflow must state that overlaps are read-only planning input
- file: dev/ISSUE_OVERLAPS.json | reason: plan-tasks must load overlap context from the dedicated artifact only

#### Decomposition
1. Update plan-tasks flow to read issue-overlaps as planning constraints before task decomposition apply.
2. Remove overlap append from plan-tasks delta contract; keep overlaps strictly read-only input for decomposition stage.
3. Preserve behavior when no overlaps exist (decomposition still runs).
4. Read overlaps from `dev/ISSUE_OVERLAPS.json` only; do not read overlap data from `TASK_EXECUTION_PIPELINE` in plan-tasks flow.
5. Add tests proving `plan tasks for ...` no longer mutates overlaps directly in write mode.

#### Issue/Task Decomposition Assessment
- Expected split: 3 tasks
  1. runtime integration in plan-tasks handlers
  2. workflow/docs contract update
  3. regression coverage

### I5-F14-M1 - Add confirm cleanup for issue-level overlaps and dependency index

#### Dependencies
- module: dev.workflow_lib.confirm_commands | reason: confirm issue and confirm feature cleanup paths live here
- file: dev/ISSUE_OVERLAPS.json | reason: completion cleanup must prune stale issue-overlap records
- file: dev/ISSUE_DEP_INDEX.json | reason: completion cleanup must remove indexed dependency surfaces for closed scope

#### Decomposition
1. Update `confirm issue done` cleanup to remove overlap entries referencing the confirmed issue.
2. Update `confirm feature done` cleanup to remove overlaps for all child issues in confirmed feature subtree.
3. Reuse index cleanup command in confirm flows:
   - `confirm issue done` triggers `workflow plan index-dependencies --remove-index --issue-id <id>` for removed/terminal issue scope.
   - `confirm feature done` triggers `workflow plan index-dependencies --remove-index --feature-id <id>` for full feature scope.
4. Keep cleanup deterministic in dry-run/write output contracts.
5. Add tests for overlap + index cleanup on issue-level and feature-level confirm paths.

#### Issue/Task Decomposition Assessment
- Expected split: 3 tasks
  1. confirm cleanup implementation
  2. index cleanup command integration in confirm path
  3. dry-run/write contract updates + regression tests

### I6-F14-M1 - Migrate overlaps storage from pipeline block to dedicated overlaps file

#### Dependencies
- file: dev/TASK_EXECUTION_PIPELINE.json | reason: legacy overlap rows must be migrated out of the pipeline artifact
- file: dev/ISSUE_OVERLAPS.json | reason: migrated overlap rows need one dedicated destination artifact
- file: dev/map/TASK_EXECUTION_PIPELINE_JSON_SCHEMA.json | reason: pipeline contract must drop overlap ownership after cutover
- file: .agents/workflows/build-overlaps.md | reason: workflow contract must point to overlaps-only storage after migration

#### Decomposition
1. Add one-time migration routine to extract overlap entries from `dev/TASK_EXECUTION_PIPELINE.json` and write them into `dev/ISSUE_OVERLAPS.json` in new schema.
2. Remove overlap block ownership from pipeline schema/runtime contracts after migration.
3. Update all overlap read/write paths to use only `dev/ISSUE_OVERLAPS.json`.
4. Update all affected agent workflow docs and CLI workflow handlers to remove overlap operations from `TASK_EXECUTION_PIPELINE` and reference overlaps-only commands/files.
5. Add migration safety checks:
   - idempotent re-run behavior,
   - deterministic ordering of migrated entries,
   - hard-fail when invalid legacy overlap rows are encountered.
6. Add tests for successful migration, no-op rerun, and legacy-shape rejection after cutover.

#### Issue/Task Decomposition Assessment
- Expected split: 4 tasks
  1. migration tool implementation
  2. runtime cutover to overlaps-only storage
  3. workflow/docs + CLI cutover from pipeline overlap operations
  4. pipeline contract cleanup and migration/regression coverage

### I8-F14-M1 - Remove TASK_EXECUTION_PIPELINE from workflow runtime entirely

#### Dependencies
- file: dev/TASK_EXECUTION_PIPELINE.json | reason: legacy runtime artifact must stop being a required tracker input anywhere in workflow execution
- file: dev/map/TASK_EXECUTION_PIPELINE_JSON_SCHEMA.json | reason: schema becomes obsolete once runtime ownership is removed
- module: dev.workflow_lib.feature_commands | reason: execution-plan and plan-tasks runtime paths still reference pipeline reads
- module: dev.workflow_lib.confirm_commands | reason: confirm cleanup still cleans sequence/block remnants from pipeline
- module: dev.workflow_lib.tracker_store | reason: canonical tracker loaders still expose pipeline payload as runtime input
- file: .agents/protocols/task-execution-protocol.md | reason: execution read order and workflow contracts still mention pipeline
- file: .agents/workflows/execute-feature.md | reason: feature execution order still resolves through pipeline first
- file: .agents/workflows/execute-task.md | reason: task execution workflow still reads pipeline for ordering rows

#### Decomposition
1. Audit and remove all remaining runtime reads of `dev/TASK_EXECUTION_PIPELINE.json`:
   - execution planning,
   - task execution preparation,
   - confirm cleanup,
   - tracker store/runtime contracts.
2. Replace pipeline-backed sequencing with surviving sources only:
   - feature issue order from `dev/FEATURE_PLANS.md`,
   - task ownership/order from `dev/map/DEV_MAP.json` and `dev/TASK_LIST.json`,
   - issue-level architectural constraints from `dev/ISSUE_OVERLAPS.json`.
3. Remove pipeline-specific writer/validator/schema code paths:
   - stop requiring pipeline payload during sync/apply flows,
   - delete obsolete pipeline schema/runtime validation contracts,
   - make tracker operations valid when no pipeline artifact exists.
4. Update confirm/reject/runtime cleanup contracts so they no longer read or mutate pipeline rows and instead operate only on active canonical artifacts.
5. Update agent rules/protocols/workflows to fully remove `TASK_EXECUTION_PIPELINE` from read order, execution order, cleanup language, and planning references.
6. Add regression coverage for:
   - execution-plan without pipeline file,
   - execute-task/execute-feature preparation without pipeline file,
   - confirm cleanup without pipeline file,
   - sync and tracker reads when pipeline artifact is absent.

#### Issue/Task Decomposition Assessment
- Expected split: 4 tasks
  1. remove runtime read dependencies on pipeline artifact
  2. replace sequencing/cleanup behavior with remaining canonical sources
  3. remove obsolete schema/store/writer contracts and workflow references
  4. add regression coverage for pipeline-free runtime behavior

### I9-F14-M1 - Remove feature plan section on confirm feature done

#### Dependencies
- module: dev.workflow_lib.confirm_commands | reason: confirm feature completion flow owns FEATURE_PLANS cleanup behavior
- file: dev/FEATURE_PLANS.md | reason: feature-level section removal must delete the full `## F*-M*` block after feature confirmation
- function: dev/workflow_lib.confirm_commands::_handle_confirm_feature_done | reason: feature confirmation path currently updates trackers but leaves the feature plan section behind
- function: dev/workflow_lib.confirm_commands::_cleanup_feature_plan_issue_artifacts | reason: existing cleanup helper already removes issue rows/blocks and likely needs feature-level companion logic

#### Decomposition
1. Add feature-level FEATURE_PLANS cleanup helper that removes the full `## <feature_id>` section, including:
   - feature title line,
   - `Issue Execution Order`,
   - feature dependencies/decomposition/assessment,
   - all child issue plan blocks within that section.
2. Integrate that helper into `confirm feature done` preview and write paths so cleanup output reports whether the feature section would be removed or was removed.
3. Keep issue-level cleanup behavior unchanged:
   - `confirm issue done` still removes only issue row/block,
   - `confirm feature done` removes the entire feature section in one step.
4. Add regression coverage for:
   - preview mode reporting feature-section cleanup,
   - write mode removing the feature section from `FEATURE_PLANS.md`,
   - no-op behavior when the feature section is already absent.

#### Issue/Task Decomposition Assessment
- Expected split: 2-3 tasks
  1. feature-level FEATURE_PLANS cleanup helper
  2. confirm feature integration and cleanup output contract
  3. regression coverage for preview/write/no-op behavior
