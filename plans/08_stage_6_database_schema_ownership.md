# Stage 6: Centralize Database Schema and Migration Ownership

## Problem / Goal

Stage 6 makes SQLite schema ownership explicit without changing the current product behavior. The project currently works, but schema creation and compatibility checks are spread across multiple runtime modules, crawler files, and jobs:

```text
client/backend/lib/users_store.py
engine/crawler/schema.sql
engine/crawler/src/db.ts
engine/server/api/server.py
engine/server/data/*.py
engine/server/db/jobs/*.py
engine/server/db/jobs/whitelist_migrations.py
```

The goal is to make each database owner, schema source, and compatibility wrapper clear enough that later stages can safely split crawler repositories, migrate jobs, and adjust deployment docs without hidden schema drift.

Stage 6 must preserve existing runtime behavior. It is not a schema redesign stage. It should introduce current-shape migration files and ownership documentation, then keep existing `ensure_*` helpers as compatibility wrappers around the same SQL behavior. The public API, recommendation behavior, crawler behavior, updater stage order, and data-build output paths must remain unchanged.

Current schema responsibilities found in the codebase:

```text
Client users DB
  owner: Client backend
  current creation helper: client/backend/lib/users_store.py::ensure_user_schema
  current wrapper: client/backend/repositories/users.py::UsersRepository.ensure_schema
  current tables: users, likes
  current key contract: likes PRIMARY KEY (user_id, video_id, instance_domain)

Crawler raw crawl DB
  owner: TypeScript crawler
  current source: engine/crawler/schema.sql
  additional TS compatibility/rebuild logic: engine/crawler/src/db.ts
  current tables: instances, channels, videos, instance_crawl_progress,
                  channel_crawl_progress, video_crawl_progress
  Stage 6 role: document ownership and test compatibility only;
                do not split crawler db.ts and do not change crawler schema.

Engine main API dataset DB
  owner: Engine data-build/jobs + Engine API runtime
  current main dataset creation: engine/server/db/jobs/sync-whitelist.py::ensure_content_schema
  current schema migration helpers: engine/server/db/jobs/whitelist_migrations.py
  current runtime ensure helpers:
    engine/server/data/interaction_events.py::ensure_interaction_event_schema
    engine/server/data/moderation.py::ensure_moderation_schema
    engine/server/data/channels.py::ensure_channels_indexes
    engine/server/data/videos.py::ensure_video_indexes
  current tables added/ensured at API startup: interaction_raw_events,
      interaction_signals, instance_denylist, channel_moderation, plus read indexes.

Engine similarity cache DB
  owner: Engine similarity precompute/runtime
  current creation helpers:
    engine/server/data/similarity_cache.py::ensure_similarity_schema
    engine/server/db/jobs/precompute-similar-ann.py::ensure_schema
  current tables: similarity_sources, similarity_items
  Stage 6 role: centralize the current table/index SQL and keep both callers compatible.

Engine random cache DB
  owner: Engine random-cache job/runtime
  current creation helper: engine/server/data/random_cache.py::ensure_random_cache_schema
  current table: random_rowids

Engine derived artifact tables in main dataset
  owner: Engine jobs
  current creation/migration helpers:
    engine/server/db/jobs/build-video-embeddings.py creates video_embeddings
    engine/server/db/jobs/recompute-popularity.py::ensure_popularity_schema adds videos.popularity
    engine/server/db/jobs/sync-whitelist.py::ensure_content_schema creates videos.popularity in whitelist output
    engine/server/db/jobs/migrate-whitelist.py delegates to whitelist_migrations.py
  Stage 6 role: document and test current compatibility boundaries;
                do not rewrite build jobs or updater orchestration.
```

Stage 6 ends with a documented source of truth for each DB family and migration/compatibility tests proving current helpers still produce the expected schemas.

## Expected Behavior

After Stage 6:

- Existing Stage 0-5 tests still pass.
- `make test` remains the fast regression baseline.
- Runtime startup semantics remain unchanged:
  - `engine/server/api/server.py` still calls the existing `ensure_*` helpers.
  - `client/backend/server.py` still calls `UsersRepository.ensure_schema()`.
  - jobs still call their existing schema helpers and migration entrypoints.
- Existing `ensure_*` helper names remain import-compatible.
- Existing DB output paths documented in `docs/DATA_BUILD.md` remain unchanged:

```text
engine/crawler/data/crawl.db
engine/server/db/whitelist.db
engine/server/db/whitelist-video-embeddings.faiss
engine/server/db/whitelist-video-embeddings.faiss.json
engine/server/db/similarity-cache.db
engine/server/db/random-cache.db
```

- Client likes identity remains:

```sql
PRIMARY KEY (user_id, video_id, instance_domain)
```

- Engine interaction ingest remains event-id idempotent through:

```sql
interaction_raw_events.event_id TEXT PRIMARY KEY
```

- Similarity cache identity remains:

```sql
PRIMARY KEY (
  source_video_id,
  source_instance_domain,
  similar_video_id,
  similar_instance_domain
)
```

- Crawler raw schema remains owned by `engine/crawler/schema.sql` and Stage 6 does not change TypeScript crawler behavior.
- `sync-whitelist.py` and `migrate-whitelist.py` keep their current user-facing behavior and error messages except where documentation adds clearer ownership notes.
- If runtime helper SQL is centralized, wrappers must produce the same tables, columns, indexes, constraints, defaults, and compatibility behavior as before.

Concrete observable behavior that must stay green:

```bash
make test
python3 -m pytest tests/repositories tests/engine_data -q
python3 engine/server/db/jobs/tests/test-interaction-events.py
```

Concrete schema examples to preserve:

```sql
CREATE TABLE IF NOT EXISTS likes (
  user_id TEXT NOT NULL,
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  video_uuid TEXT,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, video_id, instance_domain)
);
```

```sql
CREATE TABLE IF NOT EXISTS interaction_signals (
  video_uuid TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  likes_count INTEGER NOT NULL DEFAULT 0,
  undo_likes_count INTEGER NOT NULL DEFAULT 0,
  comments_count INTEGER NOT NULL DEFAULT 0,
  signal_score REAL NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (video_uuid, instance_domain)
);
```

```sql
CREATE TABLE IF NOT EXISTS random_rowids (
  position INTEGER PRIMARY KEY,
  video_rowid INTEGER NOT NULL
);
```

## Architecture

Stage 6 introduces schema ownership without changing component ownership.

```text
Client backend
  -> owns browser profile/users DB schema
  -> may gain client/backend/db/* current-shape migration helpers
  -> existing users_store.ensure_user_schema remains a compatibility wrapper

Crawler
  -> owns raw crawl schema through engine/crawler/schema.sql
  -> Stage 6 documents and tests this boundary
  -> Stage 7 later splits engine/crawler/src/db.ts

Engine API runtime
  -> owns runtime-created interaction/moderation/index/cache schema helpers
  -> existing engine/server/data/* ensure helpers remain import-compatible
  -> server.py startup keeps calling those helpers

Engine jobs
  -> own dataset build, whitelist migration, embeddings, popularity,
     similarity precompute, and random-cache population behavior
  -> Stage 6 may share current-shape SQL helpers with runtime code
  -> Stage 9 later splits updater/job orchestration
```

Target Stage 6 responsibility split:

```text
docs/SCHEMA_OWNERSHIP.md
  Explains which component owns which SQLite schema, which helper/migration creates it,
  which runtime compatibility wrappers remain, and which later stage owns future changes.

client/backend/db/
  Current-shape migration helpers for the Client users DB.
  This does not move browser profile behavior out of Client backend.

engine/server/db/migrations/
  Current-shape migration helpers for Engine-owned runtime/cache tables.
  These helpers must be callable from existing data-layer ensure wrappers.

engine/crawler/schema.sql
  Remains the raw crawler DB source of truth.
  Stage 6 does not create crawler TypeScript repositories and does not change crawler schema.
```

The important architectural rule is compatibility first: Stage 6 may centralize SQL text and documentation, but it must not change when or why schema creation happens from the caller perspective.

## Touched Files

```text
AGENTS.md
README.md
docs/ARCHITECTURE.md
docs/DATA_BUILD.md
docs/DEVELOPMENT.md
docs/DEPLOYMENT.md
docs/TESTING.md
client/backend/lib/users_store.py
client/backend/repositories/users.py
engine/crawler/schema.sql
engine/crawler/src/db.ts
engine/server/api/server.py
engine/server/data/channels.py
engine/server/data/interaction_events.py
engine/server/data/moderation.py
engine/server/data/random_cache.py
engine/server/data/similarity_cache.py
engine/server/data/users.py
engine/server/data/videos.py
engine/server/db/jobs/build-video-embeddings.py
engine/server/db/jobs/ensure-video-indexes.py
engine/server/db/jobs/migrate-whitelist.py
engine/server/db/jobs/precompute-random-rowids.py
engine/server/db/jobs/precompute-similar-ann.py
engine/server/db/jobs/recompute-popularity.py
engine/server/db/jobs/sync-whitelist.py
engine/server/db/jobs/updater-worker.py
engine/server/db/jobs/whitelist_migrations.py
engine/server/db/jobs/docs/UPDATER_WORKER.md
Makefile
pyproject.toml
```

Most touched files are listed because Stage 6 must inspect and document their schema ownership. Production edits should be narrow. Do not edit `engine/crawler/src/db.ts`, crawler CLI behavior, or updater orchestration unless a concrete Stage 6 compatibility test requires a docstring/comment-only clarification.

## New Files

```text
plans/08_stage_6_database_schema_ownership.md
docs/SCHEMA_OWNERSHIP.md
client/backend/db/__init__.py
client/backend/db/migrations/__init__.py
client/backend/db/migrations/0001_users_and_likes.sql
client/backend/db/migrate.py
engine/server/db/migrations/__init__.py
engine/server/db/migrations/client_readme.md
engine/server/db/migrations/main/__init__.py
engine/server/db/migrations/main/0001_interaction_events.sql
engine/server/db/migrations/main/0002_moderation.sql
engine/server/db/migrations/main/0003_read_indexes.sql
engine/server/db/migrations/similarity_cache/__init__.py
engine/server/db/migrations/similarity_cache/0001_similarity_cache.sql
engine/server/db/migrations/random_cache/__init__.py
engine/server/db/migrations/random_cache/0001_random_cache.sql
engine/server/db/migrations/apply.py
tests/db/test_client_user_migrations.py
tests/db/test_engine_runtime_migrations.py
tests/db/test_cache_migrations.py
tests/db/test_existing_ensure_wrappers_match_migrations.py
tests/db/test_schema_ownership_documentation.py
```

If implementation shows that Python cannot import modules whose package path begins with numeric migration filenames, the SQL files remain plain resources loaded by path. Do not convert migration SQL files into Python modules. The `__init__.py` files only mark helper directories where Python helpers live.

## Implementation Steps

### 1. Verify current baseline before schema work

Run and record current behavior before editing schema code:

```bash
make test
make lint
python3 -m pytest tests/repositories tests/engine_data -q
python3 engine/server/db/jobs/tests/test-interaction-events.py
```

Required action if any command fails before changes:

- Do not edit schema code.
- Record the failing command and reason in implementation notes.
- Fix only environment/precondition issues that are already documented, or keep Stage 6 unimplemented until the baseline is green.

### 2. Inventory current schema creation and ownership

Create `docs/SCHEMA_OWNERSHIP.md` with this purpose paragraph:

```text
This document defines which component owns each SQLite schema used by PeerTube Browser, which helper or migration creates the current shape, and which compatibility wrappers remain during refactoring.
```

The document must include these sections:

```text
Client users DB
Crawler raw crawl DB
Engine main dataset DB
Engine runtime tables and indexes
Engine similarity cache DB
Engine random cache DB
Engine derived artifacts
Compatibility wrappers
Future ownership by stage
```

Each section must list:

```text
Owner:
Current source:
Runtime/job callers:
Tables/indexes:
Compatibility wrappers:
Allowed Stage 6 changes:
Deferred changes:
Tests:
```

Concrete entries:

```text
Client users DB
Owner: Client backend
Current source: client/backend/lib/users_store.py::ensure_user_schema
Stage 6 migration source: client/backend/db/migrations/0001_users_and_likes.sql
Compatibility wrapper: client/backend/lib/users_store.py::ensure_user_schema
Deferred changes: browser profile behavior, identity semantics, route behavior
```

```text
Crawler raw crawl DB
Owner: engine/crawler
Current source: engine/crawler/schema.sql
Stage 6 migration source: none; schema.sql remains source of truth
Compatibility wrapper: not changed in Stage 6
Deferred changes: engine/crawler/src/db.ts split and TypeScript repository tests in Stage 7
```

```text
Engine main dataset DB
Owner: Engine jobs and data-build flow
Current sources: sync-whitelist.py, whitelist_migrations.py, build-video-embeddings.py,
                 recompute-popularity.py
Stage 6 migration source: documentation and tests only for whitelist/content shape;
                          do not replace job migration flow in Stage 6
Deferred changes: updater/job orchestration in Stage 9
```

```text
Engine runtime tables
Owner: Engine API runtime/data layer
Current sources: data.interaction_events, data.moderation, data.channels, data.videos
Stage 6 migration source: engine/server/db/migrations/main/*.sql
Compatibility wrapper: existing ensure_* functions delegate to current-shape SQL application
```

### 3. Add Client users DB migration resources

Add:

```text
client/backend/db/migrations/0001_users_and_likes.sql
client/backend/db/migrate.py
```

`0001_users_and_likes.sql` must contain the exact current `users` and `likes` table/index SQL from `client/backend/lib/users_store.py::ensure_user_schema`, including:

```sql
CREATE TABLE IF NOT EXISTS users (...);
CREATE TABLE IF NOT EXISTS likes (... PRIMARY KEY (user_id, video_id, instance_domain));
CREATE INDEX IF NOT EXISTS likes_user_updated_idx ON likes (user_id, updated_at DESC);
```

`client/backend/db/migrate.py` responsibilities:

- `apply_client_user_migrations(conn: sqlite3.Connection) -> None`
- load SQL resource files in filename order;
- execute them through `conn.executescript`;
- commit after applying;
- not create a migration history table in Stage 6, because current helpers are idempotent current-shape compatibility wrappers, not ordered historical migrations.

Update `client/backend/lib/users_store.py::ensure_user_schema` to call `apply_client_user_migrations(conn)`.

Compatibility requirement:

- All existing callers continue to call `ensure_user_schema` or `UsersRepository.ensure_schema`.
- Do not change `record_like`, `fetch_recent_likes`, `clear_likes`, or `remove_like`.

### 4. Add Engine runtime/cache migration resources

Add a generic SQL resource helper:

```text
engine/server/db/migrations/apply.py
```

Responsibilities:

- `apply_sql_migrations(conn: sqlite3.Connection, directory: Path) -> None`
- execute `*.sql` files in filename order;
- commit after applying;
- not create a migration history table in Stage 6;
- expose small directory helpers for current migration families if helpful:

```python
apply_main_runtime_migrations(conn)
apply_similarity_cache_migrations(conn)
apply_random_cache_migrations(conn)
```

Add main runtime migrations:

```text
engine/server/db/migrations/main/0001_interaction_events.sql
engine/server/db/migrations/main/0002_moderation.sql
engine/server/db/migrations/main/0003_read_indexes.sql
```

`0001_interaction_events.sql` must contain current SQL from `data/interaction_events.py::ensure_interaction_event_schema`.

`0002_moderation.sql` must contain current SQL from `data/moderation.py::ensure_moderation_schema` only:

```text
instance_denylist
idx_instance_denylist_active
channel_moderation
idx_channel_moderation_status_instance
```

Do not include similarity purge indexes in this file. Those are optional purge-performance indexes created by `ensure_similarity_purge_indexes(conn)` and must remain in `data/moderation.py` for now because they apply to similarity DBs and are invoked by operational moderation flows.

`0003_read_indexes.sql` must contain current index SQL from:

```text
engine/server/data/channels.py::ensure_channels_indexes
engine/server/data/videos.py::ensure_video_indexes
```

Constraint: `ensure_video_indexes` currently checks whether `videos` and `video_embeddings` tables exist before creating indexes. A raw SQL migration cannot do conditional `CREATE INDEX ON missing_table`. Required action:

- Keep `ensure_video_indexes` table-existence checks in Python.
- Either do not move video index SQL to raw migration files, or expose an `apply_main_read_indexes(conn)` Python helper that checks table existence before executing SQL.
- The plan prefers the second option: `0003_read_indexes.sql` may contain comment-separated SQL snippets, but `apply_main_read_indexes(conn)` must execute only the snippets whose target tables exist.

Add cache migrations:

```text
engine/server/db/migrations/similarity_cache/0001_similarity_cache.sql
engine/server/db/migrations/random_cache/0001_random_cache.sql
```

These must match:

```text
engine/server/data/similarity_cache.py::ensure_similarity_schema
engine/server/data/random_cache.py::ensure_random_cache_schema
```

### 5. Make existing Engine `ensure_*` helpers compatibility wrappers

Update existing helpers to delegate to migration helper functions where doing so is behavior-preserving:

```text
engine/server/data/interaction_events.py::ensure_interaction_event_schema
engine/server/data/moderation.py::ensure_moderation_schema
engine/server/data/similarity_cache.py::ensure_similarity_schema
engine/server/data/random_cache.py::ensure_random_cache_schema
```

For index helpers:

```text
engine/server/data/channels.py::ensure_channels_indexes
engine/server/data/videos.py::ensure_video_indexes
```

Required action:

- Preserve current table-existence guard behavior in `ensure_video_indexes`.
- Preserve current no-op behavior if neither `videos` nor `video_embeddings` exists.
- Preserve current behavior of `ensure_channels_indexes`. If indexes target `channels` and `channels` is missing, do not introduce a new failure if current startup/test behavior does not cover that missing-table path. If implementation discovers SQLite raises for missing `channels`, keep current behavior and document that channels indexes require the content table.

Do not update:

```text
engine/server/db/jobs/sync-whitelist.py::ensure_content_schema
engine/server/db/jobs/whitelist_migrations.py
engine/crawler/src/db.ts
engine/crawler/schema.sql
```

except for comments/docstrings if needed. These remain owned by their current job/crawler paths until later stages.

### 6. Add migration and wrapper tests

Add `tests/db/` and update `pyproject.toml` so pytest discovers it:

```toml
[tool.pytest.ini_options]
testpaths = [
  ...,
  "tests/db",
]
```

Add `tests/db/test_client_user_migrations.py`:

- apply `apply_client_user_migrations` to a temp SQLite DB;
- assert `users` and `likes` tables exist;
- assert `likes_user_updated_idx` exists;
- assert `likes` primary key is `(user_id, video_id, instance_domain)`;
- assert applying migrations twice is idempotent;
- assert `client.backend.lib.users_store.ensure_user_schema` produces the same table/index set.

Add `tests/db/test_engine_runtime_migrations.py`:

- apply main runtime migrations to temp SQLite DB with minimal `videos`, `channels`, and `video_embeddings` tables where indexes require them;
- assert interaction tables and moderation tables exist;
- assert interaction indexes exist;
- assert moderation indexes exist;
- assert read indexes from current helpers exist;
- assert applying migrations twice is idempotent;
- assert `ensure_interaction_event_schema`, `ensure_moderation_schema`, `ensure_channels_indexes`, and `ensure_video_indexes` remain callable and produce same table/index set.

Add `tests/db/test_cache_migrations.py`:

- apply similarity cache migrations and assert `similarity_sources`, `similarity_items`, and `similarity_source_rank_idx` exist;
- apply random cache migrations and assert `random_rowids` exists;
- assert current `ensure_similarity_schema` and `ensure_random_cache_schema` wrappers produce equivalent table/index sets.

Add `tests/db/test_existing_ensure_wrappers_match_migrations.py`:

- compare schema signatures for wrapper-created DBs and migration-created DBs.
- schema signature should include table names, column names, notnull/default/pk flags, and index names.
- do not compare raw SQL text because SQLite normalizes SQL and comments differently.

Add `tests/db/test_schema_ownership_documentation.py`:

- assert `docs/SCHEMA_OWNERSHIP.md` exists;
- assert it contains the required sections:

```text
Client users DB
Crawler raw crawl DB
Engine main dataset DB
Engine runtime tables and indexes
Engine similarity cache DB
Engine random cache DB
Engine derived artifacts
Compatibility wrappers
Future ownership by stage
```

### 7. Update docs without changing operational commands

Update `docs/ARCHITECTURE.md`:

- add a short DB ownership paragraph under `Crawler and Jobs` or a new `SQLite Schema Ownership` subsection;
- state that `docs/SCHEMA_OWNERSHIP.md` is the detailed source.

Update `docs/DATA_BUILD.md`:

- preserve all existing commands and paths;
- add a short note near the whitelist/migration section:

```text
Schema ownership and compatibility wrappers are documented in docs/SCHEMA_OWNERSHIP.md. Stage 6 does not change the data-build commands.
```

Update `docs/DEVELOPMENT.md`:

- add `client/backend/db` and `engine/server/db/migrations` to the project map;
- say existing `ensure_*` helpers are compatibility wrappers.

Update `docs/TESTING.md`:

- add `tests/db` to Python behavior tests;
- mention migration/schema ownership tests are part of `make test`.

Update `README.md` only if its documentation list omits `docs/SCHEMA_OWNERSHIP.md`. Do not add detailed schema text to README.

Update `docs/DEPLOYMENT.md` only if it states that runtime startup is the only source of schema creation. If no such statement exists, leave it unchanged.

### 8. Update tooling surface

Update `Makefile` `lint` target to include only the new maintained Stage 6 Python files and tests:

```text
client/backend/db
engine/server/db/migrations
tests/db
```

Do not expand lint to legacy crawler/job files in Stage 6.

`make test` should pick up `tests/db` through `pyproject.toml`.

### 9. Preserve compatibility decisions in docs

Create compatibility notes inside `docs/SCHEMA_OWNERSHIP.md`, not a separate compatibility doc unless implementation adds a real shim beyond existing `ensure_*` wrappers.

For every Stage 6 compatibility wrapper, include:

```text
Decision:
Reason:
Implementation action:
Tests:
Removal condition, if any:
```

Required entries:

```text
Decision: keep client/backend/lib/users_store.py::ensure_user_schema
Reason: existing Client startup and repository code call this helper
Implementation action: make it delegate to apply_client_user_migrations(conn)
Tests: test_client_user_migrations.py
Removal condition: only after all callers use explicit migration command in a later plan
```

```text
Decision: keep engine/server/data/interaction_events.py::ensure_interaction_event_schema
Reason: Engine startup and legacy job tests call this helper directly
Implementation action: delegate to main runtime migration for interaction tables
Tests: test_engine_runtime_migrations.py and legacy interaction events test
Removal condition: only after Engine startup uses explicit migration orchestration
```

```text
Decision: keep crawler schema ownership in engine/crawler/schema.sql
Reason: Stage 7 owns crawler DB split and crawler output behavior
Implementation action: document ownership and keep existing schema compatibility test
Tests: tests/engine_data/test_schema_compatibility_snapshot.py
Removal condition: none in Stage 6
```

### 10. Run verification

Required after implementation:

```bash
make test
make lint
python3 -m pytest tests/db -q
python3 -m pytest tests/repositories tests/engine_data -q
python3 engine/server/db/jobs/tests/test-interaction-events.py
python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit
```

Expected environment-sensitive check:

```bash
python3 engine/server/api/server.py --help
```

This may still fail on missing FAISS because Stage 6 does not change Engine startup dependency loading.

## Tests

Stage 6 test policy:

- New schema behavior must be pytest tests.
- Tests must use temporary SQLite databases.
- Tests must assert real schema effects: tables, columns, primary keys, indexes, defaults, and wrapper idempotency.
- Tests must not use production DB files.
- Tests must not require FAISS, Node dependencies, crawler runtime, or network.

Required tests:

```text
tests/db/test_client_user_migrations.py
tests/db/test_engine_runtime_migrations.py
tests/db/test_cache_migrations.py
tests/db/test_existing_ensure_wrappers_match_migrations.py
tests/db/test_schema_ownership_documentation.py
```

Existing tests that must remain green:

```text
tests/repositories/test_client_users_store.py
tests/repositories/test_engine_interaction_events.py
tests/engine_data/test_schema_compatibility_snapshot.py
tests/engine_api/test_internal_events_ingest_characterization.py
engine/server/db/jobs/tests/test-interaction-events.py
```

Assertions to include:

```text
Client likes PK remains user_id, video_id, instance_domain.
Interaction raw events PK remains event_id.
Interaction signal PK remains video_uuid, instance_domain.
Similarity item PK remains source_video_id, source_instance_domain,
  similar_video_id, similar_instance_domain.
Random cache table remains random_rowids(position, video_rowid).
Wrapper-created schemas and migration-created schemas have matching signatures.
Applying migrations twice produces the same schema signature.
```

## Documentation Maintenance

Stage 6 must update documentation because it changes the documented source of schema ownership.

Required doc updates:

```text
docs/SCHEMA_OWNERSHIP.md
  Main Stage 6 documentation artifact. Defines owners, current sources,
  compatibility wrappers, tests, and deferred future work.

docs/ARCHITECTURE.md
  Add a short schema ownership pointer and keep component boundaries intact.

docs/DATA_BUILD.md
  Preserve commands; add a schema ownership pointer near migration/data-build notes.

docs/DEVELOPMENT.md
  Add new db/migration directories to the navigation map.

docs/TESTING.md
  Add tests/db to fast Python test coverage.

README.md
  Add docs/SCHEMA_OWNERSHIP.md to documentation list only if the README lists docs.
```

Do not update unrelated frontend, recommendation, or Engine API compatibility docs unless implementation touches those responsibilities.

## Remaining Ownership After Stage 6

After Stage 6, the following are intentionally still deferred:

```text
engine/crawler/src/db.ts split
  Deferred to Stage 7.

Crawler TypeScript repository tests
  Deferred to Stage 7.

Updater/job orchestration split
  Deferred to Stage 9.

Full historical migration framework with schema_migrations table
  Deferred until explicit deployment policy requires ordered historical migrations.

Removing runtime ensure_* wrappers
  Deferred until startup/data-build docs and callers use explicit migration commands.

Changing whitelist DB schema or crawler raw schema
  Deferred to dedicated data-build/crawler plans with migration tests.
```

These deferred items are not gaps. Stage 6 establishes ownership and current-shape migration resources, then keeps compatibility wrappers so later stages have clear boundaries.

## Non-Negotiable Implementation Constraints

### Constraint: no schema redesign

Stage 6 must not rename columns, change primary keys, add required columns, change defaults, or alter table ownership.

Required action:

- Copy current SQL shape into migration resources.
- Add tests comparing wrapper-created and migration-created schemas.
- If a current schema has a known imperfect behavior, document it rather than fixing it in Stage 6.

### Constraint: no crawler behavior changes

Stage 6 must not edit crawler network traversal, repository logic, rebuild logic, or raw schema contents.

Required action:

- Keep `engine/crawler/schema.sql` unchanged.
- Keep `engine/crawler/src/db.ts` unchanged except possible comments if absolutely necessary.
- Use `tests/engine_data/test_schema_compatibility_snapshot.py` and `docs/SCHEMA_OWNERSHIP.md` to freeze ownership until Stage 7.

### Constraint: no Engine startup behavior changes

Stage 6 must not move startup responsibility out of `engine/server/api/server.py` or isolate FAISS.

Required action:

- Keep `server.py` calling existing `ensure_*` helpers.
- Make helpers delegate internally if centralizing SQL.
- Do not make `server.py` call new migration modules directly in Stage 6.

### Constraint: no job orchestration changes

Stage 6 must not change updater stage order, job commands, lock/resume behavior, or installer behavior.

Required action:

- Leave `engine/server/db/jobs/updater-worker.py` orchestration unchanged.
- Leave `sync-whitelist.py`, `migrate-whitelist.py`, and `whitelist_migrations.py` behavior unchanged unless adding comments/docstrings.
- Document current ownership and defer job split to Stage 9.

### Constraint: conditional index behavior must remain conditional

`ensure_video_indexes` currently avoids creating indexes when target tables are absent.

Required action:

- Preserve Python table-existence checks.
- Do not replace this helper with unconditional raw SQL.
- Test both missing-table no-op behavior and existing-table index creation behavior.

### Constraint: no API or recommendation behavior changes

Stage 6 must not touch Client/Engine route contracts or recommendation pipeline behavior.

Required action:

- Avoid editing `engine/server/api/routes/*`, `engine/server/api/services/*`, and `engine/server/api/recommendations/*` except import-path adjustments that are proven necessary by tests.
- If a schema change appears necessary for route/recommendation behavior, that is out of Stage 6 scope and must not be implemented here.

## Regression and Blind-Spot Analysis

### Risk: wrapper migration changes Client likes identity

Action:

- Keep SQL identical to current `users_store.ensure_user_schema`.
- Add `test_client_user_migrations.py` assertion for PK column order.
- Run existing Client users repository tests.

### Risk: Engine interaction ingest idempotency changes

Action:

- Keep `interaction_raw_events.event_id` as primary key.
- Add migration/wrapper equivalence tests.
- Run `tests/repositories/test_engine_interaction_events.py` and legacy `test-interaction-events.py`.

### Risk: similarity cache migration diverges from precompute job schema

Action:

- Copy SQL from `data/similarity_cache.py` and compare with `precompute-similar-ann.py::ensure_schema` during implementation.
- Keep precompute job behavior unchanged.
- Add cache migration tests for table/index names and PKs.

### Risk: random cache migration diverges from runtime population behavior

Action:

- Copy SQL from `data/random_cache.py::ensure_random_cache_schema`.
- Add migration and wrapper equivalence tests.
- Do not change `populate_random_cache` query logic.

### Risk: read indexes fail on empty DBs

Action:

- Preserve current table-existence checks in Python wrappers.
- Add tests for missing-table no-op and existing-table index creation.
- Do not run unconditional `CREATE INDEX` against missing tables.

### Risk: Stage 6 duplicates but does not replace old SQL, causing future confusion

Action:

- `docs/SCHEMA_OWNERSHIP.md` must explicitly identify compatibility wrappers and current migration resources.
- Each wrapper docstring should say it delegates to current-shape migrations where applicable.
- Tests should compare wrapper and migration schema signatures.

### Risk: documentation claims explicit migration commands are required when runtime still creates schema opportunistically

Action:

- Documentation must say runtime `ensure_*` helpers remain compatibility wrappers.
- Do not document a new required production migration command in Stage 6.
- Data-build commands stay unchanged.

### Blind spot: old production DBs may have pre-current schema shapes not represented in tests

Action:

- Stage 6 does not claim full historical migration support.
- Keep `whitelist_migrations.py` and `migrate-whitelist.py` unchanged for existing whitelist DB migration behavior.
- Document full historical migrations as deferred until deployment policy requires them.

### Blind spot: TypeScript crawler schema rebuild logic may create shapes beyond `schema.sql`

Action:

- Do not refactor `engine/crawler/src/db.ts` in Stage 6.
- Document that Stage 7 must reconcile TS rebuild logic with `schema.sql` before splitting crawler repositories.
- Keep current crawler schema compatibility snapshot test.

## Generic vs Project-Specific Behavior

Generic behavior:

- Schema ownership should be explicit.
- Idempotent current-shape SQL wrappers can preserve behavior while centralizing responsibility.
- Temporary SQLite databases are the correct test boundary for schema compatibility.

Project-specific behavior:

- Client users DB belongs to Client backend, not Engine.
- Crawler raw schema belongs to `engine/crawler/schema.sql` and Stage 7 crawler code.
- Engine main dataset is produced by jobs and consumed by Engine data modules.
- Engine runtime tables such as interaction events and moderation are created through current Engine API/data helpers.
- Similarity and random cache DBs are separate artifacts with separate schema ownership.
- Runtime `ensure_*` helpers remain compatibility wrappers during this refactor sequence.

## Compatibility and Backward Compatibility Decisions

Record these decisions in `docs/SCHEMA_OWNERSHIP.md` during implementation.

### Keep runtime ensure wrappers

Decision:

- Keep all current `ensure_*` helper names and call sites.

Reason:

- Engine startup, Client startup, tests, and jobs already call these helpers.

Implementation action:

- Delegate helpers to current-shape migration SQL where safe.
- Preserve conditional Python logic where raw SQL cannot preserve behavior.

Tests:

- Wrapper/migration equivalence tests in `tests/db`.

Removal condition:

- Only after a future stage introduces explicit migration commands and updates startup/data-build docs.

### Keep crawler schema ownership unchanged

Decision:

- Keep `engine/crawler/schema.sql` as raw crawler schema source.

Reason:

- Stage 7 owns crawler `db.ts` split and raw crawler behavior.

Implementation action:

- Document ownership and keep compatibility snapshot tests.

Tests:

- Existing `tests/engine_data/test_schema_compatibility_snapshot.py`.

Removal condition:

- None in Stage 6.

### Keep whitelist migration behavior unchanged

Decision:

- Keep `migrate-whitelist.py` and `whitelist_migrations.py` as the compatibility path for old whitelist DBs.

Reason:

- Historical whitelist DB migration semantics already exist and are outside current-shape runtime wrapper centralization.

Implementation action:

- Document ownership.
- Do not replace or reorder whitelist migration helpers in Stage 6.

Tests:

- Existing data/schema tests plus any new documentation assertions.

Removal condition:

- Only after a dedicated historical migration plan.

## Open Questions

None for Stage 6 scope.
