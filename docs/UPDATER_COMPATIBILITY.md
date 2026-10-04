# Updater Compatibility

## Purpose

This document records compatibility decisions preserved by the updater module split. It covers operational behavior that must remain stable while `engine/server/db/jobs/updater-worker.py` delegates internals to `engine/server/db/jobs/updater/` modules.

## Decisions

### `updater-worker.py` remains the executable entrypoint

Decision: Keep `engine/server/db/jobs/updater-worker.py` as the script path used by installers, systemd units, smoke tests, and manual commands.

Reason: Operational callers should not need to know the new package layout.

Implementation action: Replace the script body with a compatibility wrapper that sets the same import path, exposes moved helpers as imported names, parses args, configures logging, and calls `updater.pipeline.run_pipeline`.

Tests: `python3 engine/server/db/jobs/updater-worker.py --help`; `tests/jobs/test_updater_cli_characterization.py`; existing installer smoke remains prerequisite-sensitive.

Removal condition, if any: Only a future deployment plan may replace this path and update installers/systemd/docs together.

### CLI flags and defaults remain stable

Decision: Preserve existing flags, defaults, mutual exclusivity, and service-name fallback behavior.

Reason: Updater invocations may be stored in shell history, systemd units, docs, or operational scripts.

Implementation action: Move parser construction to `updater/cli.py` with an optional test argv parameter. Keep installer fallback service-name resolution and existing default path calculations.

Tests: `tests/jobs/test_updater_cli_characterization.py` and `python3 engine/server/db/jobs/updater-worker.py --help`.

Removal condition, if any: Only a dedicated operational CLI change plan may remove or repurpose a flag.

### Stage order and command arguments remain stable unless artifact correctness requires migration

Decision: Preserve crawler, embedding, merge, popularity, and service-control behavior while keeping derived artifacts consistent with the current canonical DB. Prepared Discovery is now a mandatory post-popularity stage; existing stable-index-id/Search/ANN/random/similarity stages remain after it.

Reason: Runtime tag filters and facets now consume updater-owned `video_tags` and `video_facets_snapshot`. Once canonical video mutation commits, Engine must not be restarted by the updater until that narrow prepared pair is available. Read-index reconciliation is not a per-run updater stage because Engine startup already applies the current read-index bootstrap before serving.

Implementation action: Keep orchestration in `updater/pipeline.py` and assert recorded fake-runner command arrays in tests. After the Engine is stopped, destructive stale-host purge and merge can mutate canonical videos; popularity is recomputed; `rebuild-video-discovery-data.py` rebuilds tags/facets; then the existing stable-id, Search, ANN, random, and similarity stages continue. No `ensure-video-indexes.py` command is added to the normal updater pipeline.

Tests: `tests/jobs/test_updater_pipeline_commands.py`.

Removal condition, if any: Future command argument changes require a dedicated operational behavior plan with before/after data-build validation.

### Systemd stop/start failure behavior and prepared Discovery gate

Decision: Preserve stop-before-canonical-mutation and start-in-finally behavior for later artifact failures, but do not let the updater restart its stopped Engine while prepared Discovery is unavailable.

Reason: The singleton prepared facet snapshot is a durable readiness bit for `video_tags + video_facets_snapshot`. A failed rebuild can outlive one updater process, so a later run must not restart Engine merely because its own in-memory control flow did not perform the earlier mutation.

Implementation action: Keep the nested `try/finally` in `updater/pipeline.py`. When `--skip-systemctl` is false and this run stopped Engine, the final restart first checks the persisted prepared Discovery snapshot. Failure before canonical mutation still restarts when the prior snapshot is valid; a committed mutation followed by failed rebuild leaves the marker absent and Engine stopped. Later Search/ANN/random/similarity failure still restarts after a successful prepared rebuild.

`--skip-systemctl` remains an operator escape hatch. For production mutations it is supported only when an external caller keeps Engine stopped for the complete offline updater section, from before the first canonical mutation until the updater command finishes; running it against a live production Engine is unsupported.

Tests: `tests/jobs/test_updater_service_restart.py`, `tests/jobs/test_updater_cli_characterization.py`.

Removal condition, if any: Broader startup/deployment coordination belongs to a separate publication-lifecycle plan.

### Lock behavior remains stable

Decision: Preserve active-lock rejection, stale-lock replacement, and lock cleanup on normal and exceptional exits.

Reason: Overlapping updater runs can corrupt staging/prod artifacts.

Implementation action: Move lock code to `updater/locks.py` with the same exclusive create flags and PID-liveness logic.

Tests: `tests/jobs/test_updater_locks.py`.

Removal condition, if any: None for this refactor series.

### JoinPeerTube sync and purge safety remain stable

Decision: Preserve dry-run behavior, `--yes` requirement for stale purge, host normalization, and purge aggregation. The destructive production purge executes only after the existing Engine stop boundary.

Reason: Sync mode can delete prod videos for hosts no longer in the whitelist. With prepared tags/facets, deleting those rows while Engine is serving would immediately make prepared Discovery stale.

Implementation action: Keep planning/approval before crawl, but defer `purge_hosts(..., dry_run=False)` until the post-stop section of `updater/pipeline.py`. The low-level purge invalidates prepared Discovery in the same transaction only when video rows are actually deleted.

Tests: `tests/jobs/test_updater_sync.py` and sync branches in `tests/jobs/test_updater_pipeline_commands.py`.

Removal condition, if any: A future sync behavior plan may change purge policy with explicit destructive-operation tests.

### Staging DB helper behavior remains stable

Decision: Preserve staging recreation, sidecar removal, prod seeding, delta count keys, local non-ok pruning, and test embedding injection.

Reason: Staging DB behavior bridges crawler output and Engine-readable data artifacts.

Implementation action: Move staging helpers to `updater/staging.py` without editing `engine/crawler/schema.sql` or merge rules.

Tests: `tests/jobs/test_updater_staging.py`.

Removal condition, if any: Schema or merge behavior changes belong to separate DB/data-build plans.


### Current-schema and staging embedding barriers

Before JoinPeerTube fetches, stale-host planning/purge, staging initialization, or crawler commands, the updater validates under `single_run_lock` that production contains all crawler-owned current-shape columns and expected keys. Production-only columns remain valid. A stale destination fails with an instruction to run `migrate-whitelist.py`.

`merge-staging-db.py` is the generic correctness boundary for every caller: all merge rules are validated before DML, keys must exist on both sides, and `stage_columns - prod_columns` must be empty. Production-only columns are allowed. This prevents a newer staging schema from being silently truncated by an older destination.

Staging embeddings are disposable. Every normal path that can reach production merge, including `--resume-staging`, runs `build-video-embeddings.py --force` immediately before delta calculation/merge. Existing staging vectors are never treated as proof of the current embedding recipe. `--retry-errors` remains a staging-repair-only run and exits before embeddings/merge; the subsequent normal resume performs the forced rebuild. A failed forced rebuild aborts before merge.

## Random cache publication ownership

Decision: updater/data-build is the only production writer of `random-cache.db`. The updater stops Engine before `precompute-random-index-ids.py --refresh`, publishes a validated sibling temporary artifact with atomic replace, and restarts Engine in the existing `finally` path even if the rebuild fails. `--reset` is not a compatibility alias and is intentionally removed.

Standalone rebuilds may target another output path while Engine runs, but replacement of the configured production runtime path is an offline operation and requires Engine restart before the new generation is authoritative to runtime. No hot-reload watcher is part of this contract.

### video-availability semantics cutover staging semantic cutover

Fresh `init_staging_db()` recreates DB/sidecars and stamps existing `crawl_state`
with `video_availability_semantics=canonical_absence_v1`. Legacy staging is unsupported and
never converted/backfilled. Resume (including retry-errors) requires that exact
marker immediately after production schema preflight, before denylist, network,
crawler, merge or service-stop work. Correctly marked same-era crash/resume
keeps its current behavior.

Direct `merge-staging-db.py` revalidates the same marker through the already
attached `stage` connection inside `BEGIN IMMEDIATE`, before first production
DML. It never reopens the pathname to authorize rows: replacing that path cannot
make marked B authorize attached legacy A, or revoke attached marked A. Missing
or mismatched evidence fails with a recreate-staging instruction and rollback.

During rollout, delete legacy staging and sidecars without pre-creating its
replacement. Restart Engine after offline in-place migration/Prepared v2/Search
cutover, then invoke the first ordinary updater without resume/retry-errors; it
creates staging and owns ordinary systemctl behavior. An intentionally offline
outer rollout uses `--skip-systemctl` instead, retaining sole restart ownership.
See `DATA_BUILD.md` for full-sync isolation and broader publication readiness.
This temporary stamp/check can be removed only after every supported deployment
crosses the cutover and legacy staging can no longer be resumed.
