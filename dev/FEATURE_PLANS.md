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
