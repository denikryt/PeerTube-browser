# Completed tasks

### 47) Smoke tests for installers/uninstallers and Engine/Client service interaction (with guaranteed cleanup) (done)
**Done:** implemented full installer/uninstaller smoke coverage for split services, including runtime readiness checks, e2e Client->Engine validation, and guaranteed teardown.

#### **What was implemented:**
- Added dedicated installer/uninstaller smoke script:
  - `tests/run-installers-smoke.sh`
- Implemented full entrypoint contract matrix checks (`--help`, `--dry-run`) for:
  - centralized install/uninstall scripts,
  - prod/dev wrappers,
  - service-specific Engine/Client install/uninstall scripts.
- Added live functional checks for dev contour:
  - install -> service active -> HTTP readiness (`/api/health`) -> e2e write flow (`/api/user-action`) -> uninstall -> endpoint down + artifacts removed.
- Added contour isolation and idempotency checks:
  - repeated install/uninstall must succeed,
  - dev operations must not modify prod contour state.
- Added structured diagnostics for failures:
  - `systemctl status` + `journalctl` tails in smoke run logs.
- Added guaranteed cleanup path:
  - uninstall-first teardown with fallback residual cleanup,
  - no leftover test dev services/artifacts after run.
- Added post-e2e test data cleanup:
  - reset test user profile likes through Client API,
  - remove test-ingested Engine interaction events and reconcile aggregated signals.
- Updated run docs in `README.md` and `DEPLOYMENT.md` for the split smoke flow.

### 51) Uninstall scripts for service installers (Engine/Client + centralized prod/dev) (done)
**Done:** implemented symmetric uninstall flow for Engine/Client services with centralized prod/dev/all orchestration and contour-safe cleanup.

#### **What was implemented:**
- Added service-specific uninstallers with explicit `--mode prod|dev` and optional service-name overrides:
  - `engine/uninstall-engine-service.sh`
  - `client/uninstall-client-service.sh`
- Added centralized uninstaller with mode contract `--mode prod|dev|all`:
  - `uninstall-service.sh`
- Added wrapper presets for contour-specific runs:
  - `uninstall-service-prod.sh`
  - `uninstall-service-dev.sh`
- Implemented uninstall behavior for contour units/artifacts:
  - stop/disable/remove service and timer units,
  - remove updater sudoers file,
  - run `systemctl daemon-reload` and `systemctl reset-failed`,
  - optional updater state cleanup via `--purge-updater-state`.
- Updated runbooks in `README.md` and `DEPLOYMENT.md` with uninstall usage examples.

### 46) Prod/Dev service installers: separate Engine/Client installers + centralized mode installer (done)
**Done:** implemented split service installers for Engine/Client and one centralized prod/dev mode orchestrator with contour isolation.

#### **What was implemented:**
- Added service-specific installers with explicit `--mode prod|dev` contracts:
  - `engine/install-engine-service.sh`
  - `client/install-client-service.sh`
- Reworked centralized orchestrator `install-service.sh` to support `--mode prod|dev|all` and pass contour settings to both service installers.
- Added mode preset wrappers:
  - `install-service-prod.sh`
  - `install-service-dev.sh`
- Implemented contour-specific unit naming and routing isolation:
  - prod: `peertube-engine`, `peertube-client`, optional `peertube-updater`
  - dev: `peertube-engine-dev`, `peertube-client-dev`, optional `peertube-updater-dev`
- Implemented prod/dev defaults and flags:
  - prod default force-reinstall behavior for prod units
  - dev timer toggle (`--with-updater-timer` / `--without-updater-timer`) with non-prod-safe defaults
- Updated service install docs in `README.md` and `DEPLOYMENT.md` for the new installer topology.

### 50) Remove Engine dependency on local users likes DB for recommendations (interaction-signals-only ranking input) (done)
**Done:** removed Engine recommendation-path dependency on local users likes DB and finalized interaction-signals-only ranking input contract.

#### **What was implemented:**
- Removed Engine runtime dependency on users DB in API server wiring and shared server state.
- Removed request-context fallback to Engine users likes storage; Engine now uses request-scoped likes only for recommendation-path user-like input.
- Updated recommendation modules/sources/candidates to stop reading likes via `server.user_db` and use the request-like contract.
- Extended split smoke with runtime assertion that Engine process does not open `engine/server/db/users.db` (`engine_users_db_fd_absent`).
- Updated docs to explicitly state interaction-signal-driven ranking and no local Engine users likes DB dependency.

### 45) Engine/Client architecture split: read-only Engine + temporary bridge ingest (ActivityPub-ready) (done)
**Done:** separated Engine and Client workspaces/services and introduced a temporary bridge ingest contract for write-derived signals.

#### **What was implemented:**
- Established top-level split into `engine/` and `client/`, with crawler located under `engine/crawler/`.
- Kept Engine API as read/analytics surface (`/recommendations`, `/videos/{id}/similar`, `/videos/similar`, `/api/video`, `/api/health`) without public user write/profile routes.
- Kept Client backend as write/profile surface (`/api/user-action`, `/api/user-profile/*`) and publishing path toward Engine.
- Added Engine internal bridge ingest endpoint (`/internal/events/ingest`) with normalized event schema and idempotent `event_id` handling.
- Added Engine raw/aggregated interaction storage (`interaction_raw_events`, `interaction_signals`) and ranking usage of aggregated interaction signals.
- Added split-boundary smoke coverage and bridge-flow checks via `tests/run-arch-split-smoke.sh`.

### 49) Remove direct Client->Engine code/DB coupling (API-only contract) (done)
**Done:** enforced strict API-only Client/Engine interaction and removed direct Client coupling to Engine internals.

#### **What was implemented:**
- Removed Client imports from `engine.server.*` and eliminated direct Engine DB access from `client/backend/server.py`.
- Added Client-owned helper modules under `client/backend/lib/*` for HTTP/time/users helpers and Engine API access.
- Added Engine internal read endpoints for Client flow (`/internal/videos/resolve`, `/internal/videos/metadata`) and wired routing.
- Added boundary regression script `tests/check-client-engine-boundary.sh` and integrated it into `tests/run-arch-split-smoke.sh`.
- Updated split-boundary docs in `README.md`, `DEPLOYMENT.md`, `client/backend/README.md`, and `engine/server/README.md`.

### 48) Split architecture smoke test: Engine/Client boundary + bridge flow + endpoint contracts (done)
**Done:** added a dedicated split-boundary smoke test with bridge-flow checks and structured diagnostics.

#### **What was implemented:**
- Added `tests/run-arch-split-smoke.sh` to validate Engine/Client health, endpoint ownership boundaries, and Client -> Engine bridge flow.
- Added interaction checks for like action through Client API and response contract validation (`ok`, `bridge_ok`, `bridge_error`).
- Added guaranteed cleanup via trap/finally logic so started test processes are stopped on success, failure, or interruption.
- Added persistent smoke logs under `tmp/arch-split-smoke-logs/` (`*.run.log`, `*.checks.log`, `*.errors.log`) for failure analysis.

### 35) Persistent instance denylist (done)
**Done:** implemented a persistent denylist source of truth and wired it into serving/sync/ingest paths.

#### **What was implemented:**
- Added shared moderation primitives in `server/data/moderation.py` (schema, normalization, row filtering, purge helpers).
- Added denylist CLI `server/db/jobs/instance-denylist-cli.py` with `block/unblock/list` and optional purge (`--purge-now`, `--dry-run`, `--yes`).
- Integrated denylist in `sync-whitelist.py` (subtract denylisted hosts, counters `denylisted_skipped`/`denylisted_purged`).
- Integrated denylist in `updater-worker.py` and crawler CLIs (`--exclude-hosts-file`) including defensive post-merge purge.
- Added central serving-time moderation filter in `/api/similar` response path with `filtered_by_denylist` logging.

### 32) Instance moderation: full purge + ignore (done)
**Done:** implemented instance-level ignore/allow/purge operations and reused the same moderation source of truth.

#### **What was implemented:**
- Kept instance moderation flow as an operational wrapper over `instance_denylist` (single host-level source of truth).
- Extended `server/db/jobs/instance-denylist-cli.py` usage for host moderation operations (`block/unblock/list` + purge flow), with dry-run and explicit confirmation for destructive purge.
- Reused shared purge helpers for `videos`, `video_embeddings`, `channels`, `instances`, crawl progress and similarity cache rows.
- Integrated ignore status into effective deny-host resolution for serving and updater filtering.

### 31) Channel blocklist system (done)
**Done:** implemented channel-level moderation and immediate filtering in output.

#### **What was implemented:**
- Added channel moderation schema/index in shared moderation module.
- Added CLI `server/db/jobs/channel-moderation-cli.py`:
  - `block --video-url ...` (channel resolve via local DB),
  - `block --channel-id ... --instance ...`,
  - `unblock ...`,
  - `list`.
- Added central filtering by `(channel_id, instance_domain)` in `/api/similar` final response path.
- Added config toggles in `server_config.py`: `DEFAULT_ENABLE_CHANNEL_BLOCKLIST` and `DEFAULT_HIDE_BLOCKED_IN_VIDEO_API`.

### 34) One-command DB sync with JoinPeerTube + ingest missing instances (done)
**Done:** added strict sync mode to updater with host reconciliation and missing-host ingest.

#### **What was implemented:**
- Added `--sync-join-whitelist` mode to `server/db/jobs/updater-worker.py`.
- Added reconciliation flow: `join_hosts -> effective_hosts (minus denylist) -> stale_hosts/new_hosts`.
- Added `--dry-run` planning and `--yes` confirmation for stale-host purge.
- In sync mode, crawler ingest runs only for `new_hosts` via generated `--whitelist-file`.
- Kept lock/systemctl behavior and added detailed sync counters/logging.

### 36) Block A integration regression test (done)
**Done:** added deterministic end-to-end integration regression for Block A on isolated fixture DBs.

#### **What was implemented:**
- Added `server/db/jobs/tests/test-moderation-integration.py`.
- Test uses dedicated temp DB files only (never production DB paths).
- Covers one scenario for `35 -> 32 -> 31 -> 34` and asserts:
  - denylisted/ignored/stale hosts are purged and not present in results,
  - similarity cache rows for purged hosts are removed,
  - serving filter excludes denylisted hosts and blocked channels,
  - rerun idempotency for purge steps.

### 1) Add an explicit candidate scoring stage before the mixer (done)
**Why:** allows comparing candidates from different sources on a common utility scale, not just by layer membership.

**Implementation concept:** after retrieval, each candidate gets a numeric score based on simple features (similarity, freshness, popularity), and then the mixer works with an already scored list.

**Implementation:** add a separate “scoring” step before `mixer`: collect features (similarity, freshness, popularity) in one place, compute a unified `score` and store it in the candidate; update the mixer to work with already scored candidates or use `score` as the basis for local ranking. Add freshness and popularity calculation (from video fields), pass similarity score from `similarity_candidates`, and store the final `score` in the row.

#### **Steps:**
- Create a scoring module (e.g., `server/api/recommendations/scoring.py`) and describe the list of features.
- Pass similarity score into candidates (ANN and cache) so `score` is available in the row.
- In the recommendation generator (before the mixer) compute the final `score` and sort candidates by it.
- Add feature weights (freshness/popularity/similarity) to `server_config.py`.

### 2) Add feature-based scoring instead of simple shuffle (done)
**Why:** increases recommendation relevance and makes the system behavior controllable and explainable.

**Implementation concept:** compute a feature set for each candidate (similarity to likes, freshness, popularity, channel repeat penalty) and aggregate them with a linear formula and weights.

**Implementation:** create a module that computes features (e.g., `recommendations/scoring.py`) and a weights config. While forming candidates, compute: similarity (if present), freshness (by `published_at`), popularity (views/likes), channel_penalty (frequency in current batch). Store `score = Σ(weight_i * feature_i)` in the candidate and use it for ranking.

### 3) Split recommendation logic for Home and Up Next (done)
**Why:** different surfaces require different signals (long-term interests vs current context).

**Implementation concept:** use different scoring weights and different candidate sources depending on request mode (no seed vs seed video).

**Implementation:** in `/api/similar` define two modes: `home` (no seed) and `upnext` (with seed). For each — separate scoring weights and generator sets (e.g., add profiles or separate configs in `RECOMMENDATION_PIPELINE`). In code — pick profile based on presence of seed and pass correct settings into builder/strategy.

#### **Steps:**
- Split profiles `home` and `upnext` in config (different weights/layers).
- In `/api/similar`, determine mode by seed and select the profile.
- Pass the profile into the builder when assembling strategy.
- Update UI/requests if explicit mode is needed.

### 4) Explicit exploration vs exploitation (done)
**Why:** balances “safe” recommendations with discovery of new content.

**Implementation concept:** reserve part of the batch for exploration candidates (new channels, fresh videos) with a separate scoring bonus.

**Implementation:** add a separate explore group (e.g., fresh/new channels), give it a scoring bonus or a quota. In the generator: build explore pool, then mix with exploit per config (ratio). If explore is insufficient — fill with exploit and record a metric.

### 5) Freshness as a continuous function (done)
**Why:** avoid a sharp “fresh vs not fresh” split and improve ranking of new content.

**Implementation concept:** compute freshness_score as a decaying function of publish time and include it in the overall score.

**Implementation:** add freshness-score calculation (e.g., exponential decay from publish time) and include it in `score`. For old videos it should approach 0, for new videos be maximal.

### 6) Limit max videos per author in a batch (done)
**Why:** increase diversity and perceived quality of the feed.

**Implementation concept:** in post-processing, limit the number of videos per channel, filling freed slots with next candidates by score.

**Implementation:** after sorting, build a batch with a per-author limit (e.g., max 2–3 per batch). If limit is exceeded — skip candidate and take next by score. Move the limit to config.

### 7) Layers fresh/explore/exploit + likes as a mechanism (done)
**Problem:** the architecture depended on the `likes` layer, and explore/exploit were post-splits of a shared pool, so stable layer quotas and degradation could not be set.

**Solution:** introduced layers `explore/exploit/fresh` with independent sources; likes are used as a mechanism inside generators. The feed is assembled by ratio with fallback order `explore → exploit → fresh`. For exploit, a fixed `exploit_min` is applied; for explore — similarity range; if no likes, degradations (popular/random/recent) are used.

### 8) Simplify layer config: remove `count`, split gather_ratio and mix_ratio (done)
**Problem:** a single `ratio` was used for both gather and mix, and `count` overrode them, making behavior unclear.

**Solution:** removed `count`; added `gather_ratio` and `mix_ratio` to separately control candidate gathering and final output. Updated config and docs.

### 9) Randomization inside exploit/explore via pool_size (done)
**Problem:** exploit/explore produced almost identical lists with stable sources (cache/ANN, random cache); differences came only from shuffle after scoring.

**Solution:** added `pool_size` for exploit and random selection from the filtered pool; for explore — random selection after filtering by range. Added debug fields and logs.

### 10) Per-instance limit in recommendation output (done)
**Problem:** `post_filters` only used `max_per_author`, so one instance could dominate the output.

**Solution:** added `max_per_instance` in `RECOMMENDATION_PIPELINE.post_filters` and updated docs.

### 11) Add random and popular layers + fallback when no likes (done)
**Problem:** when likes were missing, explore/exploit degraded inside themselves, which mixed layer semantics and made control harder.

**Solution:** added standalone `random` and `popular` layers; explore/exploit are empty without likes, and filling goes via `mixing.order`. `popular` is resorted by similarity when likes exist; `random` can filter by `similarity < explore_min`.

### 12) Documentation: how to build the database (crawler + jobs) (done)
**Problem:** no single instruction for data collection and index building.

**Solution option:** write separate documentation based on crawler and `server/db/jobs` analysis.

#### **Solution details:**
- Crawler data collection variants (modes, sources, limitations).
- Instance filtering via whitelist (JoinPeerTube).
- Embedding generation (what is used, which fields).
- FAISS index building.
- Where to get logs and how to check progress.

### 12) Random cache: per-instance and per-channel limits (done)
**Problem:** random cache returned absolute random without limits, so one instance or channel could dominate.

**Solution:** added parameters `random.max_per_instance` and `random.max_per_author`, applied when building the random pool; if underfilled, pool is topped up with next candidates respecting limits. Docs updated.

### 13) Random cache: optional “filtered cache” mode (done)
**Problem:** `DEFAULT_RANDOM_CACHE_SIZE` defined the size of the raw cache, not the number of already filtered candidates.

**Solution:** added flag `DEFAULT_RANDOM_CACHE_FILTERED_MODE` and limits `DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE/DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR`. In filtered mode the cache is filled to target size with filters applied and logs results.

### 14) Popular: add a soft freshness bonus (done)
**Problem:** popularity only used likes/views, so old videos dominated.

**Solution:** updated popular sorting: likes/views with a soft time-decay bonus by `published_at`.

### 12) Recommendation serving speed optimization (done)
**Problem:** serving can take several seconds (bottlenecks: popular/exploit).

**Done:**
- Popularity materialized in `videos.popularity`, added index `idx_videos_popularity`.
- Formula moved to a shared module, like weight moved to config.
- `/api/video` recomputes popularity only from instance metadata (not local likes).
- Popular pool is sorted by `videos.popularity`, heavy formula removed from query.
- Added job `server/db/jobs/recompute-popularity.py` for one-off recompute after dataset build.

### 15) Guest mode when no likes (auto mode) (done)
**Problem:** when the user has no likes (guest or new), the current profile still contains like-dependent layers.

**Solution:** added profiles `guest_home/guest_upnext` and auto-switching based on absence of likes. Debug includes `profile` flag.

### 16) Centralize “similarity candidates” pipeline (done)
**Problem:** similarity logic (candidate search, filtering, ranking, caching) was spread across modules, so video-page and recommendations used different paths and cache rules were hard to control.

**Solution option:** split into two modules (two files):
1) `similarity_candidates` — build list by similarity (ANN/cache → filters → ranking → ready candidates).
2) `similarity_cache_manager` — cache operations (read/write/refresh policy, cache validity rules).
Mixing layers for home remains a separate module.

#### **Solution details:**
- `similarity_candidates.get_similar_candidates(seed, limit, policy)` — single entry point for similars: source selection (ANN/cache), filters (seed-exclude, author-limit, error-threshold), ranking, result formation.
- `similarity_cache_manager` — unified interface for cache read/write + refresh/validity rules (e.g., full cache, when to recompute).
- `/api/similar` (video-page) gets candidates directly from `similarity_candidates`.
- Recommendations pipeline gets “similarity candidates” from the same module and passes them to the mixer for the home layer.

### 17) Move recommendation assembly out of server.py (done)
- **Problem:** `server/api/server.py` mixed infrastructure (DB, index, HTTP) with recommendation pipeline assembly, making it hard to read, change, and reuse configs.
- **Solution option:** move recommendation assembly into a separate “feed builder” module and keep only the factory call in `server.py`.

#### **Solution details:**
- Create module like `server/api/recommendations/builder.py` with `build_recommendation_strategy(...)` that assembles sources, generators, and `MixingRecommendationStrategy`.
- Move wiring deps for `SimilarFromLikesGenerator` and `FreshVideosGenerator` (likes source, fallback, random cache, fetch_recent_videos, etc.).
- In `server.py` replace assembly block with the new function call, passing configs and dependencies (db, locks, config constants).
- If needed, define a deps structure (dataclass/typed dict) to reduce params and simplify tests.

### 18) Fresh videos: selection and batch distribution (done)
**Task:** update fresh selection logic in recommendations.

#### **Requirements:**
- If the user has no likes:
  - pick randomly from the last DEFAULT_SIMILAR_PER_LIKE videos;
  - distribute fresh videos across the whole batch, not just at the top, so they appear throughout the page.
- If the user has likes:
  - select fresh videos by similarity to the user’s liked videos from a pool of DEFAULT_SIMILAR_PER_LIKE;
  - mix them with the rest of the videos.
- Make pool size parameter an optional global parameter.

### 19) Local likes storage in the browser (no auth) (done)
**Done:** added temporary like storage in the browser (localStorage) and sent likes to the server on recommendation requests.

#### **What was implemented:**
- Client stores liked videos in localStorage.
- On `/api/similar` request the client sends **random 5 likes** (uuid/host).
- Server accepts `likes` and uses them as the primary source (instead of users DB).
- Limit to 50 likes + server-side validation.
- Request body size limit and strict JSON schema (400 on error).
- Flag/module for quick switch back to users DB.
- Documented as a temporary solution until auth.

### 20) Rate limit for API requests (done)
**Done:** added an in-memory rate limiter for API.

#### **What was implemented:**
- Limit N requests per M seconds.
- Config in `server_config.py`.
- 429 response on exceed.
- Trigger logging.

### 21) Refactor server/api/server.py (module decomposition) (done)
**Done:** `server.py` was trimmed and turned into a wiring point.

#### **What was implemented:**
- Handlers moved to `handlers/similar.py`, `handlers/video.py`, `handlers/user_profile.py`.
- Request context moved to `request_context.py`.
- HTTP utilities moved to `http_utils.py`.
- `_handle_similar` split into smaller methods.
- Imports updated, deps assembly kept in `server.py`.

### 22) Handlers polish (contracts, readability, single config source) (done)
**Done:** simplified structure and removed config duplication in handlers.

#### **What was implemented:**
- `_handle_similar` split into small methods.
- Configs are taken from `recommendation_strategy` (no duplication with constants).

### 23) Install and run via Docker (done)
**Done:** added Dockerfile, docker-compose and basic run docs for SQLite.

#### **What was implemented:**
- `Dockerfile.server` for backend.
- `docker-compose.yml` with backend and volume for `server/db`.
- Section in `DEPLOYMENT.md` with run instructions (frontend via external nginx).

### 25) Exploit cache: speed up seed lookup + partial cache handling (done)
**Problem:** exploit spent ~7s in `fetch_seed_embedding` per 5 likes (slow DB lookups); partial cache entries were rejected, so only a small subset of likes produced candidates.

**Done:**
- Rewrote `fetch_seed_embedding` to avoid `OR` conditions (UUID-first, then ID) with host-specific lookups.
- Added indexes for `videos(video_uuid, instance_domain)`, `videos(video_id, instance_domain)`, and `video_embeddings(video_id, instance_domain)`.
- Batched seed fetch for likes with tuple `IN` queries to reduce N DB round-trips.
- Added config `DEFAULT_SIMILARITY_REQUIRE_FULL_CACHE` and wired it to `/api/similar` and exploit sources.

### 26) Duration on similar cards on the video page (done)
**Problem:** there is no video duration displayed on similar-video cards on the video page.

**Solution:** add duration display (as on the home page).

#### **Implementation details:**
- Use the `duration` field already present in `VideoRow` and format it the same way as on the home page.
- Add a duration block on similar-video cards (over the preview) to match the overall style.

### 27) Similar-video timing logs (done)
**Done:** added timing logs for /api/similar on video page and ANN path.

#### **What was implemented:**
- resolve_seed timing.
- ANN search and metadata fetch timing.
- similarity_candidates timing (cache/compute/meta/filter/total).
- related scoring and personalization timings.

### 28) Channels: speed up search and navigation (done)
**Done:** moved channels filtering/sorting/pagination to the server and optimized DB access paths.

#### **What was implemented:**
- `/api/channels` now supports server-side `limit/offset` with default page size and hard cap.
- Added server-side filters: `q`, `instance`, `minFollowers`, `minVideos`, `maxVideos`.
- Added server-side sorting: `sort`, `dir`.
- Response now returns `total` via separate `COUNT(*)` for correct pagination.
- Added channels indexes for sorting/filtering (`followers_count`, `videos_count`, `channel_name`, `instance_domain`).
- Channels UI switched to paged server fetch instead of loading the full channels list into the browser.

### 18) Background worker: incremental data ingest via staging DB (done)
**Done:** implemented background updater workflow through staging DB with merge into prod, plus operational tooling and docs.

#### **What was implemented:**
- Worker/orchestrator pipeline for staged ingest (`server/db/jobs/updater-worker.py`) with lock and resume behavior.
- NEW-only ingest path for instances/channels/videos with proper flags and whitelist-compatible structure.
- Merge flow staging -> prod based on merge rules and safe insert/update strategy.
- Embeddings/ANN/popularity/similarity-cache integration in updater flow and related jobs alignment.
- Installer + systemd integration (service/timer, reinstall path, updater flags in installer).
- Smoke tests and test fixtures for orchestrator (`server/db/jobs/tests/test-orchestrator-smoke.py`, reports, whitelist fixtures).
- Dedicated docs for updater and orchestrator smoke test.

### 29) Full recovery after rollback/lost edits (worker + crawler + jobs + docs) (done)
**Done:** restored lost implementation and reconciled runtime behavior with task-18 contract.

#### **What was restored:**
- Crawler/job/worker command-contract parity (required flags and modes used by updater).
- Restored and revalidated dist/runtime JS paths used by updater flow.
- Recovered DB jobs contract for popularity/similarity/ANN and aligned help/runtime behavior.
- Reconciled installer/systemd behavior with updater execution model.
- Reconciled docs and task tracking with current implementation.
- Re-ran recovery validation via orchestrator smoke flows on test DB and updated artifacts/docs.

### 38) Changelog unread indicator + new/old separator (done)
**Done:** implemented unread changelog badge across pages and visual new/old separation on changelog page.

#### **What was implemented:**
- Added a shared changelog data helper (`client/src/data/changelog.ts`) for fetch/normalize/id/state operations.
- Added a shared nav badge module (`client/src/changelog-badge.ts`) that renders unread dot on all `Changelog` nav links.
- Added localStorage seen-state flow using `changelog_seen_id` (`latest = date|title` from top entry).
- Updated `changelog.html` page rendering:
  - unseen entries are highlighted (`is-new`),
  - separator “Previously seen” is inserted between unseen and seen entries.
- Added acknowledgment flow on successful changelog load (`seen_id` update + badge refresh event), so highlighting clears after refresh.
- Wired badge module on all pages containing changelog nav links.

### 36) Human-readable CHANGELOG file (done)
**Done:** created a public changelog source file based on completed tasks with plain-language summaries and explicit dates.

#### **What was implemented:**
- Added `CHANGELOG.json` as a repository-level changelog data source.
- Backfilled entries from completed work history into user-readable text.
- Kept the changelog contract simple: `date`, `title`, `summary`.
- Stored entries in newest-first order for direct rendering.

### 37) Static changelog page (done)
**Done:** added a static changelog page that fetches updates from GitHub raw and renders them on the client.

#### **What was implemented:**
- Added `client/changelog.html` and changelog page scripts/styles.
- Implemented fetch + validation + rendering pipeline for changelog entries.
- Added loading, empty, and error UI states.
- Added navigation links to `changelog.html` across main static pages.
- Updated Vite build inputs and route rewrite support for `/changelog`.
