# Project Rules

## Working Principles

- Preserve the current working behavior before changing structure.
- Prefer small, reviewable changes with clear responsibility boundaries.
- Do not mix unrelated cleanup, refactoring, behavior changes, and tooling changes in one implementation step unless the active plan explicitly requires it.
- Treat the current component boundaries as correctness-critical until a later plan changes them.
- Keep the repository readable for a developer who wants to understand the product without learning obsolete local workflow systems.

## Tests

- Use regression-first refactoring: before moving or deleting production behavior, make sure existing characterization or regression checks cover the affected path.
- Use TDD by default for new behavior and bug fixes: write the failing behavior test first, implement, then refactor after the test is green.
- Prefer pytest for product behavior tests.
- Use bash for shell/static boundary checks, smoke wrappers, and command-level checks where shell is the natural interface.
- Tests must describe an action in a defined system state and assert the observable result.
- Assert real effects: HTTP status and response shape, SQLite rows, identity mappings, dedup decisions, recommendation output, gateway forwarding, persisted profile state, and data-build results.
- Do not rely mainly on "mock was called" tests.
- Mock only outer boundaries such as network, external APIs, filesystem edges, time, random IDs, and heavyweight optional dependencies.
- Prefer fakes, fixtures, temporary SQLite databases, and small harnesses over brittle mocks.
- Use deterministic unit/service tests for pure product logic.
- Use scenario/API tests for externally observable behavior.
- Use contract tests for component boundaries.
- Use smoke tests sparingly for full local contours; they complement but do not replace fast regression tests.
- Every new behavior needs tests.
- Every bug fix needs a regression test.

## Design

- Build from observable behavior inward.
- Keep module and function responsibilities narrow and explicit.
- Keep boundaries between handlers, services, repositories, data access, crawler code, formatting, and domain logic clear.
- Client backend owns browser-facing profile/write behavior and Engine gateway calls.
- Engine owns recommendation, metadata, internal ingest, and Engine-readable data access.
- Crawler and jobs own data collection, update flows, derived artifacts, and schema production for Engine consumption.
- Frontend owns UI state, rendering, and calls to the Client backend.
- Do not introduce direct coupling across these boundaries unless a plan explicitly defines and tests that change.
- Refactor toward clarity, but do not overengineer.
- Code should be easy to scan, easy to trace, and easy to change safely.

## Comments and Docstrings

- Write docstrings for modules, classes, public functions, and non-trivial methods.
- Document responsibility, important constraints, and behavior.
- Add comments for non-trivial logic where intent, invariants, compatibility, or failure handling are not obvious.
- Comments should explain why a block exists or what contract it protects; do not restate obvious syntax line by line.
- Keep comments short, factual, and human-readable.

## Documentation Maintenance

- Documentation is required maintenance, not optional cleanup.
- For every code, route, data model, gateway contract, deployment, behavior, crawler, job, or recommendation change, check whether documentation is affected.
- Read the purpose section or opening paragraphs of each potentially relevant document before editing it.
- Update only documentation whose stated responsibility covers the changed concept.
- Do not dump unrelated details into nearby documentation files.
- Preserve the established formatting style of the document family being edited.

## Plans

- When explicitly asked to create a plan, create a new Markdown file in `plans/`.
- Name the file with a numeric prefix and short slug, in the form `01_plan_name.md`.
- Choose the plan name from the task context. Do not ask for the name unless the context is genuinely ambiguous.
- A plan must include these blocks:
  `Problem / Goal`,
  `Expected Behavior`,
  `Architecture`,
  `Touched Files`,
  `New Files`,
  `Implementation Steps`,
  `Tests`,
  `Open Questions` if any.
- In `Touched Files` and `New Files`, write plain file paths, not Markdown links.
- Before writing or updating a plan, study the relevant code and current behavior.
- Plans must be concrete, implementation-oriented, and based on real files, real constraints, and real integration points.
- Plans must include concrete examples when they clarify the intended implementation.
- Plans must identify expected conflicts, compatibility risks, regression risks, and blind spots before implementation begins.
- Plans must explicitly state when proposed behavior is generic, PeerTube-specific, or project-specific.
- If implementation requires work that is not described in the active plan, stop and report the missing planning item before changing code.
