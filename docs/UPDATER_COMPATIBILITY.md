# Updater Compatibility

## Purpose

This document records compatibility decisions preserved by the Stage 9 updater split. It covers operational behavior that must remain stable while `engine/server/db/jobs/updater-worker.py` delegates internals to `engine/server/db/jobs/updater/` modules.

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

### Stage order and command arguments remain stable

Decision: Preserve crawler, embedding, merge, popularity, ANN, and similarity command order and current command arguments, including existing quirks.

Reason: The updater produces production data artifacts; reordering stages or “fixing” arguments during a split can change data-build behavior.

Implementation action: Move orchestration to `updater/pipeline.py` and assert recorded fake-runner command arrays in tests. Preserve the current duplicate ANN index argument in the similarity precompute command as a compatibility quirk rather than silently fixing it.

Tests: `tests/jobs/test_updater_pipeline_commands.py`.

Removal condition, if any: Command argument cleanup requires a separate behavior-change plan with before/after data-build validation.

### Systemd stop/start failure behavior remains stable

Decision: Preserve the current stop-before-merge and start-in-finally behavior.

Reason: If the service is stopped and a later post-stop stage fails, the current operational contract attempts to restart it.

Implementation action: Keep the nested `try/finally` in `updater/pipeline.py` and only run stop/start when `--skip-systemctl` is false.

Tests: `tests/jobs/test_updater_service_restart.py`.

Removal condition, if any: Only a deployment-specific plan may change systemd/service restart behavior.

### Lock behavior remains stable

Decision: Preserve active-lock rejection, stale-lock replacement, and lock cleanup on normal and exceptional exits.

Reason: Overlapping updater runs can corrupt staging/prod artifacts.

Implementation action: Move lock code to `updater/locks.py` with the same exclusive create flags and PID-liveness logic.

Tests: `tests/jobs/test_updater_locks.py`.

Removal condition, if any: None for this refactor series.

### JoinPeerTube sync and purge safety remain stable

Decision: Preserve dry-run behavior, `--yes` requirement for stale purge, host normalization, and purge aggregation.

Reason: Sync mode can delete prod data for hosts no longer in the whitelist, so safety gates must not change during a split.

Implementation action: Move fetch/list/write/purge helpers to `updater/sync.py`; keep `--yes` and dry-run decisions in the pipeline.

Tests: `tests/jobs/test_updater_sync.py` and sync branches in `tests/jobs/test_updater_pipeline_commands.py`.

Removal condition, if any: A future sync behavior plan may change purge policy with explicit destructive-operation tests.

### Staging DB helper behavior remains stable

Decision: Preserve staging recreation, sidecar removal, prod seeding, delta count keys, local non-ok pruning, and test embedding injection.

Reason: Staging DB behavior bridges crawler output and Engine-readable data artifacts.

Implementation action: Move staging helpers to `updater/staging.py` without editing `engine/crawler/schema.sql` or merge rules.

Tests: `tests/jobs/test_updater_staging.py`.

Removal condition, if any: Schema or merge behavior changes belong to separate DB/data-build plans.
