# Project Rules

## Tests

- Preserve working behavior before refactoring. For structural changes, add characterization or regression tests around the current observable behavior before moving production code.
- Use TDD by default for new behavior and bug fixes: write the failing behavior test first, implement the change, then refactor after the test is green.
- Prefer pytest for product behavior tests. Bash is appropriate for existing shell/static boundary checks, smoke wrappers, and command-level checks.
- Tests must be written as action in a defined system state -> observable result.
- An action means a specific operation under specific preconditions, system state, and input data.
- Tests must verify how the system behaves when that action happens in that state.
- Run behavior through real handlers, services, repositories, or runtime paths whenever practical.
- Assert real effects:
  HTTP status and response shape, SQLite rows, mappings, dedup decisions, recommendation output, gateway forwarding, persisted profile state, and crawler/data-build results.
- Do not rely mainly on "mock was called" tests.
- Mock only outer boundaries:
  network, PeerTube/API edges, filesystem where necessary, time, random IDs, and heavyweight optional dependencies such as ANN/FAISS index access.
- Prefer fakes, fixtures, temporary SQLite databases, and small harnesses over brittle mocks.
- Use deterministic unit/service tests for pure product logic:
  recommendation scoring, filtering, mixing, profile parsing, config parsing, payload mapping, validation, and repository behavior.
- Use scenario/API tests for externally observable behavior:
  Client profile actions, Client->Engine gateway behavior, Engine ingest, recommendation responses, video metadata responses, and crawler/update flows.
- Use contract tests for component boundaries:
  frontend -> Client backend, Client backend -> Engine HTTP API, crawler/jobs -> Engine-readable SQLite schema.
- Use smoke tests sparingly for full local contours. Smoke tests are useful, but they are not a replacement for fast characterization tests.
- Every new behavior needs tests.
- Every bug fix needs a regression test.

## Required Coverage

Required coverage must match this project, not generic bridge/sync systems.

- Frontend gateway boundary:
  frontend code must use the Client backend and must not call Engine internal/read APIs directly.
- Client/Engine boundary:
  Client backend must not import Engine modules or read Engine DB files directly; it talks to Engine over HTTP.
- Client profile and write behavior:
  user profile reads, likes, unlikes, resets, and user actions must be covered through observable DB and HTTP effects.
- Client read proxy behavior:
  allowlisted routes, sanitized query/body fields, upstream response preservation, and controlled error handling must be covered.
- Engine internal event ingest:
  event normalization, event_id idempotency, duplicate handling, aggregate interaction signals, invalid payload errors, and current partial-failure behavior must be covered.
- Recommendation behavior:
  scoring, filtering, deduplication, author/channel/instance caps, profile selection, mixing, fallback behavior, debug output, and response shape must be covered with deterministic tests.
- Similarity candidate behavior:
  cache lookup, fallback candidate generation, metadata resolution, seed/source-author exclusions, caps, scores, and limit behavior must be covered.
- Video metadata behavior:
  lookup by id/uuid/host, moderation/error filtering, dynamic PeerTube metadata overlay, DB fallback fields, and frontend-compatible response shape must be covered.
- Random/recent/popular fallback feeds:
  ordering, filtering of unusable rows, limit behavior, and duplicate avoidance where guaranteed by current behavior must be covered.
- SQLite schema compatibility:
  crawler schema and update-job outputs must contain the tables/columns consumed by Engine read paths.
- Crawler/data-build behavior:
  repository writes, crawl progress, retry/error recording, and fake PeerTube API integration paths must be covered when those areas are changed.
- Frontend behavior:
  feed rendering, video page rendering, like button state, API error states, and build/static gateway checks must be covered when frontend code is changed.
- Deployment and job behavior:
  updater stage order, lock/resume behavior, partial failure handling, and documented command compatibility must be covered when operational code changes.

## Comments

- Writing comments is mandatory for non-trivial code. Do not leave subtle behavior undocumented.
- Writing docstrings is mandatory for every module, class, public function, and non-trivial method.
- Docstrings must state responsibility, important constraints, and behavior.
- Every non-trivial function, handler, operation, and subtle code block must include comments explaining intent, invariants, constraints, or failure handling.
- If there is any doubt whether a comment is needed, write the comment.
- If there is any doubt whether a docstring is needed, write the docstring.
- Missing comments or docstrings are a project-rules violation.
- Comments must explain why the code exists, what contract it preserves, and what behavior it protects.
- Docstrings describe what the module/class/function/method is responsible for; inline comments explain why a subtle block works the way it does.
- Comments do not restate obvious syntax line by line, but they must still be present.
- Add comments especially around:
  dedup, retries, identity mapping, Client->Engine gateway behavior, bridge ingest compatibility, recommendation scoring/mixing, schema constraints, crawler/update failure paths, and deployment compatibility code.
- Prefer one strong comment before a subtle block over many weak inline comments, but never leave non-trivial logic uncommented.
- Keep comments short, factual, and human-readable.

## Design

- Build from observable behavior inward.
- Treat routing, identity mapping, dedup, recommendation output, gateway boundaries, schema compatibility, and retry behavior as correctness-critical.
- Prioritize readable code, clear project navigation, and human-readable structure.
- Keep module and function responsibilities narrow and explicit.
- Do not dump unrelated logic into one long module.
- Keep boundaries between handlers, services, repositories, data access, crawler code, formatting, and domain logic clear.
- Client backend owns browser-facing profile/write behavior and Engine gateway calls. It must not own recommendation ranking or Engine DB reads.
- Engine owns recommendation, metadata, internal ingest, and Engine-readable data access. It must not own browser profile persistence.
- Crawler/jobs own PeerTube data collection, update flows, derived artifacts, and schema production for Engine consumption.
- Frontend owns UI state, rendering, and calls to Client backend only.
- Refactor toward clarity, but do not overengineer.
- Code should be easy to scan, easy to trace, and easy to change safely.
- If code is hard to test through scenario, service, or repository tests, simplify the design.

## Documentation Maintenance

- Documentation is required maintenance, not optional cleanup.
- For every code, route, data model, gateway contract, deployment, behavior, crawler, job, or recommendation change, check whether documentation is affected.
- Read the purpose paragraph of each potentially relevant document before editing it.
- Update only documentation whose stated responsibility covers the changed concept.
- Do not dump unrelated details into nearby documentation files.
- Preserve the established formatting style of the document family being edited.
- If no documentation update is needed, understand and be able to explain why the change is outside the existing documentation boundaries.

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
- Before writing a new plan or updating an existing plan, first study the relevant code carefully.
- Plans must be based on the real codebase and current behavior, not on vague conceptual descriptions.
- The plan must be concrete and implementation-oriented, not high-level filler.
- The plan must be well thought out and well described, but not padded with empty detail.
- When writing a plan, think through how the requested work can actually be implemented in this project.
- Base the plan on the real codebase, real constraints, and real integration points.
- Do not invent architecture, files, or implementation steps disconnected from the current project state.
- Plans must include concrete implementation examples, not only conceptual descriptions.
- Plans must describe function-level or module-level changes when the affected code path is known.
- Plans should include example inputs, outputs, payload shapes, database rows, or assertions when they clarify the intended implementation.
- Avoid shallow phrases such as "normalize payload" or "update handler" unless followed by the exact normalization rules or handler behavior.
- Implementation steps must be specific enough that a developer can execute them without re-discovering the whole design.
- Plans must identify expected conflicts and compatibility risks before implementation begins.
- Plans must include a regression and blind-spot analysis for behavior that could be accidentally changed.
- Plans must explicitly state when a proposed path is generic protocol behavior, PeerTube-specific behavior, or project-specific behavior.
- If implementation requires work that is not described in the plan, stop and report the missing planning item before changing code.

- Plans must be complete before implementation begins; do not rely on rewriting the plan during implementation as the normal path.
- For every identified conflict, compatibility risk, regression risk, or blind spot, state the concrete implementation action that preserves existing behavior.
- If implementation encounters work outside the plan, stop implementation and report the missing planning item instead of changing unplanned code.
