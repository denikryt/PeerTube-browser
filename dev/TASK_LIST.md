# Task List (future)

### 1) [M2][F1] Fast response with similars
**Problem:** until the server receives a response from the instance, the client shows an empty page; some instances respond slowly.

**Solution option:** first show similar videos (fast response from local DB), then load the current video metadata when it arrives.

#### **Solution details:**
- When opening VideoPage the client starts two independent processes in parallel: a fast request for similars and a request for metadata of the current video.
- The server responds to the similars request immediately from local cache/DB, without waiting for live instance responses, so the UI is not empty.
- Metadata updates are done via a separate request to the instance (server-side or client-side), then saved to the DB and the UI updates.

### 2) [M2][F1] Similars on scroll
**Problem:** only 8 videos are shown in similar videos; there is a need to see more.

**Solution option:** remove the separate "similar videos" page and load similars directly on the video page, like on the home page: the server returns N similars and the client renders them progressively as you scroll.

#### **Solution details:**
- The server for video-page returns a full batch of similars at once (for example, `BATCH_SIZE = 48`) in a single response so the client does not make frequent requests.
- The client keeps the batch in memory and shows it in chunks while scrolling, adding new cards as the user nears the bottom.

### 3) [M2][F1] Video page metadata completeness: show tags/category + refresh mutable fields
**Problem:** video page does not show all useful metadata (especially tags and category), and metadata refresh on video request currently focuses mostly on dynamic stats (views/likes) while other fields may also change.

**Solution option:** render tags and category on the video page, and extend per-request metadata refresh to update mutable video fields from the source instance.

#### **Solution details:**
- **UI changes (video page):**
  - Add visible blocks for:
    - `category` (or category label),
    - `tags` (list/chips, with empty-state if none).
  - Keep layout compact and consistent with existing metadata area.
- **API/server refresh on video request:**
  - Keep dynamic stats refresh (`views`, `likes`) as-is.
  - Also refresh mutable metadata fields from instance response:
    - `title`,
    - `description`,
    - `tags`,
    - `category`,
    - optional: `language`, `nsfw`, `duration`, `thumbnail_url` if returned.
  - Update local DB in one write path with clear mapping rules.
- **Data model consistency:**
  - Ensure tags/category are stored in DB schema used by `/api/video`.
  - If category is numeric in source API, map to display label consistently.
- **Robustness:**
  - **Current behavior (already implemented in `server/api/handlers/video.py`)**:
    - Instance fetch uses `urlopen(..., timeout=8)` and catches `HTTPError`, `URLError`, `TimeoutError`.
    - On such errors (or non-200), instance JSON returns `None`, and dynamic payload becomes empty/partial.
    - Response to client is built with DB fallback field-by-field (`title/description/views/likes/dislikes/tags/category/nsfw`), so UI still gets data from local DB.
    - DB update (`UPDATE videos/channels`) runs only when dynamic payload is non-empty; on instance failure no overwrite is performed.
    - Instance error reset (`instances.last_error = NULL`) also happens only on successful dynamic refresh path.
  - Keep this fallback logic and document it explicitly in implementation notes/tests.
- **Validation / tests:**
  - Manual test: open video page, verify tags/category render.
  - Integration test: source metadata change is reflected after next `/api/video` request.
  - DB persistence test on a test database:
    - use a test DB that mirrors production schema (same tables/columns/indexes for `videos/channels/instances`);
    - run `/api/video` requests against known fixtures (success and instance-fail cases);
    - assert saved values in DB after request (`title/description/views/likes/dislikes/tags_json/category/nsfw/last_checked_at`);
    - assert no overwrite happens on failed instance fetch path.
  - Regression test: stats refresh still works and does not wipe existing tags/category on partial responses.

### 4) [M2][F1] Comments under the video
**Problem:** comments are not displayed under the video.

**Solution option:** the server or client requests the instance to get comments and render them under the video on the page.

#### **Solution details:**
- Add comment fetching via instance API (or a server proxy) and render them under the video description block.
- UX: show a placeholder/loader, support pagination and limits (in batches) to avoid overloading the page.
- Remove the comment input field (view-only).
- First verify on a specific video which request is needed to fetch comments; use the response structure for client rendering.

### 8) [M2][F1] Tailwind CSS (optional)
**Problem:** styles are fragmented and hard to maintain.

**Solution option:** evaluate Tailwind and adopt if needed.

#### **Solution details:**
- Start with new blocks, gradually replace repeating styles.

### 8b) [M3][F2] Switchable feed modes: recommendations / hot / recent / random / popular
**Problem:** right now there are only recommendations and random; there are no quick modes like “only recent / only hot / only popular.”

**Solution option:** add feed modes on the home page and a mode switch.

#### **Solution details:**
- UI: mode switcher (recommendations, hot, recent, random, popular).
- API: `mode` parameter (or separate endpoints) to fetch the corresponding feed.
- Hot: separate formula (e.g., likes/views with age decay).
- Recent: only fresh items (by `published_at`).
- Popular: top by likes/views.
- Random: random feed.

### 8c) [M3][F6] About page outbound links: proper click tracking
**Problem:** clicks on external links from `about.html` are currently visible only indirectly in nginx logs and are noisy/inaccurate because bots and malformed requests are mixed in.

**Solution option:** add explicit client event tracking for outbound link clicks on the About page and store events in API DB.

#### **Solution details:**
- **Client instrumentation**:
  - Add `data-track-id` for each outbound link in `client/frontend/about.html` (e.g., `about_patreon`, `about_github`, `about_youtube`).
  - Add one delegated click handler for `a[data-track-id]`.
  - Send event with `navigator.sendBeacon()` to `/api/analytics/outbound-click` (fallback to `fetch(..., { keepalive: true })` if needed).
  - Event payload: `track_id`, `href`, `page_path`, `timestamp`.
- **API endpoint**:
  - Add `POST /api/analytics/outbound-click`.
  - Validate payload (`track_id`, `href`, allowlist of known IDs/hosts).
  - Write event row to SQLite table (append-only).
- **DB schema**:
  - New table `outbound_click_events` with fields:
    - `id INTEGER PRIMARY KEY`
    - `track_id TEXT NOT NULL`
    - `href TEXT NOT NULL`
    - `page_path TEXT NOT NULL`
    - `created_at INTEGER NOT NULL`
    - optional diagnostics: `ip_hash`, `user_agent`, `referer`
  - Add index on `(track_id, created_at)`.
- **Reporting**:
  - Add simple aggregated query/endpoint for counts by `track_id` (daily and total).
  - Keep raw events for audit/debug.
- **Abuse/noise control**:
  - Rate-limit endpoint per IP.
  - Reject unknown `track_id` values.
  - Keep privacy-safe storage (no raw IP if not needed; hash or omit).
- **Validation / tests**:
  - Client test: click dispatch sends correct payload.
  - API test: valid event is stored, invalid event is rejected.
  - E2E smoke test: clicking About links increases counter in DB.

### 9b) [M2][F1] Remove a single like (UI + API)
**Problem:** currently you can only reset all likes, but cannot remove a single one.

**Solution option:** let the user remove a like from the list (in the My likes modal) and/or via dislike on the video page.

#### **Solution details:**
- UI: remove button on like card in the modal.
- Video page: dislike as “remove like” (if the video was liked).
- Client: remove entry from localStorage (uuid/host).
- Server: a dedicated endpoint (or extend `/user-profile/reset`) to delete a single like from the users DB, if a DB is used.

### 9) [M2][F1] Collapsible video description
**Problem:** long video descriptions take up too much space.

**Solution option:** implement collapse/expand for the description.

#### **Solution details:**
- Limit description height and show a “Show more/Collapse” button.
- On click, toggle expanded/collapsed state and keep it in the UI.

### 10) [M3][F2] Video search page
**Problem:** there is no search page and no server-side logic for video search.

**Solution option:** API search (FTS/LIKE) and a simple UI for results.

#### **Solution details:**
- Define request/response format: `GET /api/search/videos?q=...&page=...&limit=...&sort=...`.
- Server: add a video search endpoint (SQLite FTS5, fallback to LIKE).

### 11) [M8][F5] Docstrings for all modules and functions
**Problem:** descriptions are missing in some places, making it harder to quickly understand module and function purpose.

**Solution option:** add short docstring descriptions to all modules and functions where they are missing.

#### **Solution details:**
- Modules: 2–5 lines, “what the module does / main responsibilities.”
- Functions/classes: 1–2 lines, “what it does / what it returns.”
- Avoid noise — only where it is non-obvious.

### 12a) [M3][F2] Popular: weighted random by similarity
**Problem:** when likes exist, popular is sorted by similarity but then a random sample is taken from the whole pool, so the sorting almost does not affect the result.

**Solution option:** replace random.sample with weighted random using similarity as the weight.

#### **Solution details:**
- After sorting/scoring, compute weights (e.g., `weight = max(similarity, 0.0)` or `weight = similarity ** alpha`).
- Pick candidates via weighted sampling without replacement (or with a small epsilon for diversity).
- Add config parameter `popular.weighted_random_alpha` (0 = disabled).
- For empty/zero weights fallback to normal random.

### 15) [M4][F3] Crawler mode: start from one instance and its subscriptions
**Problem:** there is no crawler mode that starts from one instance and walks its federated subscriptions.

**Solution option:** add a mode where a seed instance domain is provided, then the crawler:
1) finds all instances it follows,
2) collects all channels from that instance and its federated instances,
3) collects all videos from those channels.

#### **Solution details:**
- CLI parameter for the seed domain (e.g., `--seed-instance`).
- Step 1: fetch subscriptions/follows of the instance and build a list of instances.
- Step 2: iterate through channels of each instance and collect their metadata.
- Step 3: iterate through videos of channels and save them to the DB.
- Note: this mode belongs to the instance crawler; its behavior should be aligned with existing crawler flags.

### 16) [M8][F5] Update recommendation description (RECOMMENDATIONS_OVERVIEW)
**Problem:** `RECOMMENDATIONS_OVERVIEW.md` does not match the current recommendation logic.

**Solution option:** rewrite the document and describe the whole generation pipeline.

#### **Solution details:**
- Describe data preparation stages (embeddings, cache, index).
- Describe candidate generation and layer mixing.
- Describe filters, deduplication, and mixing rules.
- Describe what the client receives and how the frontend uses it.

### 16l) [M7][F4] Background refresh of random cache
**Problem:** random cache is rebuilt only on server start and/or on a refresh flag. We need a background mechanism with safe updates without read conflicts.

**Solution option:** periodic job that rebuilds the cache into a separate file and atomically swaps the active cache.

#### **Solution details:**
- Config: parameter `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` (0 = disabled).
- Background thread/timer in the server that rebuilds every N minutes.
- Rebuild into `random-cache.tmp.db`, then atomic swap (rename) and safe connection re-open under `random_cache_lock`.
- Logs/metrics: build time, size, number of valid candidates, short-fill reasons.
- Consider SQLite: use WAL/readonly connection for reading, update only under a lock for replacement.

### 33) [M3][F2] Video page similars: diversity on refresh + larger candidate coverage
**Problem:** on video page (`/api/similar` for upnext), refresh often returns the same small set; for some videos only 1-5 similars are found. We need stable diversity (with likes and without likes) and larger similar pools.

**Solution option:** expand ANN candidate recall (`search_limit`, `top-k`, `nprobe`), add deterministic shuffle/window sampling for final output, and add fallback broadening when candidate count is low.

#### **Solution details:**
- **Config-driven ANN for video-page similars**:
  - Add/verify dedicated config defaults for upnext retrieval (separate from home feed where needed):
    - `SIMILAR_VIDEO_SEARCH_LIMIT`
    - `SIMILAR_VIDEO_TOP_K`
    - `SIMILAR_VIDEO_NPROBE`
  - Keep these in `server_config` and expose in logs on startup.
- **Low-candidate fallback strategy**:
  - If final unique candidates `< target_min_pool`:
    - increase ANN depth in steps (`nprobe` up to max),
    - increase `search_limit` in steps (bounded),
    - optionally relax min similarity threshold for tail fill.
  - Stop when pool is enough or hard caps reached.
- **Diversity per refresh (no repeated top-8)**:
  - Do not always take first N after sorting.
  - Use one of:
    - windowed sampling from top-M (e.g., random from top-200),
    - weighted random by similarity (without replacement),
    - deterministic daily seed + request nonce for controlled variation.
  - Keep quality by preserving similarity-weighted preference.
- **Behavior with likes vs without likes**:
  - `likes=yes`: mix source-video similars with profile-aware candidates (but keep source-video relevance dominant).
  - `likes=no`: still diversify output from source-video pool (no profile dependency required).
  - Ensure both paths can produce varied output on refresh.
- **Dedup/quality guarantees**:
  - Keep strict dedup by `(video_uuid, instance_domain)`.
  - Keep existing blocked-instance/channel filters.
  - Enforce minimum relevance floor before fallback tail.
- **Observability**:
  - Add logs per upnext request:
    - initial pool size,
    - fallback steps triggered,
    - final pool size,
    - sampling mode used,
    - number of unique items returned.
- **Validation / tests**:
- Repeated refresh test (same video, 10 requests): overlap ratio should be below threshold while relevance stays acceptable.
- Low-similarity video test: verify fallback expands pool above minimum.
- Compare behavior for `likes=yes` and `likes=no`.

### 37) [M2][F7] Stable ANN IDs: replace `video_embeddings.rowid` with deterministic `video_id+host -> int64`
**Problem:** ANN currently uses SQLite `video_embeddings.rowid` as FAISS id source. This is tightly coupled to physical row layout and becomes operationally fragile after purge/merge/rebuild cycles. We need stable ANN ids derived from logical video identity.

**Solution option:** introduce deterministic ANN id (`ann_id`) from canonical key `(video_id, instance_domain)` and migrate ANN/search/precompute pipelines to use it end-to-end.

#### **Solution details:**
- **ID contract + helper module:**
  - Add canonical key builder (`video_id + "::" + normalized instance_domain`).
  - Add deterministic `int64` generator (stable hash) and collision policy.
  - Expose one source of truth helper for all writers/readers.
- **Schema + migration:**
  - Add `ann_id` to `video_embeddings` (or dedicated mapping table) with unique index.
  - Backfill existing rows and validate no collisions.
  - Update schema migration jobs to guarantee `ann_id` exists before ANN build.
- **Embedding write paths:**
  - Ensure every insert/update into `video_embeddings` writes deterministic `ann_id`.
  - Keep behavior idempotent for re-runs and replace merges.
- **ANN build path migration:**
  - `build-ann-index.py`: read `ann_id` instead of `rowid`; `add_with_ids(..., ann_id)`.
  - Update index metadata (`id_source`) to the new contract.
- **Runtime search path migration:**
  - `data/ann.py`: ANN search returns `ann_id` list, not rowids.
  - `data/embeddings.py`: seed resolves `exclude_ann_id` instead of `exclude_rowid`.
  - `data/metadata.py`: add fetch-by-`ann_id` path and use it in ANN response handlers.
  - `handlers/similar.py`: vector search path should pass `exclude_ann_id` and resolve metadata by `ann_id`.
- **Similarity precompute migration:**
  - `precompute-similar-ann.py`: switch internal ANN ids and metadata lookup from `rowid` to `ann_id`.
  - Incremental selection should remain logical-key based (`video_id`, `instance_domain`), not physical row ids.
- **Updater/ops integration:**
  - Ensure updater sequence keeps ANN id consistency before ANN rebuild/precompute stages.
  - Update docs/runbooks to include ANN id migration/backfill step for existing DBs.
- **Validation / tests:**
  - Unit test: deterministic id generation and collision guard.
  - Migration test: backfill creates stable ids and unique constraint holds.
  - Integration test: ANN response correctness after host purge (no rowid coupling).
  - Smoke test: updater full cycle (merge -> ANN build -> precompute) with new id source.

#### **Affected areas/files (expected):**
- ANN runtime/search: `server/data/ann.py`, `server/api/handlers/similar.py`, `server/data/embeddings.py`, `server/data/metadata.py`.
- ANN build/precompute: `server/db/jobs/build-ann-index.py`, `server/db/jobs/precompute-similar-ann.py`.
- DB schema/migration/ingest: `server/db/jobs/migrate-whitelist.py`, `server/db/jobs/build-video-embeddings.py`, `server/db/jobs/sync-whitelist.py`, merge/updater flow.
- Ops/docs/tests: `server/db/jobs/updater-worker.py`, updater docs, ANN/smoke tests.

### 38) [M7][F4] Request lifecycle logs: request-start first + shared request_id across server logs
**Problem:** current logs are hard to correlate because access logs are emitted on response write, while business logs (`[similar-server]`, `[recommendations]`) are produced during processing and can interleave across threads.

**Solution option:** introduce a per-request lifecycle log (`start` -> work logs -> `end`) and one shared `request_id` propagated through handler and recommendation logs.

#### **Solution details:**
- Keep a two-log model (do not merge into one physical file):
  - nginx access log for client/network view (`ip`, URL, status, timing),
  - app/service log for internal processing (`similar-server`, `recommendations`, timing).
- Correlation contract:
  - one shared `request_id` must appear in both logs for the same request;
  - nginx should forward `X-Request-ID` (or generate it when missing), app should read and reuse it.
- Add a request-scoped context value (`request_id`) at the start of every API request (`do_GET`/`do_POST`) before business logic.
- Emit `request-start` log first with `request_id`, client IP, method, full URL, and optional user-agent.
- Reuse the same `request_id` in all downstream request-path logs (`[similar-server]`, `[recommendations]`, handler timing logs).
- Emit `request-end` log with `request_id`, status, duration_ms; `bytes` in app-log is optional.
- Treat response byte size as nginx access-log responsibility (source of truth for transferred bytes).
- Remove ad-hoc per-handler random id generation where it conflicts with shared request context.
- Keep compatibility with threaded serving (ordering guaranteed per request, not globally).
- Validation:
  - smoke test for `/api/similar`, `/api/video`, `/api/health` to verify `start -> ... -> end` with same `request_id`;
  - regression test to ensure no request is logged without `request_id`;
  - manual verification runbook that compares one request in both logs by `request_id`.

### 39) [M7][F4] Random cache refresh worker without startup downtime (extends 16l runtime behavior)
**Problem:** rebuilding random cache during startup can delay readiness and create a visible unavailable window after restart.

**Solution option:** keep serving from existing cache immediately, and rebuild cache in a background worker with atomic swap.

#### **Solution details:**
- Keep startup non-blocking:
  - open existing `random-cache.db` and start API listening first;
  - if cache is missing/invalid, use safe DB fallback until first successful build.
- Add background worker/timer to rebuild into `random-cache.tmp.db`.
- Perform atomic cache swap and safe connection reopen under `random_cache_lock`.
- Add backoff/retry policy for failed refreshes; do not block request path.
- Add metrics logs: build duration, scanned rows, final size, short-fill reasons, swap success/failure.
- Config:
  - refresh interval (minutes),
  - startup refresh mode (`off` / `async`),
  - optional max build runtime guard.
- Validation:
  - startup readiness test confirms `/api/health` responds before cache rebuild completes;
  - concurrent read test during swap shows no request failures.

### 40) [M7][F4] Zero-downtime server deploy: parallel port startup + automatic nginx switch
**Problem:** in-place restart on one port causes temporary downtime during server initialization/warm-up.

**Solution option:** implement blue/green style deploy for the API: start a new instance on a second port, health-check it, switch nginx upstream, then drain/stop old instance.

#### **Solution details:**
- Add one-command deploy script (example name: `deploy-bluegreen.sh`) that performs full switch automatically.
- Add explicit blue/green mode flag in the script (example: `--blue-green`).
- Use a fixed blue/green port pair only: `7070` and `7071` (no random/free-port selection and no custom port list flag).
- Move API service to systemd instance template (for example `peertube-browser@.service`) so two instances can run in parallel:
  - `peertube-browser@7070`,
  - `peertube-browser@7071`.
- Deploy flow in script:
  1) detect which one of `7070/7071` is currently active and choose the other one as target,
  2) start new systemd instance on inactive port,
  3) run readiness checks against new port (`/api/health`, optional warm-up wait),
  4) switch nginx upstream to the new port (single source file/snippet for upstream target),
  5) run `nginx -t` and reload nginx,
  6) stop old systemd instance after successful switch.
- Add automatic rollback:
  - if readiness check fails, stop new instance and keep old port active;
  - if nginx validation/reload fails, restore previous upstream target and keep old instance.
- Keep deploy idempotent and lock-protected (avoid concurrent deploy races).
- Add operation logs: deploy id, old/new port, switch timestamp, health-check result, rollback reason.
- Validation:
  - repeated deploy smoke tests with no 5xx spikes in nginx access log;
  - forced-failure test verifies rollback path;
  - verify one-command run requires no manual `systemctl`/nginx edits.

### 41) [M7][F4] Timestamped request logs (explicit date/time)
**Problem:** request timing analysis is harder when logs rely only on journal envelope time or inconsistent message formatting.

**Solution option:** include explicit timestamp in application log format and in request lifecycle logs.

#### **Solution details:**
- Configure logging format with explicit timestamp (recommended: ISO-8601 with milliseconds, UTC).
- Ensure both request lifecycle logs and internal server logs include the same timestamp format.
- Add optional config for structured log output (plain text default, JSON optional).
- Keep compatibility with journald (no duplicate parsing assumptions).
- Validation:
  - sample log lines include full date/time and timezone marker;
  - ordering checks across request-start/work/request-end use application timestamp fields.

### 43) [M7][F4] Static page visit logs for About and informational pages
**Problem:** visits to static informational pages (including `about`) are currently served as static files by nginx, so these page visits are not visible in app/service request logs.

**Solution option:** add a dedicated logging path for static page visits and keep correlation with request tracing where possible.

#### **Solution details:**
- Add dedicated nginx logging for informational static page routes:
  - include client IP, method, URL, status, response time, user-agent;
  - keep this in a separate log stream or with explicit marker field.
- Preserve/propagate `X-Request-ID` in nginx logs for those routes when available.
- Add a simple runbook to compare static page visits from nginx logs and API request traces from app logs.
- Optional (if needed): add client-side pageview beacon endpoint for cleaner human-intent tracking and bot/noise filtering.
- Validation:
  - visiting informational static pages produces entries with expected fields in nginx logs;
  - sample correlation by request id/time window works against app-side traces.

### 44) [M7][F4] Similarity cache shadow build + atomic swap without long API downtime
**Problem:** updater currently keeps API service stopped until `precompute-similar-ann.py` finishes. Similarity precompute can be very long, causing unnecessary API downtime.

**Solution option:** build similarity cache in a shadow DB while API is already running, then perform a fast atomic cutover.

#### **Solution details:**
- **Updater sequence change:**
  - keep service stop/start around write-conflict-critical stages only (`merge` + ANN rebuild),
  - start API service before similarity precompute stage.
- **Shadow cache build path:**
  - create `similarity-cache.next.db` from current active `similarity-cache.db` (preserve incremental baseline),
  - run `precompute-similar-ann.py --incremental` against the shadow file, not active file.
- **Atomic cutover:**
  - on success, atomically replace active cache file (`os.replace`),
  - keep rollback backup (`similarity-cache.prev.db`) for one-step restore.
- **Runtime handoff:**
  - add safe similarity DB reconnect/reopen path in API process under `similarity_db_lock` (signal or admin hook),
  - fallback: short controlled API restart only for reconnect if hot-reload is unavailable.
- **Safety/rollback:**
  - if shadow build fails, keep active cache untouched,
  - if swap/reopen fails, restore previous active cache and keep service healthy.
- **Observability:**
  - log shadow build duration, processed sources, swap duration, reopen result, rollback reason.
- **Validation / tests:**
  - integration test: API stays available during similarity precompute window,
  - concurrency test: no read errors during swap/reopen,
  - rollback test: forced swap failure restores previous cache and keeps `/api/health` green.

### 56) [M7][F4] Similarity precompute: rewrite only existing cache sources
**Problem:** updater currently runs similarity precompute over all embeddings with full cache recreation, which is heavy and can keep service downtime longer than needed.

**Solution option:** add a mode that recomputes similarity only for source videos already present in `similarity_sources`, and rewrites only those cache entries.

#### **Solution details:**
- Add dedicated CLI mode in `precompute-similar-ann.py`:
  - source set = intersection of current embeddings and existing `similarity_sources` in output cache DB;
  - process only this set instead of all embeddings.
- For each processed source, keep current rewrite semantics:
  - upsert `similarity_sources.computed_at`,
  - delete old `similarity_items` for this source,
  - insert fresh top-k rows.
- Keep non-processed source entries untouched (no global cache wipe).
- Updater integration:
  - use the new mode for updater precompute stage,
  - stop passing full-reset behavior intended for complete rebuilds.
- Validation / tests:
  - source-count check: processed set equals “already cached + still present in embeddings”;
  - data check: processed sources are rewritten, untouched sources remain unchanged;
  - runtime check: updater stage time drops compared to full-cache rebuild baseline.

### 70) [M1][F4] Workflow CLI entrypoint and command routing
**Problem:** workflow operations are still tied to manual file edits and ad-hoc command handling.

**Solution option:** add one `dev/workflow` entrypoint with stable routing for feature/task/confirm/validate command groups.

#### **Concrete steps:**
1. Create `dev/workflow` CLI entrypoint with argument parsing and subcommand dispatch.
2. Implement command router modules for `feature`, `task`, `confirm`, and `validate`.
3. Add smoke checks that verify command resolution and non-zero exit code on invalid arguments.

### 71) [M1][F4] Feature base commands: create/plan/approve/execution-plan
**Problem:** feature lifecycle commands are not unified under one executable contract.

**Solution option:** implement base feature workflow commands required before sync/materialize.

#### **Concrete steps:**
1. Implement `feature create` with feature ID/milestone validation and tracker update wiring.
2. Implement `feature plan-init`, `feature plan-lint`, and `feature approve` with plan/gate checks.
3. Implement `feature execution-plan` that returns ordered pending tasks for one feature subtree.

### 72) [M1][F4] Tracking sync command for DEV_MAP/TASK_LIST/PIPELINE
**Problem:** local decomposition sync across trackers is manual and error-prone.

**Solution option:** implement `feature sync --write` for one-change-set updates of all tracking files.

#### **Concrete steps:**
1. Implement sync input model for manual decomposition delta (`Issue -> Task`, markers, pipeline order/overlaps/outcome).
2. Implement write path that updates `dev/map/DEV_MAP.json`, `dev/TASK_LIST.md`, and `dev/TASK_EXECUTION_PIPELINE.md` together.
3. Add guard that blocks write when feature status is not `Approved`.

### 73) [M1][F4] Task ID allocation and validation scopes
**Problem:** ID allocation and cross-tracker consistency checks are not enforced by automation.

**Solution option:** add deterministic `task_count` allocation and repository/tracking validators.

#### **Concrete steps:**
1. Implement task ID allocation strictly via `task_count` (`new_id = task_count + 1`) and persist in the same write run.
2. Implement ownership validation for `[M*][F*]`/`[M*][SI*]` markers against `DEV_MAP` parent chains.
3. Implement `validate --scope tracking|repo` checks for sync consistency and gate failures.

