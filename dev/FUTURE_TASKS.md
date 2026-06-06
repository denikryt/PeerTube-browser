# Future Tasks

This file tracks tasks discovered during planning that are intentionally out of scope for the current implementation plan. Add items here when they are real follow-up work, not vague ideas.

## 1. Cleanup workflow for inactive `video_index_ids`

### Source

`plans/15_stable_ann_index_identity.md`

### Reason

The Stable ANN / Index Identity migration keeps inactive `video_index_ids` rows to avoid unsafe id reuse. This is the safe default for Milestone 0, but inactive rows may accumulate over time when videos or embeddings disappear.

### Future Work

Add a cleanup workflow that can safely delete old inactive mappings only after obsolete FAISS/random artifacts are guaranteed to be gone.

The future design must define:

- how old an inactive row must be before it is eligible for deletion;
- how to prove no active artifact can still reference the inactive `index_id`;
- whether cleanup is manual, scheduled, or part of a maintenance command;
- whether deleted mappings need an audit log before removal;
- how cleanup interacts with backups and rollback.

### Not In Current Scope

Milestone 0 must only soft-retire inactive mappings with `is_active = 0`, `retired_at`, and `retired_reason`. It must not hard-delete mappings.

## 2. Public API identity cleanup for Discovery API v1

### Source

`plans/15_stable_ann_index_identity.md`

### Reason

The Stable ANN / Index Identity migration changes only internal ANN/random artifact identity. It does not change public API responses, frontend URLs, or request identity rules.

The project still needs a clear public video identity contract before or during Discovery API v1.

### Future Work

Define and implement the public API identity contract for videos:

- when to use `video_id`;
- when to use `video_uuid`;
- whether `host` or `instance_domain` is required;
- how `/videos/{id}` should resolve ambiguous ids;
- what frontend URLs should store;
- which fields are public and which fields are internal-only;
- how Client backend should normalize browser-facing identity before forwarding to Engine.

### Not In Current Scope

Milestone 0 must not expose `index_id`, rename API response fields, change frontend URL identity, or redesign public Discovery API routes.

## 3. Evaluate uuid-first video identity model

### Source

`plans/16_discovery_api_v1.md`

### Reason

Discovery API v1 keeps both `video_id` and `video_uuid` in public video payloads. A future migration may evaluate whether `video_uuid + instance_domain` can replace internal `video_id + instance_domain` as the primary project identity.

### Future Work

Evaluate a uuid-first identity model across `videos`, `video_embeddings`, `video_index_ids`, `similarity_cache`, recommendations, likes, resolve logic, and DB migrations.

### Not In Current Scope

Discovery API v1 must not replace the current canonical internal `video_id + instance_domain` model.

## 4. Design seek-based cursors for large discovery feeds

### Source

`plans/16_discovery_api_v1.md`

### Reason

Discovery API v1 starts with opaque Client-owned cursors. The first implementation may use offset-style cursor payloads internally while keeping the cursor opaque to the frontend.

### Future Work

Design feed-specific seek cursors for large/dynamic feeds, especially `fresh`, `popular`, `recommendations`, and deterministic random sessions.

### Not In Current Scope

Discovery API v1 must keep cursors opaque and route-bound, but it does not need full seek-pagination semantics for every feed.

## 5. Optimize recommendation mix pool latency

### Source

Post-Discovery API v1 runtime profiling after cache seed lookup and cached similarity fixes.

### Reason

The cache-optimized exploit path is now fast again: seed lookup is near-zero, similarity cache hits return rows, and exploit timing is down to milliseconds on warm runs. Remaining recommendation latency is now dominated by non-cache layers, especially `explore` and `popular` pool construction/scoring.

Recent verbose logs show examples such as:

- `explore` taking roughly 1.7-3.8s depending on cache state;
- `popular` taking roughly 2.4-5.1s depending on cache state;
- `exploit` taking roughly 18-65ms after the cache fixes.

### Future Work

Profile and optimize the recommendation mix layers that are still expensive:

- `engine/server/api/recommendations/candidates/explore_range.py`;
- popular candidate pool construction/scoring;
- random/fresh pool access only if profiling shows regressions;
- possible reuse of precomputed pools, prepared queries, smaller candidate pools, or cheaper sampling strategies;
- clearer per-layer timing tests or benchmark scripts for large SQLite databases.

### Not In Current Scope

The cache seed lookup and cached similarity correctness fixes must not be expanded into recommendation algorithm redesign. This task is a separate performance optimization milestone after the index-migration regressions are resolved.
## 6. Search v1 follow-up work

### Source

`plans/17_search_v1.md`

### Reason

Search API v1 intentionally ships a lightweight SQLite FTS5 index over title, channel name, tags/category, and instance domain only. It avoids heavier indexing and incremental sync so the first search surface remains simple and tied to the current updater lifecycle.

### Future Work

Evaluate and design the deferred search capabilities:

- full-description search indexing;
- external search engines for advanced ranking/filtering, such as Meilisearch, Typesense, Elasticsearch/OpenSearch, or Tantivy;
- incremental FTS search index sync instead of full rebuild only.

### Not In Current Scope

Search v1 must not add description indexing, semantic/embedding search, external search services, or incremental FTS synchronization.

## 7. Live smoke coverage for PeerTube thumbnail contracts

### Source

Thumbnail refresh investigation and crawler media-selection follow-up.

### Reason

Current crawler thumbnail tests are deterministic and local by design: they verify the project's media-selection rules without depending on third-party PeerTube uptime or mutable remote data.

The project may still benefit from a separate live verification layer against real PeerTube instances to detect contract drift in `/api/v1/videos/:uuid`, thumbnail path availability, or image-host behavior that local fixture tests cannot observe.

### Future Work

Design a non-blocking live smoke suite for real PeerTube instances:

- accept a curated list of `host + video_uuid` or similar stable fixture inputs;
- fetch live `/api/v1/videos/:uuid` payloads and validate the expected thumbnail/preview fields;
- resolve the browser-facing image URL using the same crawler media-selection rules;
- verify the resulting URL returns a successful response or image-like content type;
- report per-instance failures without making the main deterministic test suite flaky;
- decide whether the smoke runner is manual-only, scheduled, or optional in CI;
- define how instance fixture churn is maintained when videos disappear or hosts degrade.

### Not In Current Scope

Current thumbnail fixes must keep deterministic local regression tests as the required coverage. They must not replace core crawler tests with live network-dependent checks.
