# Feature Planning Protocol

This protocol defines target-state planning quality for workflow entities.
`dev/map/DEV_MAP.json` is the runtime tracker for `Feature` and `Issue`.
`dev/FEATURE_PLANS.md` is the canonical storage for local `Task` decomposition.

## Canonical structure

- `Feature` section:
  - `## <feature_id>`
  - `### Expected Behaviour`
- `Issue` section inside a feature:
  - `### <issue_id> - <issue_title>`
  - `#### Expected Behaviour`
  - `#### Dependencies`
  - `#### Decomposition`
  - `#### Issue/Task Decomposition Assessment`

## Planning contract

1. `plan feature <id>` and `plan issue <id>` produce or refine plan content in `dev/FEATURE_PLANS.md`.
2. Local `Task` decomposition is written directly in `#### Decomposition` and assessed in `#### Issue/Task Decomposition Assessment`.
3. `Task` storage is local-plan only; it is not required to be mirrored into `DEV_MAP`.
4. Every planned `Feature` must have at least one local `Task`.
5. Every planned `Issue` must have at least one local `Task`.
6. `Issue` always means a GitHub-tracked entity; internal decomposition must not use `issue` as a synonym for local task stages.

## Quality gates

### Gate 0: Structure

- The feature section and each issue block use the canonical headings.
- `Expected Behaviour` is concrete and repository-specific.
- `Dependencies` uses concrete file/module/function/class lines.
- `Decomposition` contains executable implementation steps, not placeholders.

### Gate 1: Execution readiness

- The plan identifies real runtime/code surfaces, not topic-only intent.
- The plan states what changes, what remains invariant, and how it should be validated.
- Removed target-state commands such as `plan tasks for` and `execute task` must not appear as required phases.

### Gate 2: Tracker alignment

- Runtime entity ownership fields (`milestone_id`, `feature_id`) match the plan scope.
- Task decomposition remains local to `FEATURE_PLANS.md`.
- Materialization and execution docs do not treat `Task` as a runtime-owned DEV_MAP node.
