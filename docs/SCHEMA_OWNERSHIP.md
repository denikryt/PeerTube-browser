# SQLite Schema Ownership

## Purpose

This document defines which component owns each SQLite schema used by PeerTube Browser, which helper or migration creates the current shape, and which compatibility wrappers remain during refactoring.

Stage 6 does not introduce a historical migration framework or change production database shapes. It documents ownership, adds current-shape SQL resources, and keeps existing runtime helpers as compatibility wrappers.

## Client users DB

Owner:

```text
Client backend
```

Current source:

```text
client/backend/lib/users_store.py::ensure_user_schema
```

Stage 6 migration source:

```text
client/backend/db/migrations/0001_users_and_likes.sql
client/backend/db/migrate.py::apply_client_user_migrations
```

Runtime/job callers:

```text
client/backend/server.py
client/backend/repositories/users.py::UsersRepository.ensure_schema
client/backend/lib/users_store.py::ensure_user_schema
```

Tables/indexes:

```text
users
likes
likes_user_updated_idx
```

Compatibility wrappers:

```text
client/backend/lib/users_store.py::ensure_user_schema
client/backend/repositories/users.py::UsersRepository.ensure_schema
```

Allowed Stage 6 changes:

```text
Move the exact current users/likes SQL into checked-in migration resources and keep existing helper names.
```

Deferred changes:

```text
Browser profile behavior, route behavior, user identity semantics, and explicit historical migration state.
```

Tests:

```text
tests/db/test_client_user_migrations.py
tests/db/test_existing_ensure_wrappers_match_migrations.py
tests/repositories/test_client_users_store.py
```

## Crawler raw crawl DB

Owner:

```text
engine/crawler
```

Current source:

```text
engine/crawler/schema.sql
```

Runtime/job callers:

```text
engine/crawler/src/db.ts
engine/crawler/src/*.ts
engine/server/db/jobs/sync-whitelist.py
```

Tables/indexes:

```text
instances
channels
videos
instance_crawl_progress
channel_crawl_progress
video_crawl_progress
```

Compatibility wrappers:

```text
None changed by Stage 6.
```

Allowed Stage 6 changes:

```text
Document ownership and keep compatibility tests around the schema consumed by Engine read paths.
```

Deferred changes:

```text
engine/crawler/src/db.ts split, TypeScript repository tests, crawler schema redesign, and crawler command behavior.
```

Tests:

```text
tests/engine_data/test_schema_compatibility_snapshot.py
```

## Engine main dataset DB

Owner:

```text
Engine data-build/jobs and Engine API runtime readers
```

Current source:

```text
engine/server/db/jobs/sync-whitelist.py::ensure_content_schema
engine/server/db/jobs/whitelist_migrations.py
engine/server/db/jobs/build-video-embeddings.py
engine/server/db/jobs/recompute-popularity.py
```

Runtime/job callers:

```text
engine/server/api/server.py
engine/server/data/*.py
engine/server/db/jobs/*.py
```

Tables/indexes:

```text
videos
channels
instances
video_embeddings
popularity-related columns and read indexes
```

Compatibility wrappers:

```text
engine/server/data/channels.py::ensure_channels_indexes
engine/server/data/videos.py::ensure_video_indexes
engine/server/db/jobs/migrate-whitelist.py
engine/server/db/jobs/whitelist_migrations.py
```

Allowed Stage 6 changes:

```text
Centralize current runtime read-index SQL resources and keep conditional table-existence behavior.
```

Deferred changes:

```text
Changing whitelist schema, changing data-build outputs, adding schema_migrations, updater orchestration, and historical migration policy.
```

Tests:

```text
tests/db/test_engine_runtime_migrations.py
tests/db/test_existing_ensure_wrappers_match_migrations.py
```

## Engine runtime tables and indexes

Owner:

```text
Engine API runtime/data layer
```

Current source:

```text
engine/server/data/interaction_events.py::ensure_interaction_event_schema
engine/server/data/moderation.py::ensure_moderation_schema
engine/server/data/channels.py::ensure_channels_indexes
engine/server/data/videos.py::ensure_video_indexes
```

Stage 6 migration source:

```text
engine/server/db/migrations/main/0001_interaction_events.sql
engine/server/db/migrations/main/0002_moderation.sql
engine/server/db/migrations/main/0003_read_indexes.sql
engine/server/db/migrations/apply.py
```

Runtime/job callers:

```text
engine/server/api/server.py
engine/server/api/routes/internal_events.py
engine/server/data/*.py
engine/server/db/jobs/tests/test-interaction-events.py
```

Tables/indexes:

```text
interaction_raw_events
interaction_raw_events_video_idx
interaction_signals
instance_denylist
idx_instance_denylist_active
channel_moderation
idx_channel_moderation_status_instance
idx_channels_followers_videos_name
idx_channels_videos
idx_channels_name
idx_channels_instance
idx_videos_uuid_instance
idx_videos_id_instance
idx_video_embeddings_id_instance
```

Compatibility wrappers:

```text
engine/server/data/interaction_events.py::ensure_interaction_event_schema
engine/server/data/moderation.py::ensure_moderation_schema
engine/server/data/channels.py::ensure_channels_indexes
engine/server/data/videos.py::ensure_video_indexes
```

Allowed Stage 6 changes:

```text
Move current table/index SQL into migration resources and keep wrappers import-compatible.
```

Deferred changes:

```text
Changing ingest behavior, moderation semantics, route contracts, startup ownership, or schema lifecycle policy.
```

Tests:

```text
tests/db/test_engine_runtime_migrations.py
tests/db/test_existing_ensure_wrappers_match_migrations.py
tests/repositories/test_engine_interaction_events.py
engine/server/db/jobs/tests/test-interaction-events.py
```

## Engine similarity cache DB

Owner:

```text
Engine similarity precompute/runtime
```

Current source:

```text
engine/server/data/similarity_cache.py::ensure_similarity_schema
engine/server/db/jobs/precompute-similar-ann.py::ensure_schema
```

Stage 6 migration source:

```text
engine/server/db/migrations/similarity_cache/0001_similarity_cache.sql
engine/server/db/migrations/apply.py::apply_similarity_cache_migrations
```

Runtime/job callers:

```text
engine/server/api/server.py
engine/server/data/similarity_cache.py
engine/server/db/jobs/precompute-similar-ann.py
```

Tables/indexes:

```text
similarity_sources
similarity_items
similarity_source_rank_idx
```

Compatibility wrappers:

```text
engine/server/data/similarity_cache.py::ensure_similarity_schema
```

Allowed Stage 6 changes:

```text
Centralize current table/index SQL for runtime callers. Keep precompute job behavior unchanged.
```

Deferred changes:

```text
Similarity cache rebuild strategy, ANN behavior, precompute job split, and historical migration state.
```

Tests:

```text
tests/db/test_cache_migrations.py
tests/db/test_existing_ensure_wrappers_match_migrations.py
```

## Engine random cache DB

Owner:

```text
Engine random-cache job/runtime
```

Current source:

```text
engine/server/data/random_cache.py::ensure_random_cache_schema
```

Stage 6 migration source:

```text
engine/server/db/migrations/random_cache/0001_random_cache.sql
engine/server/db/migrations/apply.py::apply_random_cache_migrations
```

Runtime/job callers:

```text
engine/server/api/server.py
engine/server/data/random_cache.py
engine/server/db/jobs/precompute-random-rowids.py
```

Tables/indexes:

```text
random_rowids
```

Compatibility wrappers:

```text
engine/server/data/random_cache.py::ensure_random_cache_schema
```

Allowed Stage 6 changes:

```text
Centralize current table SQL and keep runtime population behavior unchanged.
```

Deferred changes:

```text
Random-cache population policy, cache refresh behavior, and job orchestration.
```

Tests:

```text
tests/db/test_cache_migrations.py
tests/db/test_existing_ensure_wrappers_match_migrations.py
```

## Engine derived artifacts

Owner:

```text
Engine jobs
```

Current source:

```text
engine/server/db/jobs/build-video-embeddings.py
engine/server/db/jobs/build-ann-index.py
engine/server/db/jobs/precompute-similar-ann.py
engine/server/db/jobs/precompute-random-rowids.py
engine/server/db/jobs/recompute-popularity.py
```

Runtime/job callers:

```text
engine/server/api/server.py
engine/server/data/ann.py
engine/server/data/embeddings.py
engine/server/data/random_cache.py
engine/server/data/similarity_cache.py
```

Tables/indexes/artifacts:

```text
video_embeddings
videos.popularity
whitelist-video-embeddings.faiss
whitelist-video-embeddings.faiss.json
similarity-cache.db
random-cache.db
```

Compatibility wrappers:

```text
Existing job entrypoints and helper functions remain unchanged in Stage 6.
```

Allowed Stage 6 changes:

```text
Document ownership and test schema boundaries that runtime code consumes.
```

Deferred changes:

```text
Updater/job orchestration split, derived artifact rebuild policy, and deployment migration commands.
```

Tests:

```text
tests/engine_data/test_schema_compatibility_snapshot.py
tests/db/test_cache_migrations.py
```

## Compatibility wrappers

### Client users schema

Decision: keep client/backend/lib/users_store.py::ensure_user_schema

Reason: existing Client startup and repository code call this helper.

Implementation action: make it delegate to apply_client_user_migrations(conn).

Tests: test_client_user_migrations.py

Removal condition: only after all callers use an explicit migration command in a later plan.

### Engine interaction events schema

Decision: keep engine/server/data/interaction_events.py::ensure_interaction_event_schema

Reason: Engine startup and legacy job tests call this helper directly.

Implementation action: delegate to main runtime migration for interaction tables.

Tests: test_engine_runtime_migrations.py and legacy interaction events test.

Removal condition: only after Engine startup uses explicit migration orchestration.

### Engine moderation schema

Decision: keep engine/server/data/moderation.py::ensure_moderation_schema

Reason: Engine startup and moderation code call this helper directly.

Implementation action: delegate to the current moderation migration resource while leaving similarity purge indexes in moderation code.

Tests: test_engine_runtime_migrations.py.

Removal condition: only after Engine startup uses explicit migration orchestration.

### Engine read indexes

Decision: keep engine/server/data/channels.py::ensure_channels_indexes and engine/server/data/videos.py::ensure_video_indexes

Reason: Engine startup uses these helpers and they preserve conditional no-op behavior for missing content tables.

Implementation action: delegate to apply_main_read_indexes(conn), which reads central SQL but only executes statements whose target tables exist.

Tests: test_engine_runtime_migrations.py.

Removal condition: only after explicit migration orchestration can preserve conditional startup behavior.

### Engine cache schemas

Decision: keep engine/server/data/similarity_cache.py::ensure_similarity_schema and engine/server/data/random_cache.py::ensure_random_cache_schema

Reason: Engine startup and cache jobs call these helpers directly.

Implementation action: delegate to cache migration resource helpers.

Tests: test_cache_migrations.py.

Removal condition: only after cache DB creation is owned by explicit migration commands.

### Crawler schema ownership

Decision: keep crawler schema ownership in engine/crawler/schema.sql

Reason: Stage 7 owns crawler DB split and crawler output behavior.

Implementation action: document ownership and keep existing schema compatibility test.

Tests: tests/engine_data/test_schema_compatibility_snapshot.py.

Removal condition: none in Stage 6.

### Whitelist migration behavior

Decision: keep migrate-whitelist.py and whitelist_migrations.py as the compatibility path for old whitelist DBs.

Reason: historical whitelist DB migration semantics already exist and are outside current-shape runtime wrapper centralization.

Implementation action: document ownership and do not replace or reorder whitelist migration helpers in Stage 6.

Tests: existing schema tests plus this documentation check.

Removal condition: only after a dedicated historical migration plan.

## Future ownership by stage

```text
Stage 7
  Split engine/crawler/src/db.ts and add TypeScript crawler repository tests.

Stage 8
  Refactor frontend UI/API/state code without changing schema ownership.

Stage 9
  Split updater/job orchestration and document operational migration flow.

Future migration-policy stage
  Introduce a full historical migration framework with schema_migrations only if deployment policy requires it.
```

The deferred items above are not Stage 6 gaps. Stage 6 establishes ownership and current-shape migration resources while keeping compatibility wrappers for existing callers.
