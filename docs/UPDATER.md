# Updater

Purpose: document the complete operation and behavior of the production data updater.

The executable entrypoint is `engine/server/db/jobs/updater-worker.py`.

## Responsibility

Updater collects new PeerTube data into staging, merges the accepted delta into the canonical database while Engine is offline, rebuilds the derived artifacts, and returns Engine to service only when required prepared data is ready.

## Inputs and Outputs

| Role | Default path |
|---|---|
| Production database | `engine/server/db/whitelist.db` |
| Staging database | `engine/server/db/staging-worker.db` |
| Merge rules | `engine/server/db/jobs/merge_rules.json` |
| FAISS index | `engine/server/db/whitelist-video-embeddings.faiss` |
| FAISS metadata | `engine/server/db/whitelist-video-embeddings.faiss.json` |
| Random cache | `engine/server/db/random-cache.db` |
| Similarity cache | `engine/server/db/similarity-cache.db` |
| Log file | `engine/server/db/updater-worker.log` |
| Single-run lock | `/tmp/peertube-browser-staging-sync.lock` |

Updater validates that writable roles and their SQLite sidecars do not alias each other before logging, locking, network access, or mutation.

## Prerequisites

1. Install Python runtime dependencies.
2. Install crawler dependencies and build the generated JavaScript used by Updater:

```bash
cd engine/crawler
npm install
npm run build
cd ../..
```

3. Ensure the production database uses the current schema. If the schema check fails:

```bash
./venv/bin/python3 engine/server/db/jobs/migrate-whitelist.py \
  --db engine/server/db/whitelist.db
```

Do not run external crawler or database writers against production or Updater staging during a run. The Updater lock prevents overlapping Updater processes; it is not a repository-wide writer lock.

## Normal Run

From the repository root:

```bash
./venv/bin/python3 engine/server/db/jobs/updater-worker.py \
  --gpu
```

`--gpu` runs embedding and FAISS stages on GPU and retries a failed GPU stage in CPU mode. Use `--cpu` to run both stages on CPU only.

## Pipeline

Updater executes these stages in order:

1. Validate output-path ownership and acquire the single-run lock.
2. Recreate staging, or validate and reuse it with `--resume-staging`.
3. Seed staging with production instances and channels for a new run.
4. Discover instances.
5. Freeze the exact selected host set after discovery, including a distinct empty scope.
6. Reset selected parent health and channel progress to page zero; stamp current provenance.
7. Probe each selected instance, enumerate its channels from page zero, and verify unresolved channel health. Do not advance incomplete or truncated lists.
8. Admit counts and new-video ingest only for freshly healthy parents with confirmed `done`.
9. Optionally sweep existing production video identities already admitted by the same parent gate; query video detail directly without a second channel-list preflight.
10. Force-build staging embeddings, stop Engine unless `--skip-systemctl` is set, apply an authorized strict purge, and merge staging. Parent health publishes only from the frozen scope (`INSERT NULL` then JSON1-scoped `UPDATE`) in one transaction.
11. Recompute popularity and rebuild prepared tags/facets, video identity indices, Search, FAISS, Random and similarity artifacts.
12. Start Engine only when prepared Discovery is ready; release the lock.

The default crawler stages are fresh instance health, channel lists/health, missing counts and new video metadata. `--host-pipeline` owns its own reset and probe; all admitted hosts enter its concurrent scheduler at `channels`, then progress to `counts` and `videos` only after persisted `done` and healthy-parent checks. `--max-channels` is a global insertion budget for ordinary channels CLI, but a per-host budget under host-pipeline.

## Staging and Resume

Without `--resume-staging`, Updater recreates staging and its SQLite sidecars. New staging is stamped with:

```text
video_availability_semantics = canonical_absence_atomic_ingest_v2
video_corpus_role            = updater_staging_delta
```

Resume, error retry, and merge require this exact generation and role. Legacy, roleless, or malformed staging is rejected rather than converted.

Resume an interrupted current-generation crawl:

```bash
./venv/bin/python3 engine/server/db/jobs/updater-worker.py \
  --resume-staging \
  --gpu
```

Resume behavior is status-aware:

- channel enumeration resets to page zero for every newly selected normal/resumed run; stale `done`/offsets cannot authorize children;
- persisted channel video counts are skipped;
- video pagination continues from `video_crawl_progress.last_start`;
- normal resume processes `pending` and `in_progress` rows;
- normal resume does not repeatedly retry recorded `error` rows;
- embeddings are always rebuilt with `--force` before a resumed merge.

## Retry Recorded Crawler Errors

Retry only errors already stored in current staging:

```bash
./venv/bin/python3 engine/server/db/jobs/updater-worker.py \
  --resume-staging \
  --retry-errors \
  --host-concurrency 1 \
  --timeout-ms 15000
```

This mode retries failed count/video rows only; it does not re-probe instances, re-enumerate channel lists, merge, rebuild derived data or publish availability. Per-host provenance is validated only for hosts with actual repair work. A repair candidate without current page-zero provenance fails before network access; a historical host with no repair work does not block retry. Run a normal `--resume-staging` to rebuild parent observations and complete publication.

## Limit a Run to Selected Hosts

Create a UTF-8 file with one host per line, then run:

```bash
./venv/bin/python3 engine/server/db/jobs/updater-worker.py \
  --hosts-file /path/to/hosts.txt
```

The normalized operator scope is frozen once; every later crawler/merge subprocess receives the frozen snapshot. Blank, missing, unreadable, empty or comment-only **operator** files fail before work begins. A legitimately empty computed scope skips network work; it does not select every host.

`--max-instances`, `--max-channels`, and `--max-videos-pages` are test caps. They are not a replacement for an explicit host scope in production work.

## Strict JoinPeerTube Synchronization

Preview hosts that would be added or purged:

```bash
./venv/bin/python3 engine/server/db/jobs/updater-worker.py \
  --sync-join-whitelist \
  --dry-run
```

Apply the approved plan:

```bash
./venv/bin/python3 engine/server/db/jobs/updater-worker.py \
  --sync-join-whitelist \
  --yes
```

Destructive host purge occurs only after Engine has stopped. `--yes` is required for the destructive operation.

## Existing-Video Availability

Availability modes inspect production video identities only after fresh parent-health, complete channel-enumeration and provenance gates. They make video-detail requests without a second host-level channel preflight. `--retry-errors` remains incompatible; strict-sync and host-pipeline are permitted with their separate parent scopes, and strict-sync dry-run remains a preview without a sweep.

Start with a small report scope:

```bash
./venv/bin/python3 engine/server/db/jobs/updater-worker.py \
  --check-existing-video-availability \
  --hosts-file /path/to/hosts-small.txt
```

The sweep records disposable per-video detail evidence (each terminal row has an attempted-detail timestamp) and emits one `video_availability_report` JSON log entry containing selected, available, absent, unknown, missing-UUID, processed-host and attempted-request counts. Old `host_preflight` evidence is rejected. Report mode does not publish availability changes, but the surrounding ordinary update pipeline still proceeds.

Publish observations explicitly:

```bash
./venv/bin/python3 engine/server/db/jobs/updater-worker.py \
  --apply-existing-video-availability \
  --hosts-file /path/to/hosts-small.txt
```

Apply mode publishes staging merge and completed availability evidence in a single SQLite transaction while Engine is offline, then rebuilds every dependent artifact. Only complete current-run observations with exact identity can change canonical `invalid_reason` and `invalid_at`. Unknown results, denied hosts and missing identities do not overwrite canonical state. A definitive AVAILABLE clears any legacy video-availability invalidity; moderation denylist remains separate. A stale or contradictory observation aborts the publication transaction.

Availability work is reset for every accepted invocation, including resumed runs. Old observations are never replayed.

## Engine Stop and Restart

By default, Updater stops the configured Engine service before the first canonical mutation.

- Failure before canonical mutation allows restart when the existing prepared snapshot is valid.
- Failure while required prepared Discovery is unavailable leaves an Engine service stopped by Updater offline.
- Failure in later FAISS, Random, or similarity stages restarts Engine after prepared Discovery has succeeded.
- Random publication builds and validates a sibling temporary database, then replaces the production artifact atomically. Engine does not hot-reload it.

`--skip-systemctl` transfers the entire Engine lifecycle to the caller:

```bash
systemctl stop peertube-engine
./venv/bin/python3 engine/server/db/jobs/updater-worker.py --skip-systemctl --cpu
systemctl start peertube-engine
```

When `--skip-systemctl` can mutate production, keep Engine and every external production writer stopped from before the first mutation until Updater finishes successfully. Do not start Engine if prepared Discovery is unavailable.

## Lock Behavior

Only one Updater invocation may run at a time.

- A process holding the nonblocking POSIX file lock causes a clear failure; PID text is diagnostic only.
- An unlocked stale file is reused. The locked inode is checked against the path before work begins.
- Normal and exceptional exits release the lock.

Do not remove an active lock to force a second run.

## Network Controls

Important crawler controls are:

```text
--concurrency          number of concurrently active hosts
--host-concurrency     maximum simultaneous requests to one host
--host-delay-ms        minimum delay between request starts for one host
--timeout-ms           request timeout
--max-retries          bounded retry count
--whitelist-url        instance registry source
--hosts-file           explicit host scope
--host-pipeline        enable host-stage scheduling
```

Use the CLI as the complete flag reference:

```bash
./venv/bin/python3 engine/server/db/jobs/updater-worker.py --help
```

## systemd Timer

The production installer enables `peertube-updater.service` and `peertube-updater.timer`:

```bash
sudo bash install-service.sh --mode prod --with-updater-timer
```

Current defaults are:

```text
OnCalendar=Fri *-*-* 20:00:00
Persistent=false
RandomizedDelaySec=0
AccuracySec=1m
```

The installed service runs the configured Engine service name with `--systemctl-use-sudo`. The scoped sudoers rule permits only the required Engine `stop` and `start` commands.

Override the schedule or worker flags during installation:

```bash
sudo bash install-service.sh \
  --mode prod \
  --with-updater-timer \
  --updater-oncalendar 'Sat *-*-* 03:00:00' \
  --updater-flags '--gpu --concurrency 5 --timeout-ms 15000 --max-retries 3'
```

## Observe a Run

```bash
systemctl status peertube-updater.service -l
journalctl -u peertube-updater.service -f -o cat
systemctl list-timers --all peertube-updater.timer
```

The file log defaults to `engine/server/db/updater-worker.log`.

Inspect current data counts:

```bash
sqlite3 engine/server/db/whitelist.db "select count(*) from videos;"
sqlite3 engine/server/db/whitelist.db "select count(*) from video_embeddings;"
sqlite3 engine/server/db/whitelist.db "select snapshot_id, schema_version from video_facets_snapshot where snapshot_id=1;"
sqlite3 engine/server/db/random-cache.db "select count(*) from random_index_ids;"
sqlite3 engine/server/db/similarity-cache.db "select count(*) from similarity_sources;"
```

## Failure Recovery

| Last completed boundary | Production state | Required action |
|---|---|---|
| Before Engine stop | Unchanged | Fix the crawler or staging error; use current-generation resume when appropriate. |
| Engine stopped, before merge | Unchanged | Fix the failure and rerun; confirm Engine restart state. |
| Canonical mutation committed, prepared rebuild failed | Updated but not ready | Keep Engine offline and rerun the required rebuild or restore a consistent backup. |
| Prepared Discovery succeeded, later artifact failed | Canonical data is ready; one derived artifact is stale or absent | Rebuild the failed artifact before relying on its provider. Engine may have restarted. |
| Combined merge/availability publication failed before commit | Canonical merge, parent health, availability and readiness changes all rolled back | Fix the evidence or input error and collect a new run. |
| Availability publication committed, later rebuild failed | Canonical availability updated; derived data incomplete | Keep Engine offline until all required rebuilds succeed or restore a consistent generation. |

Do not reuse staging from an incompatible writer generation. Do not treat a successful availability report as a successful publication. Derived artifacts are rebuildable and are not rollback authority; rollback requires a consistent canonical database and matching application version.

## Verification

Run deterministic Updater and job tests:

```bash
make test-jobs
```

Run the full operational smoke only in an environment with the required crawler build, data, FAISS dependencies, and optional systemd access:

```bash
./venv/bin/python3 engine/server/db/jobs/tests/test-orchestrator-smoke.py --cpu --keep-workdir
```

Run moderation integration against temporary fixture databases:

```bash
./venv/bin/python3 engine/server/db/jobs/tests/test-moderation-integration.py
```
