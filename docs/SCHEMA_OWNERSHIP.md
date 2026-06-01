# SQLite Schema Ownership

## Purpose

This document defines which component owns each SQLite schema used by PeerTube Browser, which migration/bootstrap entrypoint creates the current shape, and which schema contracts must remain stable during refactoring.

Stage 6 documented ownership and added current-shape SQL resources. The database bootstrap cleanup stage added explicit runtime bootstrap entrypoints above those migration resources. The follow-up legacy-wrapper cleanup removed transitional `ensure_*` schema wrappers after production callers moved to bootstrap functions.

## Client users DB

Owner:

```text
Client backend
```

Current runtime bootstrap source:

```text
client/backend/db/bootstrap.py::bootstrap_client_users_db
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
client/backend/db/bootstrap.py::bootstrap_client_users_db
```

Tables/indexes:

```text
users
likes
likes_user_updated_idx
```

Removed transitional wrappers:

```text
client/backend/lib/users_store.py::ensure_user_schema
```

Current runtime bootstrap path:

```text
client/backend/repositories/users.py::UsersRepository.ensure_schema
  -> client/backend/db/bootstrap.py::bootstrap_client_users_db
```

Current bootstrap rule:

```text
Use `bootstrap_client_users_db` for runtime setup. The transitional `ensure_user_schema` wrapper has been removed.
```

Deferred changes:

```text
Browser profile behavior, route behavior, user identity semantics, and explicit historical migration state.
```

Tests:

```text
tests/db/test_client_user_migrations.py
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
engine/crawler/src/db/* modules
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

Compatibility facade:

```text
engine/crawler/src/db/* modules own crawler DB access; legacy db.ts facade was removed in the crawler compatibility cleanup.
```

Stage 7 database modules:

```text
engine/crawler/src/db/connection.ts
engine/crawler/src/db/schema.ts
engine/crawler/src/db/types.ts
engine/crawler/src/db/instances.ts
engine/crawler/src/db/channels.ts
engine/crawler/src/db/videos.ts
engine/crawler/src/db/utils.ts
```

Allowed Stage 6 changes:

```text
Document ownership and keep compatibility tests around the schema consumed by Engine read paths.
```

Allowed Stage 7 changes:

```text
Split the TypeScript crawler DB layer into narrow modules while keeping schema.sql, command behavior, and direct db/* imports stable.
```

Deferred changes:

```text
crawler schema redesign, crawler command behavior changes, updater/job orchestration, and PeerTube network traversal refactors.
```

Tests:

```text
tests/engine_data/test_schema_compatibility_snapshot.py
engine/crawler/test/db/*.test.ts
```

Compatibility decisions:

```text
docs/CRAWLER_COMPATIBILITY.md
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

Compatibility entrypoints:

```text
engine/server/db/jobs/migrate-whitelist.py
engine/server/db/jobs/whitelist_migrations.py
```

Removed transitional wrappers:

```text
engine/server/data/channels.py::ensure_channels_indexes
engine/server/data/videos.py::ensure_video_indexes
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
```

## Engine runtime tables and indexes

Owner:

```text
Engine API runtime/data layer
```

Current runtime bootstrap source:

```text
engine/server/db/bootstrap.py::bootstrap_engine_runtime_db
engine/server/db/bootstrap.py::bootstrap_engine_moderation_db
engine/server/db/bootstrap.py::bootstrap_engine_read_indexes
```

Current runtime bootstrap source:

```text
engine/server/db/bootstrap.py::bootstrap_engine_runtime_db
engine/server/db/bootstrap.py::bootstrap_engine_moderation_db
engine/server/db/bootstrap.py::bootstrap_engine_read_indexes
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

Removed transitional wrappers:

```text
engine/server/data/interaction_events.py::ensure_interaction_event_schema
engine/server/data/moderation.py::ensure_moderation_schema
engine/server/data/channels.py::ensure_channels_indexes
engine/server/data/videos.py::ensure_video_indexes
```

Current bootstrap rule:

```text
Use Engine bootstrap functions for runtime startup and jobs. Transitional wrapper imports have been removed.
```

Deferred changes:

```text
Changing ingest behavior, moderation semantics, route contracts, startup ownership, or schema lifecycle policy.
```

Tests:

```text
tests/db/test_engine_runtime_migrations.py
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

Current runtime bootstrap source:

```text
engine/server/db/bootstrap.py::bootstrap_engine_similarity_cache_db
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

Removed transitional wrappers:

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

Current runtime bootstrap source:

```text
engine/server/db/bootstrap.py::bootstrap_engine_random_cache_db
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
engine/server/db/jobs/precompute-random-index-ids.py
```

Tables/indexes:

```text
random_index_ids
```

Removed transitional wrappers:

```text
engine/server/data/random_cache.py::ensure_random_cache_schema
```

Current behavior:

```text
Random cache stores `random_index_ids.index_id`, not SQLite rowids.
Old `random_rowids` artifacts are incompatible and must be rebuilt.
```

Deferred changes:

```text
Random-cache cleanup policy and broader artifact lifecycle management.
```

Tests:

```text
tests/db/test_cache_migrations.py
```

## Engine stable ANN index identity

Owner:

```text
Engine jobs and Engine runtime read paths
```

Current source:

```text
engine/server/db/migrations/main/0004_video_index_ids.sql
engine/server/db/jobs/sync-video-index-ids.py
engine/server/data/ann_artifact.py
```

Tables/indexes:

```text
video_index_ids
```

Current behavior:

```text
FAISS ids are `video_index_ids.index_id`.
`sync-video-index-ids.py` must run after prod merge/purge and before ANN/random/similarity artifact builds.
Inactive mappings are retained and excluded from new artifacts.
`similarity_cache` stores video_id + instance_domain, not index ids.
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
engine/server/db/jobs/precompute-random-index-ids.py
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

Operational compatibility:

```text
Existing job entrypoints and helper functions remain unchanged by schema ownership cleanup.
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

## Removed transitional schema wrappers

### Client users schema

Decision: remove client/backend/lib/users_store.py::ensure_user_schema

Reason: production Client callers now use `bootstrap_client_users_db`, and migration tests cover the current users/likes schema directly.

Implementation action: remove the wrapper function and keep `client/backend/db/bootstrap.py` as the runtime bootstrap entrypoint.

Tests: `tests/db/test_client_user_migrations.py`, `tests/db/test_database_bootstrap.py`, and `tests/db/test_no_direct_runtime_ensure_calls.py`.

### Engine interaction and moderation schemas

Decision: remove engine/server/data/interaction_events.py::ensure_interaction_event_schema and engine/server/data/moderation.py::ensure_moderation_schema

Reason: Engine startup and jobs now call explicit bootstrap functions.

Implementation action: remove wrapper functions while keeping interaction ingest and moderation runtime helpers unchanged.

Tests: `tests/db/test_engine_runtime_migrations.py`, `tests/db/test_database_bootstrap.py`, repository tests, Engine API tests, and legacy job interaction tests.

### Engine read indexes

Decision: remove engine/server/data/channels.py::ensure_channels_indexes and engine/server/data/videos.py::ensure_video_indexes

Reason: conditional read-index creation is now owned by `bootstrap_engine_read_indexes` and `apply_main_read_indexes`.

Implementation action: remove wrapper functions and keep read-index migration resources unchanged.

Tests: `tests/db/test_engine_runtime_migrations.py`, `tests/db/test_database_bootstrap.py`, and Engine data/API tests.

### Engine cache schemas

Decision: remove engine/server/data/similarity_cache.py::ensure_similarity_schema and engine/server/data/random_cache.py::ensure_random_cache_schema

Reason: cache DB creation is now owned by explicit cache bootstrap functions.

Implementation action: remove wrapper functions and keep cache migration resources unchanged.

Tests: `tests/db/test_cache_migrations.py`, `tests/db/test_database_bootstrap.py`, and Engine data tests.

## Future ownership by stage

```text
Stage 7
  Split engine/crawler/src/db/* modules and add TypeScript crawler repository tests.

Stage 8
  Refactor frontend UI/API/state code without changing schema ownership.

Stage 9
  Split updater/job orchestration and document operational migration flow.

Future migration-policy stage
  Introduce a full historical migration framework with schema_migrations only if deployment policy requires it.
```

The deferred items above are not Stage 6 gaps. Stage 6 established ownership and current-shape migration resources; later bootstrap cleanup moved production callers to explicit bootstrap entrypoints, and the legacy ensure-wrapper cleanup removed the transitional schema wrappers.
