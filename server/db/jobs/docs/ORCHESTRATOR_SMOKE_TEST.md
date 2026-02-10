# Orchestrator Smoke Test

This document describes how to run and interpret
`server/db/jobs/tests/test-orchestrator-smoke.py`.

## Purpose

The smoke test validates the full updater pipeline on a temporary mini-prod DB:

- staging init + seed from prod snapshot,
- crawler steps (`instances`, `channels`, `videos`, `channels-videos-count`),
- embeddings build,
- merge from staging into mini-prod,
- incremental popularity recompute,
- full ANN build,
- incremental similarity precompute.

It also runs failure-injection scenarios by default to verify:

- lock file release,
- DB integrity,
- expected behavior before/after merge boundaries.

## What It Uses

- Source DB: default from `server_config.DEFAULT_DB_PATH`
- Test instances list: `server/db/jobs/tests/test-instances.json`
- Temporary workdir: `tmp/orchestrator-smoke/<run-id>/`
- Local whitelist JSON server (generated inside workdir)

The generated whitelist JSON is JoinPeerTube-like:

```json
{
  "total": 3,
  "data": [
    { "host": "example.org" }
  ]
}
```

Source hosts are taken from `server/db/jobs/tests/test-instances.json`.

## Quick Start

Run with GPU (default mode):

```bash
./venv/bin/python3 server/db/jobs/tests/test-orchestrator-smoke.py --keep-workdir
```

Run CPU-only:

```bash
./venv/bin/python3 server/db/jobs/tests/test-orchestrator-smoke.py --cpu --keep-workdir
```

Run with real systemd stop/start during test:

```bash
./venv/bin/python3 server/db/jobs/tests/test-orchestrator-smoke.py --use-systemctl --keep-workdir
```

## Common Limits (for faster test runs)

```bash
./venv/bin/python3 server/db/jobs/tests/test-orchestrator-smoke.py \
  --keep-workdir \
  --max-instances 3 \
  --max-channels 30 \
  --max-videos-pages 1 \
  --seed-videos-limit 2000 \
  --concurrency 4 \
  --nlist 256
```

## Key Flags

- `--gpu` / `--cpu`
- `--keep-workdir`
- `--skip-failure-checks`
- `--use-systemctl`
- `--max-instances`
- `--max-channels`
- `--max-videos-pages`
- `--seed-videos-limit`
- `--nlist`

Run `--help` for full list:

```bash
./venv/bin/python3 server/db/jobs/tests/test-orchestrator-smoke.py --help
```

## Artifacts

By default, the latest report is always written to:

- `tmp/orchestrator-smoke/last-report.json`

When `--keep-workdir` is set, per-run artifacts remain in:

- `tmp/orchestrator-smoke/<run-id>/report.json`
- `tmp/orchestrator-smoke/<run-id>/smoke.log`
- `tmp/orchestrator-smoke/<run-id>/worker.log`
- `tmp/orchestrator-smoke/<run-id>/whitelist-http.log`
- mini-prod/staging DB and ANN/similarity outputs

## Pass / Fail

PASS means:

- required pipeline markers found in worker log,
- ANN meta total matches DB embeddings count,
- merge-rule invariants hold (`INSERT_ONLY`, `INSERT_OR_REPLACE`),
- no duplicate key groups for merge keys,
- lock file is released,
- SQLite integrity check is `ok`,
- failure scenarios behave as expected (unless skipped).

Failure scenarios included by default:

- `before_merge`
- `during_ann_build`
- `after_merge_before_similarity`

How to read `db_unchanged` in failure scenarios:

- `before_merge`: should stay `true` (no merge happened yet).
- `during_ann_build` and `after_merge_before_similarity`: may be `false` (merge already happened).

FAIL means report contains `status: "fail"` and `error`.

## GPU / CPU Verification

When running `--gpu`, verify logs contain:

- embeddings step with `device=cuda`
- ANN step with `mode=gpu`

When running `--cpu`, verify logs contain:

- embeddings step with `device=cpu`
- ANN step with `mode=cpu`

## Notes

- This test works against a temporary mini-prod DB copy, not real production DB.
- If you use `--use-systemctl`, test can stop/start the configured service.
- Keep `--nlist` safely below the available embedding count in mini DB.
- First files to inspect after run:
  - `tmp/orchestrator-smoke/last-report.json`
  - `tmp/orchestrator-smoke/<run-id>/report.json`
  - `tmp/orchestrator-smoke/<run-id>/smoke.log`
  - `tmp/orchestrator-smoke/<run-id>/worker.log`
