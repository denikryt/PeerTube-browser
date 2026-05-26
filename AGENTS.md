# Project Rules

## Tests

- Preserve current working behavior before refactoring. Add characterization or regression tests around observable behavior before moving production code.
- Use TDD by default for new behavior and bug fixes: write the failing behavior test first, implement the change, then refactor after it passes.
- Prefer pytest for product behavior tests. Use Bash only for shell/static boundary checks, smoke wrappers, and command-level checks.
- Write tests as: defined system state + concrete action + observable result.
- Prefer real handlers, services, repositories, runtime paths, temporary databases, fixtures, and fakes over brittle mocks.
- Mock only outer boundaries such as network calls, external APIs, time, random IDs, filesystem edges, and heavyweight optional dependencies.
- Assert real effects: HTTP responses, persisted state, mappings, dedup decisions, gateway behavior, generated outputs, and data changes.
- Use deterministic unit/service tests for pure logic and scenario/API tests for externally visible behavior.
- Use contract tests to protect component boundaries.
- Use full smoke tests sparingly. They are useful, but they must not replace fast focused tests.
- Every new behavior needs tests.
- Every bug fix needs a regression test.

## Required Coverage

- Tests must cover behavior that is important to the product, not incidental implementation details.
- Boundary tests must protect the intended component separation between frontend, Client backend, Engine, crawler, jobs, and storage.
- Persistence tests must protect schema compatibility, identity handling, deduplication, and data migration behavior.
- Recommendation tests must protect scoring, filtering, mixing, fallback behavior, and response shape where those behaviors are changed or refactored.
- API tests must protect public routes, error behavior, request validation, response shape, and gateway behavior.
- Crawler and job tests must protect data-build behavior, progress tracking, retry/failure handling, and compatibility with Engine reads.
- Frontend tests must protect user-visible flows and API integration when frontend code changes.
- Operational tests must protect documented commands, deployment assumptions, and long-running job behavior when those areas change.

## Comments

- Write docstrings for every module, class, public function, and non-trivial method.
- Write comments for non-trivial logic, especially where behavior depends on invariants, compatibility constraints, failure handling, or subtle data mapping.
- Comments should explain why code exists, what contract it preserves, or what behavior it protects.
- Do not restate obvious syntax line by line.
- Prefer one clear comment before a subtle block over many weak inline comments.
- Keep comments short, factual, and human-readable.

## Design

- Build from observable behavior inward.
- Keep module and function responsibilities narrow and explicit.
- Do not put unrelated logic into one long module.
- Keep boundaries clear between handlers, services, repositories, data access, crawler code, formatting, UI, and domain logic.
- Preserve the project’s component ownership: frontend handles UI, Client backend handles browser-facing state and gateway behavior, Engine handles recommendations and read APIs, crawler/jobs handle data collection and derived artifacts.
- Treat routing, identity mapping, deduplication, recommendation output, gateway boundaries, schema compatibility, and retry behavior as correctness-critical.
- Refactor toward clarity, but do not overengineer.
- Code should be easy to scan, trace, test, and change safely.
- If code is hard to test through an appropriate scenario, service, or repository test, simplify the design.

## Documentation Maintenance

- Documentation is required maintenance, not optional cleanup.
- For every code, route, data model, gateway contract, deployment, behavior, crawler, job, or recommendation change, check whether documentation is affected.
- Read the purpose paragraph of each potentially relevant document before editing it.
- Update only documentation whose stated responsibility covers the changed concept.
- Do not dump unrelated details into nearby documentation files.
- Preserve the established formatting style of the document family being edited.
- If no documentation update is needed, be able to explain why the change is outside existing documentation boundaries.

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
- Additional blocks are allowed when the task needs them.
- Before writing or updating a plan, study the relevant code carefully.
- Plans must be based on the real codebase and current behavior, not vague conceptual descriptions.
- Plans must be concrete and implementation-oriented, with enough detail that a developer can execute them without rediscovering the design.
- Do not invent architecture, files, or implementation steps disconnected from the current project state.
- Include concrete examples, payloads, database rows, assertions, or function-level changes when they clarify implementation.
- Identify expected conflicts, compatibility risks, regression risks, and blind spots before implementation begins.
- Explicitly distinguish generic behavior, PeerTube-specific behavior, and project-specific behavior when relevant.
- If implementation requires work not described in the plan, stop and report the missing planning item before changing code.