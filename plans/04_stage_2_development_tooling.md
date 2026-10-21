# Stage 2: Establish Repository-Level Development Tooling

## Problem / Goal

The project now has Stage 0 characterization tests and Stage 1 cleanup, but it still does not have stable repository-level development tooling. A developer currently has to read multiple documents and remember several raw commands to verify the project. Python test discovery is not configured centrally, Python linting is not configured, there is no root command wrapper, and Python dependencies are still represented by one CUDA/GPU-heavy `engine/server/requirements.txt` file.

Stage 2 must make safe refactoring repeatable without changing product behavior, runtime architecture, API routes, database schema, crawler behavior, frontend behavior, or deployment semantics.

Current observed tooling state:

```text
Makefile                                missing
pyproject.toml                          missing
.editorconfig                           missing
engine/server/requirements.txt          exists, GPU-heavy compatibility file
client/frontend/package.json            exists, component-local Vite scripts
engine/crawler/package.json             exists, component-local crawler scripts
```

Current fast verification commands are documented in `docs/TESTING.md` and `docs/DEVELOPMENT.md`:

```bash
python3 -m compileall client/backend engine/server
python3 engine/server/db/jobs/tests/test-interaction-events.py
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
python3 -m pytest tests/contracts tests/repositories tests/client_backend tests/engine_api tests/recommendations tests/engine_data -q
```

Current dependency-sensitive checks are:

```bash
cd client/frontend && npm run build
cd engine/crawler && npm run build
bash tests/run-arch-split-smoke.sh
bash tests/run-installers-smoke.sh --dry-run-only
```

Current known dependency blockers from Stage 0:

```text
Engine broad server imports may require faiss.
client/frontend build requires node_modules with vite.
engine/crawler build requires node_modules with TypeScript.
Full-contour smoke requires Engine runtime dependencies and usable local DB/index/cache inputs.
```

The goal of Stage 2 is to introduce a thin, honest tooling layer that wraps the current verified commands, configures pytest/ruff in one place, documents prerequisite-sensitive commands, and prepares dependency splitting without breaking existing install/deployment instructions.

Stage 2 is not a code architecture refactor. It is not the stage for Client backend extraction, Engine route splitting, crawler module splitting, FastAPI migration, schema migration, or frontend component refactor.

## Expected Behavior

After Stage 2:

- Product runtime behavior is unchanged.
- Existing Stage 0 tests still pass.
- Existing boundary scripts still pass and remain directly runnable.
- A developer can run the fast regression baseline from the repository root with one command.
- Dependency-heavy checks are available from the repository root but clearly documented as requiring local prerequisites.
- Python product tests can be discovered by pytest without repeating every test directory manually.
- Python lint configuration exists but does not force unrelated large legacy cleanup in this stage.
- Node package scripts remain local to `client/frontend` and `engine/crawler`; Stage 2 does not introduce npm workspaces.
- `engine/server/requirements.txt` remains a compatibility install file for existing docs and deployment flows.
- Stage 2 adds only a dev/test dependency file; runtime/API/ML dependency splitting is deferred to a later dedicated plan.

Concrete expected root commands:

```bash
make test
make test-fast
make test-python
make test-boundaries
make build-frontend
make build-crawler
make test-smoke-arch
make test-installers-dry-run
make lint
```

Expected behavior of the commands:

```text
make test
  Alias for make test-fast. It is the default local fast regression command, not full CI.

make test-fast
  Runs only checks expected to work in a normal Python dev environment with pytest available and without Node dependencies, FAISS index files, or local production DB artifacts.

make test-python
  Runs the Stage 0 pytest characterization suite.

make test-boundaries
  Runs the shell boundary scripts directly.

make build-frontend
  Runs cd client/frontend && npm run build. If node_modules is missing, it fails honestly with the package-manager error.

make build-crawler
  Runs cd engine/crawler && npm run build. If node_modules is missing, it fails honestly with the package-manager error.

make test-smoke-arch
  Runs tests/run-arch-split-smoke.sh and remains prerequisite-sensitive.

make test-installers-dry-run
  Runs tests/run-installers-smoke.sh --dry-run-only.

make lint
  Runs ruff on the Stage 0/Stage 1 maintained Python surfaces selected in this plan. It must not require cleaning every legacy Python file in the repository before Stage 3+ refactors.
```

`make test` must be an alias for `make test-fast`. It is the default fast regression command, not a full CI substitute and not a dependency-heavy build/smoke suite.

## Architecture

Stage 2 adds repository-level tooling around the existing architecture. It must not change component ownership.

Current component command ownership remains:

```text
Root Makefile
  -> wraps existing root, Python, shell, frontend, crawler, and smoke commands

pyproject.toml
  -> configures pytest discovery and Python linting

client/frontend/package.json
  -> remains the owner of frontend dev/build scripts

engine/crawler/package.json
  -> remains the owner of crawler build/crawl scripts

engine/server/requirements.txt
  -> remains compatibility install file for existing Engine deployment docs
```

Target command layering:

```text
Developer at repo root
  -> make test-fast
      -> compileall
      -> engine/server/db/jobs/tests/test-interaction-events.py
      -> boundary scripts
      -> pytest Stage 0 suites

Developer at repo root
  -> make build-frontend
      -> cd client/frontend && npm run build

Developer at repo root
  -> make build-crawler
      -> cd engine/crawler && npm run build

Developer at repo root
  -> make test-smoke-arch
      -> bash tests/run-arch-split-smoke.sh
```

The Makefile is a wrapper, not a new workflow engine. It should be readable and directly map targets to commands documented in `docs/TESTING.md`.

Python tooling architecture:

```text
pyproject.toml
  [tool.pytest.ini_options]
    testpaths = Stage 0 product test directories
    pythonpath = ["."] if needed by current imports
    addopts = concise output appropriate for fast regression checks

  [tool.ruff]
    target-version = py310 or py311 based on current supported runtime
    line-length = a reasonable project default
    exclude generated/local artifact directories

  [tool.ruff.lint]
    start with safe rule groups only
```

Do not configure mypy/pyright as mandatory in Stage 2 unless a stage-specific implementation discovery proves the current codebase can pass or the target is explicitly scoped to a narrow maintained surface. Type checking is allowed as a future optional target, but it must not become a blocking check in Stage 2.

Dependency organization architecture:

```text
engine/server/requirements.txt              existing compatibility file, unchanged
engine/server/requirements-dev.txt          dev/test/lint dependencies for the fast local checks
```

Stage 2 adds only `requirements-dev.txt`. API/runtime and ML/GPU dependency splitting is deferred to a dedicated dependency-split stage because it can affect deployment and data-build behavior.

## Touched Files

```text
AGENTS.md
README.md
docs/DEVELOPMENT.md
docs/TESTING.md
docs/DEPLOYMENT.md
engine/server/requirements.txt
client/frontend/package.json
engine/crawler/package.json
tests/check-client-engine-boundary.sh
tests/check-frontend-client-gateway.sh
tests/run-arch-split-smoke.sh
tests/run-installers-smoke.sh
```

Stage 2 should only edit a narrow subset of these files. The scripts and package files are listed because the plan is based on their existing commands; they should not be changed unless implementation discovers that a wrapper cannot call them directly.

## New Files

```text
plans/04_stage_2_development_tooling.md
Makefile
pyproject.toml
.editorconfig
engine/server/requirements-dev.txt
```

Stage 2 must not add API/runtime or ML/GPU split requirements files. Those files belong to a later dependency-specific plan.

## Implementation Steps

### 1. Re-run the current baseline before adding tooling

Run the current Stage 0/Stage 1 checks before editing files:

```bash
python3 -m compileall client/backend engine/server
python3 engine/server/db/jobs/tests/test-interaction-events.py
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
python3 -m pytest tests/contracts tests/repositories tests/client_backend tests/engine_api tests/recommendations tests/engine_data -q
```

Record any unexpected failures before continuing. If a current fast check fails before tooling changes, stop and diagnose; do not hide a pre-existing regression behind Makefile or pytest config work.

### 2. Add a minimal root `Makefile`

Create `Makefile` with explicit, thin targets. Use commands that already exist and are documented.

Required targets:

```makefile
.PHONY: test test-fast test-python test-boundaries test-python-compile test-legacy-interaction-events build-frontend build-crawler test-smoke-arch test-installers-dry-run lint

test: test-fast

test-fast: test-python-compile test-legacy-interaction-events test-boundaries test-python

test-python-compile:
	python3 -m compileall client/backend engine/server

test-legacy-interaction-events:
	python3 engine/server/db/jobs/tests/test-interaction-events.py

test-boundaries:
	bash tests/check-client-engine-boundary.sh
	bash tests/check-frontend-client-gateway.sh

test-python:
	python3 -m pytest -q

build-frontend:
	cd client/frontend && npm run build

build-crawler:
	cd engine/crawler && npm run build

test-smoke-arch:
	bash tests/run-arch-split-smoke.sh

test-installers-dry-run:
	bash tests/run-installers-smoke.sh --dry-run-only

lint:
	python3 -m ruff check tests client/backend/lib engine/server/data engine/server/api/recommendations engine/server/api/handlers/internal_events.py engine/server/api/handlers/video.py
```

The exact `lint` paths may be adjusted during implementation based on real ruff output, but the principle is important: lint the maintained/test-heavy surfaces first, not the entire repository if legacy modules would force unrelated cleanup.

Do not add targets that mutate local services, install systemd units, delete DB files, or run crawler jobs by default.

### 3. Add `pyproject.toml` for pytest and ruff

Create a minimal `pyproject.toml`.

Recommended pytest config:

```toml
[tool.pytest.ini_options]
testpaths = [
  "tests/contracts",
  "tests/repositories",
  "tests/client_backend",
  "tests/engine_api",
  "tests/recommendations",
  "tests/engine_data",
]
pythonpath = ["."]
addopts = "-q"
```

Do not include `engine/server/api/tests` in pytest `testpaths` during Stage 2 because the existing broad Engine server test path is currently blocked by `faiss` imports in a normal environment. Keep that limitation documented in `docs/TESTING.md`.

Recommended ruff starting point:

```toml
[tool.ruff]
target-version = "py310"
line-length = 100
exclude = [
  ".git",
  ".venv",
  "venv",
  "node_modules",
  "client/frontend/dist",
  "engine/crawler/dist",
  "__pycache__",
  ".pytest_cache",
]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = []
```

Stage 2 introduces `ruff check` only. Do not introduce `ruff format` in this stage; formatting normalization belongs to a later style-normalization stage. If `ruff check` on the selected maintained surfaces exposes many pre-existing style-only issues, do not broaden ignore rules blindly. Either narrow the `make lint` path to Stage 0/Stage 1 maintained files or document lint as a non-blocking command until a later lint-cleanup plan.

### 4. Add `.editorconfig`

Create `.editorconfig` for consistent whitespace across Python, TypeScript, Markdown, shell, JSON, and YAML.

Suggested content:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 2

[*.py]
indent_size = 4

[*.sh]
indent_size = 2

[Makefile]
indent_style = tab

[*.md]
trim_trailing_whitespace = false
```


### 5. Add `engine/server/requirements-dev.txt`

Create a dev/test requirements file that installs only tooling needed for Stage 0/Stage 2 checks, not the full ML runtime.

Required initial content:

```text
pytest>=8,<9
ruff>=0.8,<1
```

Use conservative version ranges instead of exact pins. Exact pins or lock files should wait until CI/reproducibility policy is defined.

Do not remove or replace `engine/server/requirements.txt`. Existing deployment docs currently install that file and must continue to work.

### 6. Document the new commands in `docs/TESTING.md`

Update the purpose-relevant sections of `docs/TESTING.md`.

Required changes:

- Add a short “Root command wrappers” section.
- State that `make test-fast` is the preferred local pre-refactor check.
- State that `make test-python` runs the pytest characterization suite through `pyproject.toml` test discovery.
- State that `make build-frontend`, `make build-crawler`, and smoke targets are prerequisite-sensitive.
- Keep the raw commands visible so developers can debug without Makefile indirection.

Example text:

```text
Use `make test-fast` for the normal fast regression baseline. It wraps the same commands listed below and does not run Node builds or full-contour smoke checks.
```

Do not remove the Stage 0 baseline notes or dependency blockers; Stage 2 tooling should clarify them, not erase them.

### 7. Document developer setup in `docs/DEVELOPMENT.md`

Update the purpose-relevant sections of `docs/DEVELOPMENT.md`.

Required additions:

```bash
python3 -m pip install -r engine/server/requirements-dev.txt
make test-fast
make lint
```

Also document that frontend and crawler dependencies are still installed in their component directories:

```bash
cd client/frontend && npm install
cd engine/crawler && npm install
```

Do not introduce npm workspaces in docs. Do not imply that `npm install` at repository root exists.

### 8. Update `README.md` minimally

Add or update a concise development verification pointer only if it improves discoverability.

Acceptable README addition:

```markdown
## Development checks

Use `make test-fast` for the fast regression baseline. See `docs/DEVELOPMENT.md` and `docs/TESTING.md` for setup, dependency-heavy checks, and smoke tests.
```

Do not move operational deployment details into README in this stage.

### 9. Defer runtime dependency splitting

Do not add `requirements-api.txt`, `requirements-ml-cpu.txt`, or `requirements-ml-gpu-cu121.txt` in Stage 2.

Required actions:

- Add only `engine/server/requirements-dev.txt`.
- Leave `engine/server/requirements.txt` as the compatibility install file.
- Add a note in `docs/DEVELOPMENT.md` that API/runtime and ML/GPU dependency splitting is deferred to a later dependency-specific plan.

This keeps Stage 2 focused on repeatable development commands and avoids changing deployment assumptions.

### 10. Run the new root commands

After adding tooling, run:

```bash
make test-fast
make test-python
make test-boundaries
make lint
```

If `ruff` is not installed in the current environment, run:

```bash
python3 -m pip install -r engine/server/requirements-dev.txt
```

only if environment policy permits installing local dependencies. If installation is not possible, document the command as blocked by missing dev dependency and still run the non-ruff checks.

Do not require these commands in Stage 2:

```bash
make build-frontend
make build-crawler
make test-smoke-arch
```

They should exist, but they are prerequisite-sensitive. If run, classify failures as prerequisite failures or product failures according to `docs/TESTING.md`.

### 11. Stop conditions

Stop and update this plan before implementation continues if any of these happen:

- `make test-fast` cannot wrap existing Stage 0 commands without changing production code.
- pytest discovery through `pyproject.toml` changes which tests run in a way that hides Stage 0 tests.
- ruff requires broad production-code cleanup outside the Stage 0/Stage 1 maintained surfaces.
- adding `requirements-dev.txt` conflicts with existing deployment docs or installer scripts.
- any Makefile target would need to mutate systemd services, DB files, crawler state, or local production artifacts by default.
- Node package scripts need to be renamed to support root wrappers.
- implementation discovers that `docs/DEVELOPMENT.md` or `docs/TESTING.md` already define contradictory command semantics.

## Tests

Stage 2 does not require new product behavior tests. It verifies tooling by running existing Stage 0 tests through new root commands.

Required checks before implementation:

```bash
python3 -m compileall client/backend engine/server
python3 engine/server/db/jobs/tests/test-interaction-events.py
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
python3 -m pytest tests/contracts tests/repositories tests/client_backend tests/engine_api tests/recommendations tests/engine_data -q
```

Required checks after implementation:

```bash
make test
make test-fast
make test-python
make test-boundaries
```

`make test` must run the same fast baseline as `make test-fast`.

Required lint check if dev dependencies are available:

```bash
make lint
```

Optional prerequisite-sensitive checks:

```bash
make build-frontend
make build-crawler
make test-smoke-arch
make test-installers-dry-run
```

Installer dry-run smoke must remain separate from `make test-fast` because installer scripts are operational checks, not fast product regression checks.

Expected behavior of test results:

- `make test-fast` should pass in the same environment where Stage 0 pytest tests pass.
- `make test-python` should run the Stage 0 pytest directories via `pyproject.toml` discovery.
- `make test-boundaries` should run the two existing shell boundary scripts.
- `make lint` should either pass on the selected maintained surfaces or the implementation must narrow/fix the Stage 2 lint surface without broad unrelated refactoring.
- Node build and smoke targets may fail when prerequisites are missing; those failures must be documented and not hidden.

## Documentation Maintenance

Update only documents whose current purpose covers Stage 2 tooling:

```text
docs/TESTING.md
  Root command wrappers, pytest discovery, fast vs dependency-heavy checks, smoke prerequisites.

docs/DEVELOPMENT.md
  Developer setup, dev dependencies, root commands, component-local Node installs.

README.md
  Short discoverability pointer to make test-fast and docs.

docs/DEPLOYMENT.md
  Only if dependency files used by deployment are changed. If requirements.txt remains the deployment install file, no deployment doc change is required except possibly a note that dev requirements are not deployment requirements.
```

Before editing each document, read its opening purpose or surrounding section and update only that section.

## Regression and Blind-Spot Analysis

### Regressions Stage 2 must catch

- A root command accidentally omits an existing Stage 0 check.
- pytest discovery excludes one of the Stage 0 product test directories.
- Makefile targets hide dependency failures or silently skip checks.
- Makefile targets run dependency-heavy Node builds as part of the fast baseline.
- Makefile targets mutate local DB, systemd, crawler, or production artifacts by default.
- ruff configuration forces unrelated legacy cleanup and expands the stage beyond tooling.
- dependency file changes break existing deployment instructions that use `engine/server/requirements.txt`.
- docs claim a command is mandatory even though it is prerequisite-sensitive.

### Blind spots that remain after Stage 2

- Full Python dependency split is intentionally deferred to a later dependency-specific plan.
- FAISS-heavy Engine server imports remain a later architecture/dependency problem.
- Node workspaces are not introduced; frontend and crawler still manage dependencies independently.
- Type checking is deferred until after Client/Engine modules are split into narrower units; large legacy modules may still be untyped.
- CI is not introduced unless a later stage or explicit plan adds it.
- Lint coverage may be intentionally limited to maintained/test-heavy surfaces until later refactors reduce legacy complexity.

## Compatibility and Protocol Notes

Generic behavior:

- Root command wrappers are a developer convenience and should map to explicit underlying commands.
- pytest configuration is a test discovery mechanism, not a product behavior contract.

Project-specific behavior:

- `make test-fast` must protect the PeerTube Browser Stage 0 safety net.
- Frontend and crawler Node commands remain component-local because this repository does not currently use npm workspaces.
- `engine/server/requirements.txt` remains the compatibility deployment install file in Stage 2.
- Engine ML/GPU dependencies are project-specific runtime/index-build concerns and should not be forced into fast developer tooling.

PeerTube-specific behavior:

- None. Stage 2 tooling does not alter PeerTube crawler API behavior, federation assumptions, recommendation behavior, or data-build semantics.

## Open Questions

None for the current Stage 2 scope.

## Decisions

- `make test` is an alias for `make test-fast`.
- Stage 2 introduces `ruff check` only; `ruff format` is deferred to a later style-normalization stage.
- `engine/server/requirements-dev.txt` uses conservative version ranges: `pytest>=8,<9` and `ruff>=0.8,<1`.
- API/runtime and ML/GPU dependency split files are deferred to a dedicated dependency-split stage.
- Installer dry-run smoke remains a separate target and is not part of `make test-fast`.
- Type checking is deferred until after Client/Engine modules are split into narrower units.
