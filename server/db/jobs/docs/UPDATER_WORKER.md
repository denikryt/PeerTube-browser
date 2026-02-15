# Updater Worker

This document describes how `server/db/jobs/updater-worker.py` works.

## Purpose

`updater-worker.py` is a background pipeline that refreshes the production dataset.
It uses a staging database, merges changes into prod, then rebuilds derived artifacts.

Main goals:
- fetch new instances/channels/videos,
- compute embeddings for new content,
- merge staging into prod with merge rules,
- refresh popularity/similarity data,
- rebuild ANN index for prod.

## Inputs and Outputs

Inputs:
- Prod DB: `server/db/whitelist.db` (default)
- Merge rules: `server/db/jobs/merge_rules.json`
- Crawler CLIs from `crawler/dist/*.js`
- Python jobs in `server/db/jobs/*.py`

Outputs:
- Updated prod DB (`whitelist.db`)
- Rebuilt FAISS index (`whitelist-video-embeddings.faiss` + `.json`)
- Updated similarity cache (`similarity-cache.db`)

Temporary output:
- Staging DB (`server/db/staging-worker.db`, recreated each run)

## Execution Order

The worker runs this sequence:

1. Acquire single-run lock (`/tmp/peertube-browser-staging-sync.lock` by default).
2. Prepare staging DB:
   - default: recreate staging DB from crawler schema (`schema.sql`);
   - with `--resume-staging`: reuse existing staging DB and progress state.
3. Seed staging from prod (`instances` + `channels`) unless `--resume-staging` is used.
4. Run crawler steps into staging:
   - `instances-cli`
   - optional local health filter (`--skip-local-dead`)
   - `channels-cli --new-channels`
   - `videos-cli --new-videos --existing-db <prod> --sort -publishedAt`
   - `channels-videos-count-cli`
5. Build embeddings in staging (`build-video-embeddings.py`).
6. Optionally stop API service (unless `--skip-systemctl`).
7. Merge staging into prod (`merge-staging-db.py` with `merge_rules.json`).
8. Recompute popularity incrementally (`recompute-popularity.py --incremental`).
9. Rebuild ANN index from prod (`build-ann-index.py`).
10. Update similarity cache incrementally (`precompute-similar-ann.py --incremental`).
11. Start API service back.
12. Release lock and finish.

## What Exactly Is Collected

- Instances: from whitelist source (JoinPeerTube URL by default).
- Channels:
  - crawler requests channel pages from each instance API;
  - with `--new-channels`, only channels absent in DB are inserted/kept as new rows.
- Videos: new videos only (`--new-videos`) using prod DB as reference.
- Channel video counts: refreshed in staging for crawled channels.
- Embeddings: computed for new/required rows in staging.

After merge, prod contains merged changes according to `merge_rules.json`.

## Lock Behavior

- Only one worker run is allowed at a time.
- If lock file exists and PID is alive, worker exits with a clear "another run is active" error.
- If lock file exists but PID is stale, worker removes stale lock and continues.

## Resume Staging Behavior

- `--resume-staging` keeps current staging DB and crawler progress tables.
- This allows continuing from the latest saved crawler position instead of starting a fresh staging cycle.
- Without `--resume-staging`, staging DB is recreated each run.

## Service Stop/Start Behavior

Default behavior:
- worker stops `peertube-browser` before merge and starts it after post-merge jobs.
- systemd install uses `--systemctl-use-sudo` so stop/start runs as `sudo -n systemctl ...`
  without interactive auth prompts.

Alternative:
- `--skip-systemctl` disables stop/start control (for manual orchestration).

## GPU/CPU Mode

Acceleration mode is explicit:
- `--gpu`: embeddings + FAISS build run in GPU mode (no CPU fallback).
- `--cpu`: embeddings + FAISS build run in CPU mode.

Default is `--gpu` unless overridden.

## Important Flags

- `--prod-db`, `--staging-db` paths
- `--index-path`, `--index-meta-path`
- `--similarity-db`
- `--merge-rules`
- `--service-name`
- `--systemctl-bin`
- `--systemctl-use-sudo`
- `--skip-systemctl`
- `--skip-local-dead`
- `--resume-staging`
- `--whitelist-url`
- `--concurrency`, `--timeout-ms`, `--max-retries`
- `--max-instances`, `--max-channels`, `--max-videos-pages` (test caps)
- `--videos-stop-after-full-pages`
- `--nlist` (FAISS build)

Test-only failure/injection flags:
- `--inject-replace-embedding-for-test`
- `--fail-before-merge`
- `--fail-during-ann-build`
- `--fail-after-merge-before-similarity`

## Manual Run

From repo root:

```bash
./venv/bin/python3 server/db/jobs/updater-worker.py --gpu --skip-local-dead
```

## Systemd Run

`install-service.sh --with-updater-timer` installs:
- `peertube-updater.service` (oneshot worker)
- `peertube-updater.timer` (daily schedule)
- `/etc/sudoers.d/peertube-updater-systemctl` scoped rule allowing updater user to run
  `/usr/bin/systemctl stop/start peertube-browser` via `sudo -n`.

Current timer behavior:
- `OnBootSec=10m`
- `OnUnitInactiveSec=1d`
- `Persistent=true`

Updater flags for systemd are configured in `install-service.sh` via:

- `UPDATER_FLAGS="..."`

You can set mode and crawler/network options there, for example:

- `--gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3`

Installer force reinstall:

- `install-service.sh --force` fully reinstalls unit files (stop/disable/remove/recreate/reload/reset-failed).
- It affects systemd units only; it does not delete prod/staging DB files.

## Logs

Worker logs:
- stdout/stderr from systemd journal
- file log path from `--logs` (default `server/db/updater-worker.log`)

Useful commands:

```bash
systemctl status peertube-updater.service -l
journalctl -u peertube-updater.service -f -o cat
systemctl list-timers --all peertube-updater.timer
```
