# Moderation Integration Test

This document describes how to run and interpret
`engine/server/db/jobs/tests/test-moderation-integration.py`.

## Purpose

The test validates moderation/ingest invariants end-to-end on fixture DBs:

- host denylist behavior,
- host purge behavior,
- channel blocklist behavior,
- strict host reconciliation logic,
- serving-time moderation filtering.

It supports two fixture modes:

- synthetic seed (default),
- sampled real rows copied from production DB (`--sample-from-prod`).

The test does not use network calls.

## Important Scope

All write operations happen only in temporary SQLite files:

- `tmp/moderation-integration/moderation-main.db`
- `tmp/moderation-integration/moderation-similarity.db`

In `--sample-from-prod` mode, production DB is opened read-only and used only as a source
for sampling hosts/channels/videos/embeddings copied into temp DBs.

## Quick Start

Run:

```bash
python3 engine/server/db/jobs/tests/test-moderation-integration.py
```

Run with sampled production data:

```bash
python3 engine/server/db/jobs/tests/test-moderation-integration.py --sample-from-prod
```

Explicit source DB:

```bash
python3 engine/server/db/jobs/tests/test-moderation-integration.py --sample-from-prod --source-db engine/server/db/whitelist.db
```

Run with a specific host as block/purge target:

```bash
python3 engine/server/db/jobs/tests/test-moderation-integration.py --sample-from-prod --target-host bad.instance.tld
```

Keep fixture files for inspection:

```bash
python3 engine/server/db/jobs/tests/test-moderation-integration.py --keep-workdir
```

## What the Test Does

1. Seed fixtures into temporary DBs:
   - synthetic mode: fixed hosts (`allowed.example`, `deny.example`, `ignored.example`, `stale.example`)
   - prod-sample mode: sampled real hosts/channels/videos/embeddings from source DB
   - when `--target-host` is passed, that host is forced into the `deny` role and becomes
     the block/purge target in the test flow
   - denylist host rows
   - blocked channel row
   - similarity sources/items
2. Purge `ignored` role host from main DB + similarity DB and verify non-zero deletion counts.
3. Emulate strict sync reconciliation:
   - `join_hosts - denied_hosts => effective_hosts`
   - `current_hosts - effective_hosts => stale_hosts`
   - purge each stale host from main DB + similarity DB
4. Validate serving moderation using the same helper as server response path:
   - `data.serving_moderation.apply_serving_moderation_filters(...)`
   - expect denylisted host rows and blocked-channel rows to be filtered out
5. Validate final DB invariants:
   - removed hosts no longer exist in `videos`/`instances`
   - no dangling similarity rows for removed hosts
6. Replay purge for idempotency and verify replay deletion counts are zero.

## How to Read Logs

The script logs by stages:

- `INFO [seed] ...`
  - fixture creation and DB paths.
- `INFO [seed][main] ...`
  - seeded row counts in main DB (`instances/channels/videos/...`).
- `INFO [seed][similarity] ...`
  - seeded row counts in similarity DB.
- `INFO [seed][prod-sample] ...`
  - selected sampled hosts and role mapping (`allowed/deny/ignored/stale`)
  - per-host sampled counts (`channels/videos/embeddings`)
- `INFO [test][step1] ...`
  - purge of ignored host + per-table delete counters.
- `INFO [test][step2] ...`
  - host set math (`join_hosts`, `denied_hosts`, `effective_hosts`, `stale_hosts`)
  - stale host purge counters.
- `INFO [test][step3] ...`
  - serving filter input/output counts and kept IDs.
  - includes moderation counters:
    - `filtered_by_denylist`
    - `filtered_by_blocked_channel`
- `INFO [test][step4] ...`
  - dangling similarity check (`dangling_similarity=0` expected).
- `INFO [test][step5] ...`
  - idempotency replay purge counters (all zeros expected).
- `Moderation integration test: PASS`
  - all assertions passed.

## Notes

- The test validates serving moderation logic through the shared serving helper used by recommendation routes.
- It does not perform real HTTP requests; it verifies the same filtering contract in-process.
