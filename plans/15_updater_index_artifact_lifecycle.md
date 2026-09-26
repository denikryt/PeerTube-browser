# Updater Index Artifact Lifecycle Cleanup

## Problem / Goal

The stable ANN/index identity migration changed long-lived ANN and random artifacts from SQLite `video_embeddings.rowid` to stable `video_index_ids.index_id`.

The updater already owns the automatic data-build path and already runs most of the required post-merge work:

```text
crawler -> staging embeddings -> merge -> popularity -> sync-video-index-ids -> FAISS -> similarity
```

However, the current updater is not yet a complete post-migration artifact lifecycle path:

1. It does not explicitly rebuild `random-cache.db` with `random_index_ids`.
2. Its `precompute-similar-ann.py` command still passes the ANN index path twice.
3. Required-file validation does not include `precompute-random-index-ids.py`.
4. CLI/path resolution does not expose the random cache DB path, even though Engine runtime uses `DEFAULT_RANDOM_CACHE_DB_PATH`.
5. Updater documentation still describes the old artifact set/order and does not mention stable index-id sync or random-cache rebuild.
6. Command-sequence tests currently preserve the duplicate similarity index argument as a compatibility quirk, but that quirk conflicts with the new stable-index artifact lifecycle and should be removed in this plan.

Goal: make `updater-worker.py` the single reliable automatic path for rebuilding post-migration discovery artifacts after prod DB updates:

```text
build embeddings in staging
-> merge staging into prod
-> post-merge purge/safety cleanup
-> recompute popularity
-> sync video_index_ids
-> rebuild FAISS with index_id ids
-> rebuild random_index_ids cache
-> precompute similarity cache from the rebuilt FAISS index
```

This is an operational cleanup plan. It must not introduce a new public API, change recommendation response shapes, change frontend behavior, or reintroduce rowid compatibility wrappers.

## Expected Behavior

After implementation, a normal updater run should emit this high-level command order:

```text
instances-cli.js
channels-cli.js
videos-cli.js
channels-videos-count-cli.js
build-video-embeddings.py
systemctl stop <service>
merge-staging-db.py
recompute-popularity.py --incremental
sync-video-index-ids.py
build-ann-index.py
precompute-random-index-ids.py
precompute-similar-ann.py
systemctl start <service>
```

The updater must rebuild the random cache explicitly after FAISS is rebuilt and before the service is restarted.

`precompute-similar-ann.py` must receive exactly one value for `--index`:

```text
--index <index-path>
```

It must not include the old duplicate positional `<index-path>` argument.

The random cache command should use the same default random cache target as Engine runtime:

```text
engine/server/db/random-cache.db
```

and should use the stable-index cache job:

```text
engine/server/db/jobs/precompute-random-index-ids.py
```

The updater should preserve existing behavior for:

- crawler stage order,
- staging reuse,
- JoinPeerTube sync dry-run and stale-host safety,
- denylist purge behavior,
- service stop/start finally behavior,
- GPU/CPU fallback behavior for heavy Python jobs,
- `--skip-systemctl`,
- failure injection flags already covered by tests.

## Architecture

### Existing owner

`engine/server/db/jobs/updater-worker.py` remains the executable entrypoint. Do not create a second updater command for this work.

The real orchestration owner is:

```text
engine/server/db/jobs/updater/pipeline.py
```

Path and CLI ownership is split as follows:

```text
engine/server/db/jobs/updater/cli.py      -> argparse flags and default paths
engine/server/db/jobs/updater/paths.py    -> resolved paths and required-file checks
engine/server/db/jobs/updater/pipeline.py -> command ordering and subprocess construction
```

### New/updated path ownership

Add a random cache DB path to `ResolvedUpdaterPaths`:

```text
random_cache_db: Path
```

`cli.py` should resolve the default from `server_config.DEFAULT_RANDOM_CACHE_DB_PATH`, matching Engine runtime.

Add a CLI flag:

```text
--random-cache-db <path>
```

Default:

```text
engine/server/db/random-cache.db
```

This follows the existing pattern for:

```text
--similarity-db
--index-path
--index-meta-path
```

### Random cache command

Add a pipeline command after successful ANN rebuild and before similarity precompute:

```bash
python3 engine/server/db/jobs/precompute-random-index-ids.py \
  --db <prod-db> \
  --out <random-cache-db> \
  --size 500000 \
  --filtered \
  --max-per-author 100 \
  --max-per-instance 0 \
  --reset
```

Use project defaults from `server_config.py` rather than duplicating magic constants when practical:

```text
DEFAULT_RANDOM_CACHE_SIZE
DEFAULT_RANDOM_CACHE_FILTERED_MODE
DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR
DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE
DEFAULT_RANDOM_CACHE_DB_PATH
```

Implementation options:

- Preferred: import these defaults in `cli.py` for the path default, and in `pipeline.py` for command arguments.
- Acceptable: if importing runtime config in `pipeline.py` creates circular/path issues, keep the values explicit but add a comment that they intentionally mirror `server_config.py`. Prefer avoiding duplication if the import is straightforward.

For filtered mode:

- If `DEFAULT_RANDOM_CACHE_FILTERED_MODE` is true, include `--filtered` and both cap flags.
- If false, omit `--filtered` and cap flags.

Use `--reset` so stale rows from a previous cache are removed. This is important because old rowid-based `random-cache.db` files are incompatible with the new `random_index_ids` semantics.

### Similarity command cleanup

Update `precompute_cmd` in `updater/pipeline.py` from the current shape:

```text
--index <index-path> <index-path>
```

to:

```text
--index <index-path>
```

This is no longer a compatibility quirk to preserve. The stable-index migration made artifact identity correctness more important than preserving a malformed command array.

### Required-file validation

Update `required_runtime_files()` in `updater/paths.py` to include:

```text
paths.script_dir / "precompute-random-index-ids.py"
```

Do not require the random cache DB itself to already exist; it is an output artifact.

### Failure behavior

Do not add new failure-injection flags unless tests prove they are needed.

If `precompute-random-index-ids.py` fails after the service has been stopped, the existing `finally` block must still restart the service. This should be covered by existing service-restart behavior patterns.

No fallback to rowid-based random cache is allowed.

## Touched Files

```text
engine/server/db/jobs/updater/cli.py
engine/server/db/jobs/updater/paths.py
engine/server/db/jobs/updater/pipeline.py
tests/jobs/test_updater_cli_characterization.py
tests/jobs/test_updater_pipeline_commands.py
tests/jobs/test_updater_service_restart.py
docs/DATA_BUILD.md
docs/UPDATER_COMPATIBILITY.md
engine/server/db/jobs/docs/UPDATER_WORKER.md
```

## New Files

No new production files are required.

No new plan-specific docs are required unless implementation discovers that existing docs do not have an appropriate ownership boundary for the updater artifact lifecycle.

## Implementation Steps

### 1. Add random cache path to updater CLI and path resolution

In `engine/server/db/jobs/updater/cli.py`:

1. Import `DEFAULT_RANDOM_CACHE_DB_PATH` together with the existing DB path defaults.
2. Resolve:

   ```python
   default_random_cache = (REPO_ROOT / DEFAULT_RANDOM_CACHE_DB_PATH).resolve()
   ```

3. Add:

   ```python
   parser.add_argument(
       "--random-cache-db",
       default=str(default_random_cache),
       help="Path to random index-id cache DB.",
   )
   ```

In `engine/server/db/jobs/updater/paths.py`:

1. Add `random_cache_db: Path` to `ResolvedUpdaterPaths`.
2. In `from_args()`, set:

   ```python
   random_cache_db=Path(args.random_cache_db).resolve()
   ```

3. Add `precompute-random-index-ids.py` to `required_runtime_files()`.

### 2. Add explicit random cache rebuild to the updater pipeline

In `engine/server/db/jobs/updater/pipeline.py`, add a command after ANN rebuild succeeds and before similarity precompute:

```python
random_cache_cmd = [
    args.python_bin,
    (paths.script_dir / "precompute-random-index-ids.py").as_posix(),
    "--db",
    paths.prod_db.as_posix(),
    "--out",
    paths.random_cache_db.as_posix(),
    "--size",
    str(DEFAULT_RANDOM_CACHE_SIZE),
    "--reset",
]
if DEFAULT_RANDOM_CACHE_FILTERED_MODE:
    random_cache_cmd.extend(
        [
            "--filtered",
            "--max-per-author",
            str(DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR),
            "--max-per-instance",
            str(DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE),
        ]
    )
_run_cmd(random_cache_cmd, cwd=paths.repo_root, runner=command_runner)
```

Add a short comment before this block explaining why the cache is rebuilt explicitly:

```text
The Engine can populate random cache at startup, but the updater owns production artifact refresh. Rebuilding here prevents stale rowid-era random artifacts from surviving a data update.
```

Do not use `run_with_cpu_fallback`; the random cache job is SQLite-only.

### 3. Remove duplicate ANN index argument from similarity precompute

In `precompute_cmd`, remove the extra:

```python
paths.index_path.as_posix(),
```

that appears immediately after the `--index <path>` pair.

After the change, the command must contain the ANN path exactly once unless it appears as part of another argument value.

### 4. Update command-sequence tests

In `tests/jobs/test_updater_pipeline_commands.py`:

1. Add `random_cache_db=str(tmp_path / "random-cache.db")` to `_args()`.
2. Update expected command order to include `precompute-random-index-ids.py` between `build-ann-index.py` and `precompute-similar-ann.py`.
3. Replace the old assertion:

   ```python
   assert precompute.count(str(tmp_path / "ann.index")) == 2
   ```

   with:

   ```python
   assert precompute.count(str(tmp_path / "ann.index")) == 1
   ```

4. Add assertions for the random cache command:

   ```python
   random_cmd = next(cmd for cmd in seen if "precompute-random-index-ids.py" in cmd[1])
   assert "--db" in random_cmd
   assert str(tmp_path / "prod.db") in random_cmd
   assert "--out" in random_cmd
   assert str(tmp_path / "random-cache.db") in random_cmd
   assert "--reset" in random_cmd
   assert "--filtered" in random_cmd
   assert "--max-per-author" in random_cmd
   assert "100" in random_cmd
   ```

5. Update CPU-mode tests carefully: the random cache job should not be classified as a GPU/CPU heavy job. The existing heavy-job filter searches for `embeddings`, `build-ann`, and `precompute`; because the random job filename contains `precompute`, the test may accidentally require `--cpu` on a SQLite job. Update the filter to match exact script names:

   ```python
   heavy_scripts = {
       "build-video-embeddings.py",
       "build-ann-index.py",
       "precompute-similar-ann.py",
   }
   heavy = [cmd for cmd in seen if len(cmd) > 1 and Path(cmd[1]).name in heavy_scripts]
   ```

6. Add an assertion that the random cache command does not get `--cpu` or `--gpu`.

### 5. Update CLI characterization tests

In `tests/jobs/test_updater_cli_characterization.py`:

1. Assert that `parse_args([])` has `random_cache_db` ending in:

   ```text
   engine/server/db/random-cache.db
   ```

2. Assert that an explicit override is respected:

   ```python
   args = parse_args(["--random-cache-db", "/tmp/random.db"])
   assert args.random_cache_db == "/tmp/random.db"
   ```

3. If the help-output test snapshots or checks important flags, include `--random-cache-db`.

### 6. Update service restart tests if needed

Review `tests/jobs/test_updater_service_restart.py`.

If tests assert exact command order or assume similarity is the first post-ANN command, update them to include random-cache rebuild between ANN and similarity.

Add or update one regression assertion:

```text
when the random cache job fails after service stop, updater still runs systemctl start
```

This can be done by using the fake command runner to raise when `precompute-random-index-ids.py` is invoked, then asserting `systemctl start` was still recorded.

### 7. Update docs

Update only docs whose purpose covers this behavior.

#### docs/DATA_BUILD.md

The current automatic updater summary says:

```text
crawl to staging -> embeddings -> merge to prod -> popularity -> ANN rebuild -> similarity precompute
```

Change it to include:

```text
index-id sync -> ANN rebuild -> random cache rebuild -> similarity precompute
```

Keep manual command sections aligned with the actual updater order.

#### docs/UPDATER_COMPATIBILITY.md

The existing “Stage order and command arguments remain stable” section says the duplicate ANN index argument is intentionally preserved. That is no longer true after this plan.

Update the decision text to explain that the stable-index migration intentionally changes updater command order/arguments for artifact correctness:

```text
- sync-video-index-ids runs before artifact rebuilds;
- precompute-random-index-ids is now part of the updater artifact refresh;
- precompute-similar-ann receives one --index value;
- old rowid-era random/ANN artifact assumptions are not compatibility behavior.
```

Do not leave documentation claiming the duplicate index argument is preserved.

#### engine/server/db/jobs/docs/UPDATER_WORKER.md

Update:

- Inputs/Outputs: include `random-cache.db`.
- Execution Order: insert `sync-video-index-ids.py` and `precompute-random-index-ids.py`, and remove the duplicate-index quirk if mentioned.
- Important Flags: include `--random-cache-db`.
- Purpose/Main goals: mention stable index-id sync and random cache rebuild.

## Tests

Run focused tests first:

```bash
python3 -m pytest -q \
  tests/jobs/test_updater_cli_characterization.py \
  tests/jobs/test_updater_pipeline_commands.py \
  tests/jobs/test_updater_service_restart.py
```

Run related artifact tests:

```bash
python3 -m pytest -q \
  tests/jobs/test_sync_video_index_ids.py \
  tests/jobs/test_build_ann_index_identity.py \
  tests/jobs/test_random_index_cache.py
```

Run the project Python suite:

```bash
python3 -m pytest -q
```

Run static/compile checks used in this project:

```bash
python3 -m compileall -q client/backend engine/server
bash tests/check-client-engine-boundary.sh
bash tests/check-frontend-client-gateway.sh
python3 engine/server/db/jobs/updater-worker.py --help
```

If Node dependencies are installed, also run:

```bash
cd client/frontend && npm test -- --run
cd ../../engine/crawler && npm run test:db
```

If dependencies are not installed, report that explicitly instead of claiming those tests passed.

## Compatibility / Migration Notes

This plan intentionally changes updater command behavior after the stable ANN/index identity migration.

This is not a public API compatibility break. It is an artifact correctness fix.

No compatibility wrappers with old rowid names should be added.

Old rowid-based random cache artifacts are invalid. The updater should rebuild `random-cache.db` using `random_index_ids`.

Old rowid-based FAISS artifacts are already rejected by FAISS metadata validation and rebuilt by `build-ann-index.py`.

`similarity_cache` schema stays unchanged. The updater only ensures similarity precompute runs after the rebuilt FAISS artifact and after random cache rebuild.

## Regression Risks and Concrete Protections

### Risk: random cache job is skipped in some updater modes

Protection: command-sequence tests must cover normal mode, `--skip-systemctl`, CPU mode, and JoinPeerTube sync mode with new hosts. In all modes that proceed to merge/artifact rebuild, `precompute-random-index-ids.py` must appear after `build-ann-index.py`.

### Risk: no-change sync mode starts rebuilding artifacts unnecessarily

Protection: keep the existing early return when `--sync-join-whitelist` has no new or stale hosts. Tests already assert no commands are run in that case.

### Risk: random cache failure leaves service stopped

Protection: add/update service restart test so a failure in `precompute-random-index-ids.py` still triggers `systemctl start` when stop succeeded.

### Risk: CPU-mode test accidentally treats random cache as a GPU/CPU job

Protection: update tests to classify heavy jobs by exact script name, not substring `precompute`.

### Risk: docs still say duplicate ANN index argument is preserved

Protection: update `docs/UPDATER_COMPATIBILITY.md` and `engine/server/db/jobs/docs/UPDATER_WORKER.md` in the same change.

### Risk: runtime and updater disagree on random cache path

Protection: use `DEFAULT_RANDOM_CACHE_DB_PATH` for the updater default and test the parsed default path.

## Out of Scope

- Discovery API v1.
- Public API identity cleanup.
- Frontend URL/id normalization.
- New index lifecycle database table.
- Hard cleanup of inactive `video_index_ids` rows.
- Changing similarity cache schema to `index_id`.
- Online incremental FAISS update.
- Replacing `updater-worker.py` as the systemd/manual entrypoint.

## Open Questions

None. The implementation should use the existing updater as the owner of this lifecycle and should not create a parallel rebuild pipeline.
