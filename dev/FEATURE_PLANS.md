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

## F15-M1

### Expected Behaviour
- `reject feature --id <feature_id>` becomes a first-class workflow command that rejects the full feature subtree in one deterministic operation instead of requiring manual issue-by-issue rejection.
- In local tracker state, the feature and all child issues transition to `Rejected`, while child task artifacts are removed from active planning/execution trackers so no stale pending work remains attached to a rejected feature.
- Local cleanup removes child issue plan blocks, the parent feature plan section, overlap rows, and dependency-index rows when present, while staying stable when some artifacts were already removed earlier.
- Remote behavior mirrors existing `reject issue` semantics: each mapped child issue and the mapped feature issue receives the rejection marker and is closed, while unmapped nodes remain local-only and are reported explicitly.

### Dependencies
- [dev/workflow_lib/confirm_commands.py](dev/workflow_lib/confirm_commands.py) — owns the current `reject issue` flow, feature confirmation cleanup path, and shared tracker cleanup helpers that `reject feature` should reuse instead of reimplementing.
- [dev/FEATURE_PLANS.md](dev/FEATURE_PLANS.md) — feature rejection must remove child issue plan blocks and the parent feature section when they exist, while staying stable if they are already absent.
- [dev/map/DEV_MAP.json](dev/map/DEV_MAP.json) — feature and child issue status transitions must mark the subtree as `Rejected` without leaving orphan issue nodes or stale active statuses.
- [dev/ISSUE_OVERLAPS.json](dev/ISSUE_OVERLAPS.json) and [dev/ISSUE_DEP_INDEX.json](dev/ISSUE_DEP_INDEX.json) — feature-level reject cleanup must remove rows and lookups for the rejected feature subtree in the same write run as other tracker cleanup.
- [.agents/workflows/reject.md](.agents/workflows/reject.md) and [.agents/protocols/task-execution-protocol.md](.agents/protocols/task-execution-protocol.md) — command workflow and lifecycle rules must be extended from issue-only reject semantics to a deterministic feature-level reject contract.
- Existing `reject issue` GitHub behavior is the remote contract baseline: mapped issues receive a rejection marker and are closed, while unmapped issues stay local-only and report missing mapping metadata explicitly.

### Decomposition
1. Add a feature-level reject command surface and local cleanup contract:
   - introduce `reject feature --id <feature_id>` with deterministic preview and write-mode payloads,
   - mark the feature and all child issues as `Rejected`,
   - remove child task artifacts plus issue/feature plan blocks, overlap rows, and dependency-index rows when present,
   - keep repeated or partial-artifact runs no-op-safe instead of failing on already-clean state.
2. Reuse existing reject/confirm primitives rather than fork new logic:
   - build feature reject on top of the current `reject issue` GitHub semantics and `confirm feature` cleanup helpers,
   - keep cleanup reporting aligned with existing reject/confirm payload shapes so downstream workflow output stays predictable,
   - preserve materialization-aware behavior for mapped versus unmapped child issues.
3. Lock the new behavior with docs and regression coverage:
   - add preview/write/no-op/repeat tests for feature reject,
   - document how feature rejection differs from feature confirmation while reusing the same cleanup surfaces,
   - keep runtime help and workflow docs aligned with the final command surface.

### Issue/Task Decomposition Assessment
- Feature scope is intentionally split into two issues because local subtree cleanup and remote GitHub rejection are tightly related but still separable implementation slices.
- Minimal execution order:
  1. add the feature-level reject contract and local subtree cleanup,
  2. extend GitHub rejection flow and lock the combined behavior with docs/tests.
- Expected split:
  - `I1-F15-M1`: contract, parser/handler wiring, local cleanup, deterministic payloads
  - `I2-F15-M1`: GitHub cascade, workflow/help updates, regression coverage

### I1-F15-M1 - Add reject feature command and local subtree cleanup

#### Expected Behaviour
- Users can preview and apply `reject feature --id <feature_id>` through the workflow CLI with the same dry-run/write conventions used by the current confirm and reject commands.
- Write mode marks the feature and every child issue as `Rejected`, removes feature-owned task artifacts from active trackers, and deletes child issue plus feature plan blocks when they exist.
- The command remains deterministic on partially cleaned or repeat-run states by reporting which cleanup surfaces were found, removed, or already absent instead of failing late on missing artifacts.

#### Dependencies
- file: `dev/workflow_lib/confirm_commands.py` | reason: add a `reject feature` parser target and handler next to the existing issue-level reject and feature-level confirm flows.
- function: `_handle_reject_issue` | reason: feature reject should mirror materialization-aware local status semantics instead of inventing a second rejection model.
- function: `_handle_confirm_feature_done` | reason: feature reject should reuse the existing full-subtree cleanup shape for task artifacts, overlaps, dependency-index rows, and feature-plan section removal.
- function: `_cleanup_feature_plan_issue_artifacts` | reason: child issue plan blocks must be removed deterministically when rejecting a feature subtree.
- function: `_cleanup_feature_plan_feature_section` | reason: the parent `## <feature_id>` section must be removed when present and reported explicitly in preview/write payloads.
- file: `dev/map/DEV_MAP.json` | reason: feature and child issue statuses must transition to `Rejected` while task artifacts are removed from active trackers.

#### Decomposition
1. Define the feature-level reject contract in the CLI and handler payload:
   - add `reject feature --id <feature_id>` as a first-class parser target,
   - define preview fields for affected child issues, task artifacts, feature-plan cleanup, overlaps cleanup, and dependency-index cleanup,
   - keep `--write`, `--close-github`, and repeat-run behavior consistent with existing reject commands.
2. Implement local subtree rejection and cleanup:
   - mark the feature node and every child issue node as `Rejected` in write mode,
   - remove task-list entries, overlap rows, and dependency-index rows for the full feature subtree through the shared cleanup helpers,
   - remove child issue plan blocks and the parent feature section from `FEATURE_PLANS.md` when they exist.
3. Keep artifact-missing and mixed-state behavior deterministic:
   - do not fail when some tasks, issue blocks, or the feature section are already absent,
   - report which cleanup surfaces were found, removed, or already clean,
   - keep unmapped child issues valid in local-only mode until GitHub rejection is explicitly requested.

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 implementation tasks
  1. parser/handler contract for `reject feature`
  2. DEV_MAP status transition for feature and child issues
  3. subtree cleanup wiring across task list, overlaps, dep-index, and plan artifacts
  4. deterministic preview/no-op reporting

### I2-F15-M1 - Add GitHub rejection cascade and regression coverage for reject feature

#### Expected Behaviour
- Feature-level reject applies the same rejection-marker and close flow already used by `reject issue` to the mapped feature issue and every mapped child issue in the subtree.
- Mixed mapping states remain valid: mapped issues are rejected remotely, unmapped issues stay local-only, and the command returns explicit reporting instead of collapsing the whole run.
- Workflow docs and regression tests make preview, write, no-op, and repeat behavior explicit so feature rejection becomes as predictable and auditable as feature confirmation.

#### Dependencies
- file: `dev/workflow_lib/confirm_commands.py` | reason: extend feature-level reject to reuse the same rejection-marker and close flow already implemented for mapped issues.
- function: `_append_issue_rejection_marker` | reason: the feature issue and mapped child issues should receive the same deterministic rejection marker content as `reject issue`.
- module: `dev.workflow_lib.github_adapter` | reason: feature reject must resolve repository context, edit issue bodies, and close mapped feature/child issues through the existing adapter layer.
- file: `.agents/workflows/reject.md` | reason: workflow docs must stop describing reject as issue-only once feature-level reject is introduced.
- file: `tests/workflow/test_feature_lifecycle.py` | reason: feature lifecycle coverage should include the new feature-level reject command surface and repeat-run semantics.
- file: `tests/workflow/test_overlap_commands.py` | reason: cleanup regression tests already cover feature-level artifact removal patterns and are a natural home for reject-feature cleanup assertions.

#### Decomposition
1. Implement GitHub rejection cascade for the feature subtree:
   - apply the same rejection-marker and close flow to the mapped feature issue and every mapped child issue,
   - keep `--no-close-github` as a pure local mode,
   - return deterministic reporting for fully mapped, partially mapped, and unmapped subtrees.
2. Update workflow/help guidance for feature reject:
   - document that `reject feature` rejects the local subtree and cleans local planning/tracker artifacts,
   - clarify that GitHub behavior mirrors `reject issue` for each mapped issue in the subtree,
   - keep docs explicit about local-only behavior when mappings are missing or remote closing is disabled.
3. Add regression coverage for preview, write, and repeat behavior:
   - cover preview mode with no file mutations,
   - cover write mode over mixed mapped/unmapped child issues,
   - cover repeat reject runs and already-absent artifacts so the command remains idempotent and auditable.

#### Issue/Task Decomposition Assessment
- Expected split: 3 implementation tasks
  1. GitHub cascade integration for feature + child issues
  2. workflow/help alignment for the new command
  3. regression coverage for preview/write/repeat/mixed-mapping flows

## F16-M1

### Expected Behaviour
- The planning protocol becomes the single source of truth for `FEATURE_PLANS.md` structure, so agents no longer need to infer the real contract from existing plan blocks or runtime quirks.
- `FEATURE_PLANS.md` becomes a storage-only file with no header boilerplate, and each feature section is reduced to a concise `Expected Behaviour` block that describes the intended outcome and how the feature can be verified.
- Detailed planning structure remains only at the issue-block level, and `feature plan-lint` plus plan-generation helpers enforce that simplified split consistently across runtime, docs, and tests.
- Existing plans migrate to the new format without losing actionable issue-level decomposition detail, and regression checks prevent protocol, lint, and fixtures from drifting apart again.

### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — owns `plan-init`, `plan-lint`, and plan parsing logic that must be aligned to the new feature-level contract.
- [.agents/protocols/feature-planning-protocol.md](.agents/protocols/feature-planning-protocol.md) — should become the only canonical owner of the planning structure and quality gates.
- [.agents/workflows/plan-feature.md](.agents/workflows/plan-feature.md) and [.agents/workflows/plan-issue.md](.agents/workflows/plan-issue.md) — workflow steps must reference the protocol contract instead of treating `FEATURE_PLANS.md` header text as the structure owner.
- [dev/FEATURE_PLANS.md](dev/FEATURE_PLANS.md) — target storage artifact that must become headerless and be normalized to the simplified feature-level block shape.
- [tests/workflow/test_feature_lifecycle.py](tests/workflow/test_feature_lifecycle.py), [tests/workflow/test_overlap_commands.py](tests/workflow/test_overlap_commands.py), and [tests/workflow/test_task_planning.py](tests/workflow/test_task_planning.py) — fixtures and lint expectations must be updated to prove the new contract is enforced end-to-end.

### Decomposition
1. Move canonical ownership of the planning format into the protocol:
   - define the exact feature-level and issue-level plan structures in the planning protocol,
   - make workflows procedural only and reference that contract instead of duplicating local format rules,
   - keep the feature-level contract intentionally minimal: `Expected Behaviour` only.
2. Align runtime enforcement and plan-generation helpers to the simplified contract:
   - change lint so feature sections require only `Expected Behaviour`,
   - keep issue-block validation strict and unchanged where detailed engineering decomposition still belongs,
   - make scaffolds and parser assumptions work with a headerless `FEATURE_PLANS.md`.
3. Migrate stored plans and lock the contract with tests:
   - remove `FEATURE_PLANS.md` boilerplate and normalize existing feature sections,
   - update test fixtures to the new storage shape,
   - add consistency checks that fail when protocol, lint, and fixtures diverge.

### Issue/Task Decomposition Assessment
- Feature scope is split into three issues because protocol ownership, runtime enforcement, and migration/regression work are closely related but should still be delivered in a controlled sequence.
- Minimal execution order:
  1. define the canonical protocol and storage contract,
  2. align runtime lint and generation helpers,
  3. migrate stored plans and add regression/consistency checks.
- Expected split:
  - `I1-F16-M1`: protocol and workflow contract rewrite
  - `I2-F16-M1`: runtime lint and scaffold alignment
  - `I3-F16-M1`: storage migration and regression coverage

### I1-F16-M1 - Define canonical planning contract and storage-only FEATURE_PLANS structure

#### Expected Behaviour
- The protocol explicitly defines the only valid `FEATURE_PLANS.md` structure, so feature and issue plan shape no longer depends on header prose inside the storage file.
- Feature sections are defined as `## <feature_id>` plus `### Expected Behaviour` only, while issue sections remain the detailed engineering planning units.
- Planning workflows reference the protocol contract directly and stop treating `FEATURE_PLANS.md` itself as a format-owner document.

#### Dependencies
- file: `.agents/protocols/feature-planning-protocol.md` | reason: this file must become the canonical owner of the planning structure and quality gates.
- file: `.agents/workflows/plan-feature.md` | reason: feature-planning workflow must reference the protocol contract instead of `FEATURE_PLANS.md` header text.
- file: `.agents/workflows/plan-issue.md` | reason: issue-planning workflow must stay aligned with the protocol-owned issue-block structure.
- file: `dev/FEATURE_PLANS.md` | reason: storage file must stop carrying ownership/format boilerplate once the protocol becomes canonical.

#### Decomposition
1. Define the canonical planning structure in the protocol:
   - document that feature sections require only `Expected Behaviour`,
   - document that issue blocks keep `Expected Behaviour`, `Dependencies`, `Decomposition`, and `Issue/Task Decomposition Assessment`,
   - make the protocol the explicit source of truth for heading names and section levels.
2. Rewrite planning workflows around protocol-owned structure:
   - update `plan-feature` to generate and review the simplified feature block plus full issue blocks,
   - update `plan-issue` to reference only the issue-block contract it owns procedurally,
   - remove references that imply `FEATURE_PLANS.md` header text is normative.
3. Define storage-only expectations for `FEATURE_PLANS.md`:
   - document that the file may contain plans only, without header boilerplate,
   - keep storage semantics compatible with plan extraction and cleanup code,
   - specify migration expectations for existing sections.

#### Issue/Task Decomposition Assessment
- Expected split: 3 implementation tasks
  1. protocol contract rewrite for feature and issue sections
  2. plan-feature workflow alignment
  3. plan-issue/storage-only guidance alignment

### I2-F16-M1 - Align lint and plan generation with the simplified feature-block contract

#### Expected Behaviour
- `feature plan-lint` validates feature sections using the new minimal contract and still validates issue blocks with the full detailed structure.
- `feature plan-init` and related plan-generation helpers create feature sections that are immediately valid under the new contract without injecting obsolete placeholders.
- Runtime parsing and extraction stay stable when `FEATURE_PLANS.md` contains only raw plan sections and no file header boilerplate.

#### Dependencies
- file: `dev/workflow_lib/feature_commands.py` | reason: lint, plan-init, and plan extraction logic must enforce the new feature-level contract.
- function: `_lint_feature_plan_section` | reason: feature-level heading validation must be reduced to `Expected Behaviour` only.
- function: `_render_feature_plan_section` | reason: generated feature scaffolds must stop emitting obsolete feature-level headings.
- function: `_extract_feature_plan_section` | reason: plan extraction must remain stable after removing storage-file boilerplate.
- file: `dev/FEATURE_PLANS.md` | reason: runtime assumptions about file preamble or feature-section layout must be compatible with headerless storage.

#### Decomposition
1. Update runtime feature-section linting:
   - require only `Expected Behaviour` at the feature level,
   - keep non-empty content and placeholder-quality checks where appropriate,
   - preserve strict issue-block validation under the same feature section.
2. Update plan scaffolds and section rendering:
   - make `plan-init` emit only the simplified feature-level block,
   - keep issue-block generation unchanged where detailed decomposition is still required,
   - ensure newly initialized plans pass lint without manual removal of obsolete placeholders.
3. Remove header-dependent runtime assumptions:
   - make empty/default file initialization compatible with a headerless storage file,
   - keep feature lookup and section-bound detection stable without relying on `# Feature Plans`,
   - verify cleanup and extraction helpers still operate correctly on pure-plan storage.

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 implementation tasks
  1. feature-level lint contract update
  2. plan-init / scaffold update
  3. headerless storage compatibility pass
  4. targeted runtime verification

### I3-F16-M1 - Migrate existing plans and add consistency regression coverage

#### Expected Behaviour
- Existing `FEATURE_PLANS.md` content is normalized to the new contract without dropping issue-level implementation detail.
- Test fixtures stop depending on storage-file boilerplate or obsolete feature-level headings.
- Regression checks catch future drift between the protocol contract, runtime lint, and representative plan fixtures.

#### Dependencies
- file: `dev/FEATURE_PLANS.md` | reason: existing feature sections must be migrated to the new storage shape.
- file: `tests/workflow/test_feature_lifecycle.py` | reason: plan-init and lint fixtures must reflect headerless storage and simplified feature blocks.
- file: `tests/workflow/test_overlap_commands.py` | reason: feature-plan lint and cleanup fixtures currently exercise feature-level Expected Behaviour and storage-file handling.
- file: `tests/workflow/test_task_planning.py` | reason: task-planning fixtures must remain valid after feature-level headings are simplified.
- file: `.agents/protocols/feature-planning-protocol.md` | reason: tests should validate the enforced contract declared by the protocol rather than a stale local convention.

#### Decomposition
1. Migrate stored feature plans:
   - remove file-level boilerplate from `FEATURE_PLANS.md`,
   - simplify existing feature sections to `Expected Behaviour` only,
   - keep issue blocks intact except where updates are needed for contract conformance.
2. Update workflow fixtures and lint expectations:
   - rewrite test fixtures that currently include obsolete header text or feature-level headings,
   - add positive checks for headerless storage plus simplified feature sections,
   - add failure checks for missing feature-level `Expected Behaviour`.
3. Add consistency regression coverage:
   - prove runtime lint follows the protocol-declared feature and issue structures,
   - add targeted guards for scaffold validity and headerless-file behavior,
   - keep regression scope focused on real drift vectors rather than duplicating the full protocol in tests.

#### Issue/Task Decomposition Assessment
- Expected split: 3 implementation tasks
  1. plan storage migration
  2. fixture/test update
  3. protocol-lint consistency regression checks

## F17-M1

### Expected Behaviour
- Overlap workflow moves to one explicit model: the agent prepares a full editable draft snapshot for `ISSUE_OVERLAPS.json`, including both `overlaps` and `issue_execution_order`, instead of relying on ambiguous partial-delta apply semantics.
- Scope discovery remains local to the requested feature or issue, but final apply writes a complete validated global block so unrelated existing overlap pairs remain intact unless the draft changes them explicitly.
- `issue_execution_order` becomes an explicitly edited field in the final draft rather than a hidden side effect of `apply-overlaps`, while CLI validation ensures that the provided order is structurally valid and semantically consistent with dependency overlaps.
- `issue_execution_order` is reduced to issues that actually participate in dependency overlaps, so the order block stops echoing unrelated active issues from `DEV_MAP` that contribute no dependency edges.
- Workflow docs and regression coverage make the roles clear: CLI commands discover context and validate/apply the final snapshot, while the agent prepares and edits the full draft between those stages.

### Dependencies
- [dev/workflow_lib/feature_commands.py](dev/workflow_lib/feature_commands.py) — owns `show-related`, `get-plan-block`, `build-overlaps`, `show-overlaps`, and `apply-overlaps`, so the overlap workflow contract and write semantics must be updated there.
- [dev/workflow_lib/tracker_json_contracts.py](dev/workflow_lib/tracker_json_contracts.py) and [dev/map/ISSUE_OVERLAPS_JSON_SCHEMA.json](dev/map/ISSUE_OVERLAPS_JSON_SCHEMA.json) — canonical overlap payload shape and validation rules that must be extended to support full-draft validation and explicit order semantics.
- [dev/ISSUE_OVERLAPS.json](dev/ISSUE_OVERLAPS.json) — target global tracker whose full-block ownership, preservation rules, and apply semantics must become explicit and auditable.
- [.agents/workflows/build-overlaps.md](.agents/workflows/build-overlaps.md) — current workflow still describes delta-oriented overlap drafting and needs to be rewritten around full snapshot preparation and CLI validation/apply.
- [tests/workflow/test_overlap_commands.py](tests/workflow/test_overlap_commands.py) — overlap workflow behavior, scope filtering, and apply semantics need regression coverage once the new contract is introduced.

### Decomposition
1. Define one canonical overlap workflow contract:
   - scope-specific commands discover candidates and issue-plan context,
   - the agent prepares a full editable draft snapshot from current global overlap state plus scoped updates,
   - final apply validates and writes the entire block instead of performing hidden partial replacement or implicit merge.
2. Align runtime validation and apply semantics with that contract:
   - schema validation and semantic validation live in CLI,
   - draft preparation remains agent-driven,
   - `issue_execution_order` is validated as an explicit field supplied in the final draft.
3. Lock the workflow with docs and tests:
   - update build/apply overlap workflow guidance,
   - cover preservation of unrelated pairs,
   - cover invalid orders, duplicate pairs, pair/order mismatch, and scope-read behavior.
4. Remove noise from global overlap ordering:
   - keep `issue_execution_order` limited to dependency-overlap participants only,
   - stop auto-including active issues that have no dependency edges,
   - make tests prove that isolated issues stay out of the order block.

### Issue/Task Decomposition Assessment
- Feature scope is split into three issues because workflow contract, runtime enforcement, and regression/documentation work are closely connected but should be landed in a controlled sequence.
- A fourth issue is required because global order node selection is a separate runtime rule from draft/apply semantics and needs targeted regression coverage.
- Minimal execution order:
  1. define the canonical overlap workflow and responsibility split,
  2. implement full-draft validation and write semantics,
  3. limit `issue_execution_order` to dependency-overlap participants,
  4. align helper commands, docs, and regression coverage.
- Expected split:
  - `I1-F17-M1`: workflow contract and command-surface definition
  - `I2-F17-M1`: runtime validation/apply semantics
  - `I3-F17-M1`: workflow/doc/test alignment
  - `I4-F17-M1`: dependency-graph-only issue order

### I1-F17-M1 - Define full-snapshot overlap workflow contract and CLI responsibilities

#### Expected Behaviour
- The repository has one explicit overlap workflow contract that says exactly which steps are CLI-owned and which steps are agent-owned.
- Discovery commands remain scoped to the requested feature or issue, while final overlap editing is performed against a full global draft snapshot.
- The overlap contract explicitly states that the agent edits `issue_execution_order` in the draft and that CLI validation/apply treats that order as input to be checked rather than silently recomputed.

#### Dependencies
- file: `.agents/workflows/build-overlaps.md` | reason: this workflow must be rewritten so it describes full-snapshot draft preparation instead of ambiguous delta-only semantics.
- file: `dev/workflow_lib/feature_commands.py` | reason: command responsibilities for overlap discovery, readback, and apply must match the documented workflow contract.
- file: `dev/ISSUE_OVERLAPS.json` | reason: the contract needs to define full-block ownership and preservation of unrelated overlap pairs.
- file: `dev/map/ISSUE_OVERLAPS_JSON_SCHEMA.json` | reason: the workflow contract must stay compatible with the canonical overlap payload shape and explicit order field.

#### Decomposition
1. Define the canonical overlap workflow steps:
   - discovery through `index-dependencies`, `show-related`, and issue-plan extraction,
   - agent-prepared full draft snapshot from current global state,
   - CLI validation and full-block apply.
2. Define responsibility boundaries:
   - CLI owns discovery helpers, validation, and final write,
   - the agent owns draft preparation, pair classification, pair updates, and explicit `issue_execution_order` editing.
3. Define full-snapshot preservation semantics:
   - existing unrelated pairs stay in the draft unless explicitly changed,
   - pair identity is tracked by canonical issue pair key,
   - final apply consumes a complete snapshot rather than an implicit merge patch.

#### Issue/Task Decomposition Assessment
- Expected split: 3 implementation tasks
  1. workflow contract rewrite
  2. command responsibility mapping
  3. full-snapshot preservation and pair-key semantics

### I2-F17-M1 - Implement full-block overlap apply validation and write semantics

#### Expected Behaviour
- `apply-overlaps` accepts a full draft snapshot, validates it thoroughly, and writes the entire `ISSUE_OVERLAPS.json` block only when both schema and semantic checks pass.
- Validation rejects malformed payloads, duplicate pair keys, pair/order mismatches, unknown issue IDs, and contradictory `issue_execution_order` before any file mutation happens.
- Final write semantics are explicit: the CLI persists exactly the validated full draft block and does not perform hidden scope replacement or hidden order recomputation.

#### Dependencies
- file: `dev/workflow_lib/feature_commands.py` | reason: `_handle_plan_apply_overlaps` currently derives order implicitly and must be updated to validate and persist a full supplied snapshot.
- file: `dev/workflow_lib/tracker_json_contracts.py` | reason: overlap payload validation must cover full-draft shape, duplicate pair keys, and explicit order semantics.
- file: `dev/map/ISSUE_OVERLAPS_JSON_SCHEMA.json` | reason: schema requirements must match the final draft payload that `apply-overlaps` expects.
- file: `dev/map/DEV_MAP.json` | reason: semantic validation must confirm that overlap issue IDs referenced in the draft actually exist in the active tracker state.

#### Decomposition
1. Update overlap payload contract for full-draft apply:
   - require full top-level overlap block shape in the apply input,
   - validate explicit `issue_execution_order` supplied in the draft,
   - keep pair/order shape deterministic and schema-backed.
2. Implement semantic validation before write:
   - reject duplicate canonical pair keys,
   - reject `order` values that do not reference the same issue pair,
   - reject unknown issue IDs and invalid order/member relationships,
   - reject contradictory or cyclic dependency ordering when applicable.
3. Implement explicit full-block write semantics:
   - persist the validated draft block exactly as supplied,
   - do not replace only one scope silently,
   - do not recompute `issue_execution_order` behind the agent’s back during apply.

#### Issue/Task Decomposition Assessment
- Expected split: 3-4 implementation tasks
  1. schema/contract update for full apply payload
  2. semantic validation rules
  3. full-block write behavior
  4. negative-path verification

### I3-F17-M1 - Align overlap build/read workflows and regression coverage with snapshot apply

#### Expected Behaviour
- Overlap helper commands and workflow docs clearly support the new model: scoped discovery, agent-prepared full snapshot, CLI validation, and full-block apply.
- `show-overlaps` and related overlap-read helpers report state consistently for feature and issue scopes so the agent can prepare the draft without hidden filtering surprises.
- Regression coverage protects unrelated-pair preservation, feature-scope reads, and invalid full-draft apply behavior from future drift.

#### Dependencies
- file: `.agents/workflows/build-overlaps.md` | reason: the procedural workflow must describe the new full-snapshot preparation and validation/apply sequence end to end.
- file: `dev/workflow_lib/feature_commands.py` | reason: overlap read/build helpers and scope filtering must match the rewritten workflow and final apply model.
- file: `tests/workflow/test_overlap_commands.py` | reason: overlap workflow regressions should be locked in one place, including feature-scope reads and full-draft apply semantics.
- file: `dev/ISSUE_OVERLAPS.json` | reason: tests need representative global overlap state to prove unrelated-pair preservation and explicit order handling.

#### Decomposition
1. Align overlap read/build workflow guidance:
   - rewrite procedural docs around full draft preparation,
   - document agent-owned draft editing and CLI-owned validation/apply,
   - make explicit that final draft contains the full overlap block.
2. Align overlap helper behavior where needed:
   - ensure feature-scope reads return the overlaps actually owned by that feature subtree,
   - keep build helpers compatible with agent-driven full draft preparation,
   - avoid helper behavior that suggests hidden merge or scope replacement semantics.
3. Add regression coverage for the redesigned workflow:
   - preserve unrelated existing pairs when applying a new full draft,
   - fail on duplicate pairs, invalid issue IDs, invalid order references, and contradictory order,
   - cover feature-scope and issue-scope overlap reads under the new model.

#### Issue/Task Decomposition Assessment
- Expected split: 3 implementation tasks
  1. workflow/doc alignment
  2. helper/read-path alignment
  3. regression coverage for full-draft apply and scope reads

### I4-F17-M1 - Limit issue execution order to dependency-overlap participants only

#### Expected Behaviour
- `issue_execution_order.ordered_issue_ids` contains only issue IDs that participate in at least one dependency overlap edge, rather than all active issues from `DEV_MAP`.
- Issues with no dependency-overlap participation remain absent from the global order block, so `ISSUE_OVERLAPS.json` reflects real dependency-ordering data instead of unrelated tracker noise.
- Runtime behavior and tests make it explicit that the order block is derived from dependency-graph membership, not from generic active-issue presence.

#### Dependencies
- file: `dev/workflow_lib/feature_commands.py` | reason: global issue order is currently built from all active DEV_MAP issues and must instead use only dependency-overlap participants.
- function: `_build_global_issue_execution_order` | reason: this builder currently seeds the graph with unrelated active issues and must narrow node selection to dependency-overlap participants.
- function: `_collect_active_issue_ids_in_dev_map_order` | reason: active-issue collection is the source of the current noise and must either be constrained or replaced for overlap ordering.
- file: `dev/ISSUE_OVERLAPS.json` | reason: the stored order block should no longer include issues with no dependency-edge participation.
- file: `tests/workflow/test_overlap_commands.py` | reason: regression coverage must prove isolated issues stay out of `ordered_issue_ids` while dependency-linked issues remain ordered correctly.

#### Decomposition
1. Redefine the node set for global overlap ordering:
   - derive order nodes only from issue IDs that appear in dependency overlaps,
   - preserve stable ordering among those participating nodes,
   - stop seeding the graph from unrelated active issues in `DEV_MAP`.
2. Update runtime global-order builder:
   - change `_build_global_issue_execution_order` to ignore non-participating issues,
   - keep cycle detection and dependency-edge handling intact for participating nodes,
   - ensure empty or overlap-free dependency graphs produce an empty order block instead of a noisy active-issue list.
3. Add regression coverage for noisy-order removal:
   - prove issues without dependency overlaps do not appear in `ordered_issue_ids`,
   - prove dependency-linked issues still appear in stable topological order,
   - cover mixed states where only part of the active issue set participates in dependency overlaps.

#### Issue/Task Decomposition Assessment
- Expected split: 3 implementation tasks
  1. order-node contract change
  2. runtime builder update
  3. regression coverage for isolated-issue exclusion
