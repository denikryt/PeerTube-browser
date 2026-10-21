# Stage 9: Rationalize Jobs, Updater, and Deployment Docs

## Problem / Goal

The project now has clearer Client backend, Engine API, recommendation, schema, crawler, and frontend boundaries. The remaining operational weak spot is the updater/data-build job layer, especially `engine/server/db/jobs/updater-worker.py`.

`updater-worker.py` currently combines several responsibilities in one long executable script:

- CLI argument parsing and default path resolution.
- logging setup.
- single-run lock acquisition and stale-lock cleanup.
- systemd stop/start command construction and execution.
- generic command execution and GPU-to-CPU fallback behavior.
- JoinPeerTube whitelist fetching and sync planning.
- moderation denylist loading and prod/staging purge behavior.
- staging DB recreation, seeding, delta counting, and local-health pruning.
- crawler command construction and execution.
- embedding, merge, popularity, ANN, and similarity precompute stage command construction.
- test-only failure injection and replacement embedding injection.
- temp-file cleanup and final runtime logging.

The goal of Stage 9 is to make the operational updater code readable, testable, and documented while preserving current operational behavior. This stage must not redesign the data-build pipeline, change job semantics, change installer behavior, or change runtime service contours.

The current updater pipeline order must remain:

```text
lock
-> moderation/JoinPeerTube sync planning
-> staging init or resume
-> staging seed from prod, unless sync-join mode skips it
-> staging denylist prune
-> crawl instances
-> optional local-health staging prune
-> crawl channels
-> crawl videos
-> refresh channel video counts
-> build staging embeddings with GPU/CPU behavior preserved
-> optional test replacement embedding injection
-> count staging deltas
-> optional service stop
-> merge staging into prod
-> post-merge denylist safety prune
-> recompute popularity incremental
-> build ANN index with GPU/CPU behavior preserved
-> precompute similarity cache with GPU/CPU behavior preserved
-> optional service start
-> temp-file cleanup
-> final timing log
```

Stage 9 is a behavior-preserving split. It should improve code ownership and testability, not change outputs.

## Expected Behavior

After Stage 9:

- `engine/server/db/jobs/updater-worker.py` remains the executable CLI entrypoint.
- Existing command invocation remains valid:

```bash
python3 engine/server/db/jobs/updater-worker.py --gpu --skip-local-dead
```

- Existing CLI flags remain valid and keep their current defaults and meanings.
- `--help` output remains functionally equivalent: same flags, defaults, and descriptions unless formatting changes are produced by the existing `CompactHelpFormatter`.
- Default path resolution remains based on the same repository-relative paths and `server_config` values.
- Default Engine service-name resolution keeps the same installer fallback behavior:
  - prefer `engine/install-updater-service.sh --print-default-engine-service-name`;
  - fall back to `engine/install-engine-service.sh --print-default-service-name` where applicable;
  - fall back to `peertube-engine-dev` for dev and `peertube-engine` for prod.
- Lock behavior remains unchanged:
  - active lock PID blocks a second run;
  - stale lock PID is removed and replaced;
  - lock file is removed when the run exits normally or through an exception after acquiring it.
- `run_cmd` keeps current logging and `subprocess.run(..., check=True)` behavior.
- GPU/CPU fallback behavior remains unchanged:
  - commands without `--gpu` run once;
  - commands with `--gpu` retry once with GPU flags removed and `--cpu` appended if the first run raises `subprocess.CalledProcessError`.
- `systemctl_cmd` keeps current command construction and sudo prefix behavior.
- `--skip-systemctl` continues to skip stop/start entirely.
- When service stop succeeds and a later merge/post-merge stage fails, the service still starts in a `finally` path.
- `--dry-run` remains supported only with `--sync-join-whitelist`.
- `--sync-join-whitelist` keeps current stale-host purge safety behavior:
  - dry run returns after logging a delete plan;
  - non-dry-run stale purge requires `--yes`;
  - denylisted hosts are excluded from effective JoinPeerTube hosts.
- Staging DB behavior remains unchanged:
  - no `--resume-staging`: remove DB plus WAL/SHM sidecars and run `schema.sql`;
  - `--resume-staging` with existing staging DB: reuse it;
  - `crawl_state` is still created in staging;
  - prod instances and channels are seeded into staging only when not in sync-join mode.
- Crawler command names, script paths, flags, order, and cwd remain unchanged.
- Embedding, merge, popularity, ANN, and similarity commands keep their current arguments and cwd.
- Test-only flags keep current behavior:
  - `--inject-replace-embedding-for-test`;
  - `--fail-before-merge`;
  - `--fail-during-ann-build`;
  - `--fail-after-merge-before-similarity`.
- Existing smoke tests remain available and are not replaced by unit tests.
- Installer scripts remain behaviorally unchanged. Stage 9 may document installer/updater behavior, but it must not rewrite installer logic.
- No Engine API, Client backend, frontend, crawler DB schema, recommendation, schema migration, or runtime API behavior changes are introduced.

## Architecture

Stage 9 introduces an internal Python package for updater/job orchestration while keeping executable script compatibility.

Current operational boundary:

```text
systemd / shell / developer
  -> engine/server/db/jobs/updater-worker.py
      -> crawler dist CLIs
      -> Python DB jobs
      -> systemctl stop/start
      -> prod/staging SQLite DBs
      -> ANN and similarity artifacts
```

Target Stage 9 boundary:

```text
systemd / shell / developer
  -> engine/server/db/jobs/updater-worker.py       # compatibility CLI wrapper
      -> engine.server.db.jobs.updater.cli         # args/defaults
      -> engine.server.db.jobs.updater.paths       # resolved paths and required-file checks
      -> engine.server.db.jobs.updater.locks       # single-run lock
      -> engine.server.db.jobs.updater.commands    # command runner, CPU fallback, systemctl command
      -> engine.server.db.jobs.updater.sync        # JoinPeerTube sync planning and purge helpers
      -> engine.server.db.jobs.updater.staging     # staging init/seed/delta/prune helpers
      -> engine.server.db.jobs.updater.pipeline    # stage order and orchestration
```

### Ownership after Stage 9

`updater-worker.py` remains responsible for:

```text
- executable shebang compatibility;
- setting up import paths needed by direct script execution;
- calling parse_args/setup logging/pipeline run;
- preserving the current direct CLI entrypoint path.
```

`engine/server/db/jobs/updater/cli.py` owns:

```text
- parser construction;
- current CLI flags, defaults, choices, and help text;
- default prod/staging/index/similarity/log/lock path resolution;
- default service-name resolution via existing installer scripts.
```

`engine/server/db/jobs/updater/commands.py` owns:

```text
- command execution;
- elapsed-time logging;
- GPU-to-CPU fallback transformation;
- systemctl command construction;
- fake command runner seam used by tests.
```

`engine/server/db/jobs/updater/locks.py` owns:

```text
- pid liveness checks;
- lock-file creation/removal;
- stale-lock replacement;
- active-lock error behavior.
```

`engine/server/db/jobs/updater/sync.py` owns:

```text
- JoinPeerTube host fetch shape handling;
- prod host listing;
- denylist loading;
- host-file temp writing;
- prod and staging purge helpers.
```

`engine/server/db/jobs/updater/staging.py` owns:

```text
- DB sidecar removal;
- staging DB initialization from crawler schema;
- staging seed from prod;
- shared-column calculation;
- staging delta counts;
- local non-ok host pruning;
- test replacement embedding injection.
```

`engine/server/db/jobs/updater/pipeline.py` owns:

```text
- high-level updater stage order;
- required-file validation;
- construction of crawler/job commands in current order;
- dry-run and sync-join branch behavior;
- service stop/start finally behavior;
- temp-file cleanup;
- final timing log.
```

### Explicit non-ownership for Stage 9

Stage 9 must not own or change:

```text
- crawler TypeScript DB/schema modules from Stage 7;
- Engine API routes/services from Stage 4;
- recommendation config/types from Stage 5;
- schema migration ownership from Stage 6;
- frontend code from Stage 8;
- installer systemd unit generation behavior;
- FAISS/index internals;
- merge rules semantics;
- crawler network traversal or PeerTube API behavior.
```

If a code path would require one of those changes, Stage 9 implementation must keep that behavior in the existing module and document it as deferred. It must not opportunistically expand the scope.

## Touched Files

```text
Makefile
README.md
docs/ARCHITECTURE.md
docs/DATA_BUILD.md
docs/DEPLOYMENT.md
docs/DEVELOPMENT.md
docs/TESTING.md
engine/server/db/jobs/updater-worker.py
engine/server/db/jobs/docs/UPDATER_WORKER.md
engine/server/db/jobs/tests/test-orchestrator-smoke.py
pyproject.toml
```

`AGENTS.md` is explicitly out of scope for Stage 9. The current project rules already cover planning, compatibility documentation, concrete risk actions, and behavior-preserving implementation. Do not edit project rules as part of Stage 9.

`engine/server/db/jobs/tests/test-orchestrator-smoke.py` should only be touched if import paths or docs references need to reflect the new package layout. Its smoke behavior must not be weakened.

## New Files

```text
plans/11_stage_9_jobs_updater_operational_split.md
docs/UPDATER_COMPATIBILITY.md
engine/server/db/jobs/updater/__init__.py
engine/server/db/jobs/updater/cli.py
engine/server/db/jobs/updater/commands.py
engine/server/db/jobs/updater/locks.py
engine/server/db/jobs/updater/paths.py
engine/server/db/jobs/updater/pipeline.py
engine/server/db/jobs/updater/staging.py
engine/server/db/jobs/updater/sync.py
engine/server/db/jobs/updater/types.py
tests/jobs/test_updater_cli_characterization.py
tests/jobs/test_updater_commands.py
tests/jobs/test_updater_locks.py
tests/jobs/test_updater_staging.py
tests/jobs/test_updater_sync.py
tests/jobs/test_updater_pipeline_commands.py
tests/jobs/test_updater_service_restart.py
```

If implementation shows that `paths.py` would only contain trivial aliases, it may still be created with a small `ResolvedUpdaterPaths` type and required-file validation because it creates a stable seam between CLI/defaults and pipeline execution.

## Implementation Steps

### 1. Confirm current baseline before changes

Run the current fast checks before changing code:

```bash
make test
make lint
python3 engine/server/db/jobs/tests/test-interaction-events.py
python3 engine/server/db/jobs/updater-worker.py --help
```

If `python3 engine/server/db/jobs/updater-worker.py --help` imports optional FAISS-heavy Engine startup code unexpectedly, the implementation action is not to add FAISS isolation. Instead, inspect the direct import path and keep updater CLI imports limited to `server_config` values already used by `parse_args`.

### 2. Add focused tests before moving behavior

Add new pytest tests under `tests/jobs/` before splitting production code. These tests must use fake command runners, temporary SQLite databases, temporary files, and monkeypatched network/service boundaries. They must not run real crawler CLIs, real systemctl, real FAISS, or real network calls.

#### 2.1 CLI characterization

File:

```text
tests/jobs/test_updater_cli_characterization.py
```

Required cases:

```text
- parse_args accepts current important flags and keeps current defaults for mode, GPU, lock file, max caps, dry-run, sync-join, systemctl flags, and crawler dir.
- default service-name resolution falls back to peertube-engine-dev for dev and peertube-engine for prod when installer scripts are unavailable or fail.
- --dry-run without --sync-join-whitelist remains a pipeline-level error, not an argparse error.
```

Concrete assertions:

```python
args = parse_args(["--mode", "dev", "--cpu", "--skip-systemctl"])
assert args.mode == "dev"
assert args.use_gpu is False
assert args.skip_systemctl is True
assert args.service_name == "peertube-engine-dev"
```

The new `parse_args(argv: list[str] | None = None)` function should accept an optional argv for tests while `updater-worker.py` uses `parse_args()` for normal CLI behavior.

#### 2.2 Command adapter tests

File:

```text
tests/jobs/test_updater_commands.py
```

Required cases:

```text
- _to_cpu_cmd removes --gpu and --gpu-device <N>, appends --cpu once, and preserves all other args order.
- run_with_cpu_fallback runs a CPU command once when --gpu is absent.
- run_with_cpu_fallback retries GPU command with CPU command after CalledProcessError.
- systemctl_cmd returns [systemctl, action, service] without sudo and [sudo, -n, systemctl, action, service] with sudo.
```

Use fake command runners rather than real subprocess calls.

#### 2.3 Lock tests

File:

```text
tests/jobs/test_updater_locks.py
```

Required cases:

```text
- active lock raises the same active-run error shape.
- stale PID lock is removed and replaced.
- lock file is removed after normal context exit.
- lock file is removed after exception inside the context.
```

Use temporary lock files and monkeypatch `_pid_alive`.

#### 2.4 Staging DB tests

File:

```text
tests/jobs/test_updater_staging.py
```

Required cases:

```text
- remove_db_with_sidecars removes .db, .db-wal, and .db-shm.
- init_staging_db executes a supplied schema and creates crawl_state.
- seed_staging_from_prod copies only shared channels columns and writes crawl_state stage_seeded_at/stage_seeded_from.
- count_staging_deltas returns current keys: instances_new, channels_new, videos_new, embeddings_new.
- prune_staging_local_non_ok_instances removes staging hosts whose prod health_status is non-ok and returns removed/remaining.
```

Use minimal temporary SQLite schemas that contain only the columns needed by each helper.

#### 2.5 Sync and purge tests

File:

```text
tests/jobs/test_updater_sync.py
```

Required cases:

```text
- fetch_join_hosts accepts both {"data": [...]} and list payload shapes.
- fetch_join_hosts normalizes hosts to lowercase trimmed values and skips empty hosts.
- list_prod_hosts returns lowercase trimmed host set.
- write_hosts_file writes sorted hosts and returns None for empty sets.
- purge_hosts returns aggregated counts from purge helpers.
```

Network calls must be monkeypatched at `urlopen`. Purge helpers may monkeypatch `purge_host_data` and `purge_similarity_for_host` if the test only targets orchestration and aggregation.

#### 2.6 Pipeline command sequence tests

File:

```text
tests/jobs/test_updater_pipeline_commands.py
```

Required cases:

```text
- normal non-sync run builds commands in the current order: instances, channels, videos, counts, embeddings, stop service, merge, recompute popularity, build ANN, precompute similarity, start service.
- --skip-systemctl removes stop/start commands while preserving all data-build commands.
- --sync-join-whitelist with no new hosts and no stale hosts skips crawler/merge/job commands and finishes early.
- --sync-join-whitelist --dry-run logs/plans purge and returns before staging/crawler/merge commands.
- denied hosts add --exclude-hosts-file to crawler commands.
- sync new hosts add --whitelist-file to instances command.
- GPU mode appends --gpu to embeddings and ANN/precompute commands exactly as current behavior does.
- CPU mode appends --cpu where current behavior does.
```

Use a fake command runner that records commands and returns success. Use fake functions for heavy DB/network pieces where the test is about command sequencing. Do not shell out.

#### 2.7 Service restart tests

File:

```text
tests/jobs/test_updater_service_restart.py
```

Required cases:

```text
- if service stop succeeds and merge command fails, start service is still recorded after the failure.
- if --skip-systemctl is set, neither stop nor start is recorded even when later commands fail.
- fail_before_merge triggers before service stop.
- fail_during_ann_build happens after merge and recompute popularity, then service start runs.
- fail_after_merge_before_similarity happens after ANN build, then service start runs.
```

Use fake command runner exceptions and assert command sequence. Do not use real systemctl.

### 3. Create updater package without changing behavior

Create:

```text
engine/server/db/jobs/updater/__init__.py
engine/server/db/jobs/updater/types.py
engine/server/db/jobs/updater/cli.py
engine/server/db/jobs/updater/commands.py
engine/server/db/jobs/updater/locks.py
engine/server/db/jobs/updater/paths.py
engine/server/db/jobs/updater/sync.py
engine/server/db/jobs/updater/staging.py
engine/server/db/jobs/updater/pipeline.py
```

All new modules must have docstrings. Public functions/classes must have docstrings explaining responsibility, constraints, and behavior.

Suggested internal types:

```python
@dataclass(frozen=True)
class UpdaterPaths:
    repo_root: Path
    script_dir: Path
    crawler_dir: Path
    crawler_dist: Path
    schema_path: Path
    prod_db: Path
    staging_db: Path
    index_path: Path
    index_meta_path: Path
    similarity_db: Path
    merge_rules: Path
    lock_file: Path

@dataclass
class CommandRunner:
    run: Callable[[list[str], Path | None], None]
```

If a type increases complexity without improving boundaries, prefer simple functions and explicit parameters. Do not introduce a dependency injection framework.

### 4. Move CLI/default ownership

Move from `updater-worker.py` into `updater/cli.py`:

```text
resolve_default_engine_service_name
parse_args
```

Required implementation actions:

- Keep current installer command fallback logic exactly.
- Keep `CompactHelpFormatter`.
- Add optional `argv` parameter to `parse_args` for tests.
- Keep default path calculations equivalent to current code.
- Keep direct script invocation behavior by calling `parse_args()` from `updater-worker.py` with no argv.

Compatibility action:

- `updater-worker.py` should re-export `resolve_default_engine_service_name` and `parse_args` as imported names if feasible. This preserves any local scripts/tests that load the script and call those functions directly.

### 5. Move command execution ownership

Move from `updater-worker.py` into `updater/commands.py`:

```text
run_cmd
_to_cpu_cmd
run_with_cpu_fallback
systemctl_cmd
```

Required implementation actions:

- Preserve `logging.info("run: ...")` display behavior.
- Preserve elapsed-time logging.
- Preserve `subprocess.run(cmd, cwd=cwd, check=True)` semantics.
- Add optional command-runner seam only as a parameter or small object used by tests; default behavior must still call subprocess.
- Keep `_to_cpu_cmd` behavior exactly, including removing `--gpu-device` and the following value.

Compatibility action:

- `updater-worker.py` should re-export these functions as imported names if feasible.

### 6. Move lock ownership

Move from `updater-worker.py` into `updater/locks.py`:

```text
_pid_alive
single_run_lock
```

Required implementation actions:

- Preserve `os.O_CREAT | os.O_EXCL | os.O_WRONLY` lock acquisition.
- Preserve active-lock RuntimeError wording closely enough that operational logs remain recognizable.
- Preserve stale PID removal and warning log.
- Preserve lock removal on normal and exceptional exits.

Compatibility action:

- `updater-worker.py` should re-export these functions as imported names if feasible.

### 7. Move sync/purge ownership

Move from `updater-worker.py` into `updater/sync.py`:

```text
fetch_join_hosts
list_prod_hosts
load_denied_hosts
write_hosts_file
purge_hosts
purge_hosts_from_staging
```

Required implementation actions:

- Preserve User-Agent string for JoinPeerTube requests.
- Preserve accepted JSON shapes for host payloads.
- Preserve host lowercase/trim normalization.
- Preserve dry-run propagation to `purge_host_data` and `purge_similarity_for_host`.
- Preserve optional similarity DB behavior: only open similarity DB when the file exists.
- Keep moderation helper imports from `data.moderation` here or in a small helper module; do not move moderation ownership.

Compatibility action:

- `updater-worker.py` should re-export these functions as imported names if feasible.

### 8. Move staging DB ownership

Move from `updater-worker.py` into `updater/staging.py`:

```text
remove_db_with_sidecars
init_staging_db
shared_columns
seed_staging_from_prod
count_staging_deltas
prune_staging_local_non_ok_instances
inject_replace_embedding_for_test
```

Required implementation actions:

- Preserve sidecar suffixes exactly: `-wal`, `-shm` appended to the full suffix.
- Preserve `crawl_state` table SQL.
- Preserve `stage_seeded_at` as millisecond epoch string.
- Preserve `stage_seeded_from` as prod DB path string.
- Preserve shared-column ordering from the left/main table.
- Preserve delta key names and SQL join keys.
- Preserve local non-ok health-status filtering and logging summary.
- Preserve replacement embedding mutation behavior.

Compatibility action:

- `updater-worker.py` should re-export these functions as imported names if feasible.

### 9. Extract pipeline orchestration without changing stage order

Move high-level `main` body after parsing/log setup into `updater/pipeline.py`.

Suggested function:

```python
def run_pipeline(args: argparse.Namespace) -> None:
    """Run the updater pipeline using parsed CLI args and current stage order."""
```

`updater-worker.py` should become:

```python
def main() -> None:
    args = parse_args()
    setup_logging(Path(args.logs).resolve())
    run_pipeline(args)
```

Required implementation actions:

- Keep required-file validation before acquiring lock, as current code does.
- Keep `logging.info("worker start ...")` before lock acquisition as current code does.
- Keep `pipeline_start = time.monotonic()` placement equivalent enough that final timing remains whole-run timing.
- Keep `--dry-run` validation before lock acquisition as current code does.
- Keep temp-file cleanup in an outer `finally` around the locked pipeline body.
- Keep service restart `finally` nested around merge/post-merge jobs.
- Keep early returns for sync dry-run and sync no-op behavior.
- Keep all command arguments exactly as current code emits them, including duplicated `--timeout` in the `channels_cmd` if the current code emits it. Stage 9 must not silently “fix” command quirks unless a dedicated behavior-change plan covers that change.

Compatibility action:

- If extracting `run_pipeline` requires a test seam, add optional keyword-only dependencies with defaults matching current behavior. Example:

```python
def run_pipeline(args, *, command_runner=run_cmd, clock=time.monotonic) -> None:
    ...
```

Do not make callers supply dependencies in production.

### 10. Keep `updater-worker.py` as a compatibility facade

After extraction, `updater-worker.py` should:

- keep the shebang;
- keep the top-level script path bootstrapping needed for direct execution;
- import and re-export moved helper functions where feasible;
- define `setup_logging` or import it from a small module if moved;
- define `main` as CLI wrapper;
- call `main()` under `if __name__ == "__main__"`.

The file should not become empty or disappear. Operational docs and systemd/installers must continue to reference the same path.

### 11. Document updater compatibility decisions

Create:

```text
docs/UPDATER_COMPATIBILITY.md
```

Every compatibility decision introduced or preserved by Stage 9 must be recorded with:

```text
Decision:
Reason:
Implementation action:
Tests:
Removal condition, if any:
```

Required entries:

```text
updater-worker.py remains the CLI compatibility facade
updater stage order is preserved
crawler dist CLI command names and flags are preserved
systemctl stop/start semantics are preserved
GPU-to-CPU fallback semantics are preserved
sync-join dry-run and --yes purge safety semantics are preserved
staging resume/init/seed semantics are preserved
legacy top-level helper function imports are preserved where feasible
known command quirks are preserved, including duplicated channels --timeout if present
```

### 12. Update operational docs only where responsibility matches

Update only sections whose responsibility covers Stage 9 changes:

```text
docs/DATA_BUILD.md
docs/DEPLOYMENT.md
docs/DEVELOPMENT.md
docs/TESTING.md
engine/server/db/jobs/docs/UPDATER_WORKER.md
README.md
```

Required documentation actions:

- `engine/server/db/jobs/docs/UPDATER_WORKER.md` must describe the new internal updater package at a high level while keeping the same external CLI path.
- `docs/DATA_BUILD.md` must keep current updater command examples and may link to `docs/UPDATER_COMPATIBILITY.md`.
- `docs/DEPLOYMENT.md` must not change installer commands except to note that updater internals were split without changing installer entrypoints.
- `docs/TESTING.md` must document the new job tests and whether they are part of `make test`.
- `docs/DEVELOPMENT.md` may mention where updater internals now live.
- `README.md` should only receive a short docs/navigation update if the existing docs list would otherwise omit the new compatibility document.

### 13. Update tooling only for Stage 9 maintained surface

Update:

```text
pyproject.toml
Makefile
```

Required actions:

- Add `tests/jobs` to pytest discovery.
- Add a `make test-jobs` target that runs `python3 -m pytest tests/jobs -q`.
- Keep `make test` / `make test-fast` as Python fast regression checks; including `tests/jobs` is acceptable because these tests must not shell out to real jobs.
- Extend `make lint` only to new Stage 9 maintained files:

```text
engine/server/db/jobs/updater
engine/server/db/jobs/updater-worker.py
tests/jobs
```

Do not add full `engine/server/db/jobs/*.py` lint coverage in Stage 9. That would turn this stage into unrelated legacy lint cleanup.

### 14. Preserve existing smoke tests

Do not delete or weaken:

```text
engine/server/db/jobs/tests/test-orchestrator-smoke.py
engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md
```

If the smoke test invokes `updater-worker.py`, it must continue to invoke the same path. Any smoke test updates must be limited to import-path compatibility or documentation wording.

## Tests

Stage 9 must add tests before moving production updater code. Required tests:

```bash
python3 -m pytest tests/jobs -q
```

Required full checks after implementation:

```bash
make test
make lint
python3 -m pytest tests/jobs -q
python3 engine/server/db/jobs/tests/test-interaction-events.py
python3 engine/server/db/jobs/updater-worker.py --help
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
```

Prerequisite-sensitive checks that should remain separate:

```bash
make build-crawler
make test-crawler-db
make build-frontend
make test-frontend
make test-installers-dry-run
```

Run them when dependencies/environment support them, but do not make Stage 9 success depend on Node/systemd availability.

### Behavior assertions required by Stage 9 tests

The new tests must assert:

```text
- command sequence and command arguments, not just that a stage function was called;
- lock file state before/during/after context use;
- SQLite row state for staging seed/delta/prune helpers;
- purge aggregation outputs;
- service start command after failures that happen after service stop;
- absence of service stop/start commands under --skip-systemctl;
- dry-run and sync no-op early-return behavior;
- current CLI defaults and fallback service names.
```

## Documentation Maintenance

Before editing each document, read its purpose/current opening section and update only matching sections.

Document responsibilities for Stage 9:

```text
docs/UPDATER_COMPATIBILITY.md
  Compatibility decisions introduced or preserved by the updater split.

engine/server/db/jobs/docs/UPDATER_WORKER.md
  Detailed updater behavior, stage order, lock/resume/failure semantics, and operational command reference.

docs/DATA_BUILD.md
  Data-build/updater command entrypoints and artifact flow.

docs/DEPLOYMENT.md
  Systemd/service/updater installer usage and operational verification.

docs/DEVELOPMENT.md
  Developer navigation for updater internals and job tests.

docs/TESTING.md
  How to run fast tests, jobs tests, smoke tests, and prerequisite-sensitive checks.

README.md
  High-level documentation navigation only, if needed.
```

Do not move detailed updater internals into `README.md`, `docs/ARCHITECTURE.md`, or unrelated compatibility docs.

## Regression and Blind-Spot Analysis

### Risk: stage order changes during extraction

Action: Add command-sequence tests before moving pipeline code. In implementation, centralize stage orchestration in `updater/pipeline.py` and keep the current command list order byte-for-byte where practical. Compare recorded fake-runner commands against expected ordered command names and key arguments.

### Risk: CLI defaults or flag behavior changes

Action: Move parser construction into `updater/cli.py` with an optional test argv parameter. Add tests for representative defaults and flags. Do not rename, remove, or repurpose any existing flag.

### Risk: service is not restarted after a post-stop failure

Action: Preserve the nested `try/finally` around merge/post-merge stages. Add tests where fake command runner raises after the stop command and assert the start command is still recorded.

### Risk: lock semantics change

Action: Move lock code into `updater/locks.py` without changing file open flags or RuntimeError shape. Add tests for active lock, stale lock, normal exit, and exception exit.

### Risk: GPU fallback changes

Action: Move `_to_cpu_cmd` and `run_with_cpu_fallback` mechanically. Add tests for `--gpu-device` removal, `--cpu` append, one-run CPU behavior, and retry-on-CalledProcessError behavior.

### Risk: sync-join purge safety changes

Action: Keep dry-run and `--yes` logic in pipeline with helper functions only for data retrieval/purge aggregation. Add tests for dry-run early return, no-op early return, and stale-host `--yes` requirement if that branch is extracted enough to test without real purge.

### Risk: staging DB shape changes

Action: Use the existing `schema.sql` path and move only helper logic. Add tests with minimal SQLite fixtures for sidecar removal, crawl_state creation, seeding, deltas, and local non-ok pruning. Do not edit `engine/crawler/schema.sql`.

### Risk: command quirks are accidentally “fixed”

Action: Preserve current emitted command arguments, including duplicated `--timeout` in `channels_cmd` if present. Document preserved quirks in `docs/UPDATER_COMPATIBILITY.md` and assert them in command-sequence tests where possible.

### Risk: installer behavior changes accidentally

Action: Do not edit installer scripts in Stage 9. Only update docs. Keep `updater-worker.py` path stable so systemd unit generation still points to the same entrypoint.

### Risk: tests become too mocked and miss real behavior

Action: Use fake command runners only at the shell boundary. Use real pipeline code, real SQLite temp DBs for staging helpers, and real lock files. Assert command arrays, DB rows, lock files, and return behavior.

### Risk: broad jobs lint cleanup causes unrelated churn

Action: Extend lint only to new updater package, wrapper, and tests. Do not lint/fix unrelated job scripts.

### Blind spot: full orchestrator smoke may require Node, FAISS, and real dataset artifacts

Action: Keep `engine/server/db/jobs/tests/test-orchestrator-smoke.py` as prerequisite-sensitive smoke. Do not make it part of the fast Stage 9 proof. Document when to run it in `docs/TESTING.md`.

### Blind spot: historical production updater runs may rely on importing helpers from `updater-worker.py`

Action: Re-export moved helpers from `updater-worker.py` where feasible. Document this facade behavior in `docs/UPDATER_COMPATIBILITY.md`. If a helper cannot be re-exported cleanly, keep that helper in the wrapper for Stage 9 instead of removing it.

### Blind spot: `setup_logging` ownership may be ambiguous

Action: Keep `setup_logging` in `updater-worker.py` or move it to a tiny `updater/logging.py` only if it improves clarity without changing behavior. If not moved, document that wrapper still owns logging setup.

### Blind spot: Stage 9 may expose bugs unrelated to split

Action: Do not fix unrelated updater bugs in Stage 9. Preserve current behavior and add compatibility notes if a known quirk is discovered. Behavior changes require a separate plan.

## Compatibility and Protocol Notes

Stage 9 behavior is project-specific operational behavior, not a generic crawler/update protocol.

- Crawler CLI command order and flags are project-specific to PeerTube Browser's current TypeScript crawler.
- Merge/popularity/ANN/similarity job order is project-specific data-build behavior.
- `--sync-join-whitelist` is project-specific JoinPeerTube reconciliation behavior.
- Systemd stop/start behavior is deployment-specific operational behavior.

Do not describe these as generic PeerTube or federation requirements.

## Non-Negotiable Implementation Constraints

### Constraint: updater-worker.py path remains stable

Required action:

Keep `engine/server/db/jobs/updater-worker.py` as the executable entrypoint. Do not rename it, delete it, or require installers/systemd/docs to call a new module path.

### Constraint: stage order remains stable

Required action:

Move code mechanically into `updater/pipeline.py` and verify ordered commands with fake-runner tests. If a section is too hard to move without changing order, keep that section in `updater-worker.py` and document it as deferred rather than changing behavior.

### Constraint: no installer script behavior changes

Required action:

Do not edit `install-service.sh`, `uninstall-service.sh`, `engine/install-engine-service.sh`, `client/install-client-service.sh`, or updater unit-generation logic. Update docs only.

### Constraint: no crawler schema or command rename

Required action:

Do not edit `engine/crawler/schema.sql` and do not rename crawler package scripts. The updater continues to call generated `engine/crawler/dist/*.js` files with current flags.

### Constraint: no full migration/deployment framework

Required action:

Do not add job state DBs, migration-state tables, or deployment orchestration frameworks in Stage 9. This stage is a split and documentation stage only.

### Constraint: no operational behavior fixes hidden inside refactor

Required action:

Preserve current quirks unless a separate behavior-change plan exists. If an undesirable behavior is found, document it in `docs/UPDATER_COMPATIBILITY.md` or a future-work note, but do not change it.

## Open Questions

None for the current Stage 9 scope.
