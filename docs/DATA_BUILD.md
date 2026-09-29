# Data Build (Crawler + Jobs)

This document explains how to build the local SQLite dataset plus derived
artifacts (embeddings, ANN index, caches) used by the API.

All paths below are relative to the repository root.

## Outputs
- `engine/crawler/data/crawl.db` raw crawl database.
- `engine/server/db/whitelist.db` filtered dataset used by the API.
- `engine/server/db/whitelist-video-embeddings.faiss` and `engine/server/db/whitelist-video-embeddings.faiss.json` ANN index + metadata.
- `engine/server/db/similarity-cache.db` precomputed similar cache (optional).
- `engine/server/db/random-cache.db` random index-id cache (optional).

## Prerequisites
- Node.js + npm for the crawler (`engine/crawler/package.json`).
- Python 3.10+ for jobs (`engine/server/requirements.txt`).
- Optional CUDA if you plan to run embeddings with `--gpu`.

## Automatic background updater
You can run the same build/update flow automatically with the updater worker:

- Worker entrypoint: `engine/server/db/jobs/updater-worker.py`
- Internal updater modules: `engine/server/db/jobs/updater/`
- It runs: instances/channels -> missing video counts -> video metadata to staging -> embeddings -> merge to prod -> popularity -> prepared Discovery -> index-id sync -> Search rebuild -> ANN rebuild -> random cache rebuild -> similarity precompute.
- Systemd installation: `install-service.sh --with-updater-timer`
- Timer runs daily (`OnUnitInactiveSec=1d`).
- Optional `--host-pipeline` mode overlaps different hosts and reselects queued
  work after every stage with global priority `channel lists -> NULL counts ->
  videos`; in-flight work is allowed to finish.

Detailed behavior, flags, lock/resume logic, and systemd notes are documented in:

- `engine/server/db/jobs/docs/UPDATER_WORKER.md`
- `docs/UPDATER_COMPATIBILITY.md`

## 1) Crawl data

### Build crawler
```bash
cd engine/crawler
npm install
npm run build
```

Crawler DB module tests are available after installing crawler dependencies:

```bash
cd engine/crawler
npm run test:db
```

These tests verify the TypeScript crawler stores with temporary SQLite files. They do not run PeerTube network crawls.

### Instance discovery
Default source is the JoinPeerTube whitelist JSON.
```bash
cd engine/crawler
npm run crawl:instances
```

Useful flags:
- `--whitelist-url <url>` change the source list.
- `--expand-beyond-whitelist` follow federation graph beyond the whitelist.
- `--graph` store follower/following edges between instances.
- `--resume` reuse progress stored in `instance_crawl_progress`.
- `--concurrency`, `--timeout`, `--max-retries`, `--max-errors` control crawl speed and retry policy.

Data source and limits:
- Uses `GET /api/v1/server/following` and `GET /api/v1/server/followers`.
- Page size is fixed at 50.
- Only public instance metadata is collected.

### Instance health checks
```bash
cd engine/crawler
npm run crawl:instances:health
```

Useful flags:
- `--errors-only` check only instances with `health_status=error`.
- `--min-age-days`, `--min-age-min`, `--min-age-sec` limit checks by last health timestamp.
- `--host <host>` check a single instance.

Data source and limits:
- Uses `GET /api/v1/video-channels?start=0&count=1`.

### Channel crawl
```bash
cd engine/crawler
npm run crawl:channels
```

Useful flags:
- `--check-health` only checks per-channel health and writes errors.
- `--resume` reuse progress stored in `channel_crawl_progress`.

Data source and limits:
- Uses `GET /api/v1/video-channels?start=<offset>&count=50`.
- Only channels hosted on the instance itself are stored.
- `--new-channels` leaves existing metadata unchanged but refreshes the listed
  `videos_count`; an omitted count becomes `NULL` for the following count stage.

### Channel video counts
```bash
cd engine/crawler
npm run crawl:channels:videos-count
```

The updater runs this after channel discovery. Counts already supplied by
`GET /api/v1/video-channels` are kept; only rows with `videos_count IS NULL`
need a per-channel request. Successful counts are committed immediately, so
`--resume` skips them after an interruption. Recorded errors are left for an
explicit `--errors` repair pass.

Useful flags:
- `--resume` skips channels with existing counts or errors.
- `--errors` processes only channels with recorded errors.

### Video crawl
```bash
cd engine/crawler
npm run crawl:videos
```

Useful flags:
- `--new-videos` skip videos that already exist in `videos` (by id + instance).
- `--stop-after-full-pages <N>` stop after N pages that contain only existing videos.
- `--resume` reuse progress stored in `video_crawl_progress`.
- `--errors` process only channels with recorded errors.

Data source and limits:
- Uses `GET /api/v1/video-channels/<channel>/videos?start=<offset>&count=50`.
- Selects only channels with `videos_count > 0`; zero-count and unresolved
  channels do not cause metadata requests.
- Each successful page stores its next offset in `video_crawl_progress`, so
  `--resume` continues an interrupted channel from that page. Returned IDs are
  filtered against staging and production before insertion.
- Default host concurrency is limited to avoid rate limiting.

### Tags and comments enrichment
These are slower because they hit per-video endpoints.
```bash
cd engine/crawler
npm run crawl:videos:tags
npm run crawl:videos:comments
```

Useful flags:
- `--host-delay <ms>` throttles requests per host (default 200ms).
- `--concurrency` limits number of hosts processed in parallel.

Data source and limits:
- Uses `GET /api/v1/videos/<uuid>` for tags and comment counts.

## 2) Filter to JoinPeerTube whitelist
This step builds the API dataset in `engine/server/db/whitelist.db`.

```bash
python3 engine/server/db/jobs/sync-whitelist.py \
  --db engine/crawler/data/crawl.db \
  --output-db engine/server/db/whitelist.db
```

Notes:
- Default whitelist URL is JoinPeerTube and can be overridden with `--url`.
- `--mode include` keeps only whitelisted hosts (default).
- `--mode exclude` keeps hosts not in the whitelist.
- If the source DB schema has `video_embeddings`, they are copied into whitelist.db.
- A successful full sync applies current Engine read indexes and rebuilds prepared
  `video_tags` plus the singleton facet snapshot before returning.

If the whitelist DB schema is outdated, migrate it:
```bash
python3 engine/server/db/jobs/migrate-whitelist.py --db engine/server/db/whitelist.db
```

Schema ownership is documented in `docs/SCHEMA_OWNERSHIP.md`.


### Metadata-v1 ingestion and historical backfill

Normal `crawl:videos` ingestion now persists detail metadata needed by the browser and by a future ActivityPub adapter: language/category/licence identifiers, source timestamps, sensitive summary, live flags, support/aspect ratio, account identity, and canonical thumbnail dimensions. Fresh rows also persist detail tags.

Historical rows must be migrated before the metadata maintenance command is used:

```bash
python3 engine/server/db/jobs/migrate-whitelist.py --db engine/server/db/whitelist.db
cd engine/crawler
npm run crawl:videos:metadata -- --db ../server/db/whitelist.db
```

The metadata command is a data-only operation. It validates the current metadata schema read-only and does not run crawler schema migrations against `whitelist.db`. `--update-metadata` explicitly revisits rows that already completed the current metadata version.

When this command targets the production `whitelist.db`, keep Engine serving stopped through the maintenance operation and rebuild prepared Discovery before serving resumes:

```bash
python3 engine/server/db/jobs/rebuild-video-discovery-data.py --db engine/server/db/whitelist.db
```

This is required because metadata maintenance can change prepared-facet source fields such as language/category and can mark rows invalid after permanent metadata errors.


### Thumbnail candidate migration and historical backfill

The runtime can serve historical rows immediately after the additive schema migration: SQL `thumbnail_candidates_json IS NULL` deliberately falls back to the stored singular `thumbnail_url`. Do not keep Engine offline for the full historical network backfill.

Mandatory rollout barrier:

```text
1. stop Engine/updater writers
2. deploy the new code
3. migrate-whitelist.py on production whitelist.db
4. verify thumbnail_candidates_json exists and legacy SQL-NULL rows still expose thumbnail_url
5. resume normal serving
```

Backfill candidate state separately in bounded maintenance windows. Use explicit non-overlapping host batches; `--resume` is the row-level SQL-NULL selector, while `--max-instances` is only an optional safety cap inside a batch:

```bash
cd engine/crawler
npm run crawl:videos:thumbnails -- \
  --db ../server/db/whitelist.db \
  --resume \
  --hosts-file /path/to/thumbnail-batch-01.txt
```

Successful modern detail writes `[]` or an ordered JSON array of `{url,width,height}` candidate objects. Detail request failure and successful legacy/non-array detail shapes leave SQL `NULL` for retry; definitive 404/410 failures mark the video invalid and other failures record the existing generic video error state. This thumbnail-only maintenance does not require Discovery/Search/embedding/ANN/random/similarity rebuilds because none of those artifacts depend on thumbnail state. Initial production use should keep Engine stopped during each bounded write window unless concurrent-writer behavior is separately validated.

Existing embedding-source fields are protected during ordinary repeat crawl and metadata backfill: `title`, `description`, `tags_json`, `category`, and `channel_name`. Intentionally changing any of those fields after embeddings exist requires a full embedding/artifact rebuild. The legacy tags maintenance commands remain embedding-affecting for existing rows. `comments_count` is dynamic metadata and is **not** an embedding input.

### Embedding recipe migration barrier

The semantic embedding recipe is `title + description + tags + category + channel name`; it no longer includes `comments_count`. Existing production embeddings created by the old recipe must be rebuilt as one isolated maintenance operation. Do not allow updater merges or Engine serving while the production embedding/ANN/similarity set is partially rebuilt.

Operational barrier:

```text
1. disable/prevent updater-worker/timer and verify no updater run is active
2. stop peertube-browser Engine
3. deploy/activate the code with the new embedding recipe
4. build-video-embeddings.py --force (using the deployment's normal CPU/GPU flags)
5. sync-video-index-ids.py
6. build-ann-index.py (using the deployment's normal output/CPU/GPU flags)
7. precompute-similar-ann.py --reset (using the deployment's normal paths/flags)
8. validate DB integrity/counts, stable IDs, FAISS metadata/ntotal, similarity cache
9. start peertube-browser Engine
10. re-enable updater execution
```

If any rebuild/validation step fails, keep Engine stopped and updater disabled until the reconstructible derived artifacts are rebuilt successfully. A normal updater merge independently force-rebuilds all staging embeddings with the currently deployed recipe immediately before delta calculation/merge, including `--resume-staging`; therefore an old resumed staging DB cannot reintroduce vectors from the previous recipe.

## 3) Build embeddings
Embeddings use SentenceTransformers. The text payload is built from:
- `title`
- `description`
- `tags_json`
- `category`
- `channel_name`

Default model is `all-MiniLM-L6-v2`.
```bash
python3 engine/server/db/jobs/build-video-embeddings.py \
  --db-path engine/server/db/whitelist.db
```

Useful flags:
- `--model-name <model>` choose a different SentenceTransformer.
- `--batch-size <N>` trades RAM for throughput.
- `--force` recompute all embeddings.
- `--gpu` uses CUDA and fails if it is unavailable.

## 4) Sync stable index ids

Before building ANN/random/similarity artifacts, sync stable numeric ids for every currently indexable video. A video is indexable when it exists in both `videos` and `video_embeddings`.

```bash
python3 engine/server/db/jobs/sync-video-index-ids.py \
  --db engine/server/db/whitelist.db
```

## 5) Build FAISS ANN index
The index uses `video_index_ids.index_id` as ids. Old rowid-based FAISS artifacts are incompatible and must be rebuilt.

```bash
python3 engine/server/db/jobs/build-ann-index.py \
  --db-path engine/server/db/whitelist.db \
  --index-path engine/server/db/whitelist-video-embeddings.faiss \
  --meta-path engine/server/db/whitelist-video-embeddings.faiss.json \
  --normalize
```

Useful flags:
- `--nlist`, `--m`, `--nbits` tune IVFPQ.
- `--train-sample` controls training set size.
- `--batch-size` controls memory usage when adding vectors.

## 6) Precompute random cache (optional)
This prepares a random stable-index-id pool for the random feed.
```bash
python3 engine/server/db/jobs/precompute-random-index-ids.py \
  --db engine/server/db/whitelist.db \
  --out engine/server/db/random-cache.db \
  --size 5000 \
  --filtered \
  --max-per-author 100 \
  --max-per-instance 0 \
  --refresh
```



The builder owns the artifact lifecycle: it writes a sibling temporary DB, validates the completed generation, then publishes with `os.replace()`. `--refresh` forces a new generation; without it a valid sufficiently sized artifact may be reused. `--reset` is intentionally unsupported.

When `--out` is the configured production runtime path, publication is an offline operation: stop Engine before rebuilding and restart it afterward. Engine does not hot-reload the replaced file.

## 7) Precompute similarity cache (optional)
This speeds up similar video fetches for the video page.
```bash
python3 engine/server/db/jobs/precompute-similar-ann.py \
  --db engine/server/db/whitelist.db \
  --index engine/server/db/whitelist-video-embeddings.faiss \
  --out engine/server/db/similarity-cache.db \
  --top-k 20 \
  --nprobe 16 \
  --reset
```

## 8) Recompute Trending (one-time after dataset build)
Materialize `videos.popularity` for fast Trending queries. The score is
`(views + 10 * likes) / (1 + age_hours)`, so a newer video that gains more
views and likes ranks higher; the one-hour floor protects newly published rows.
```bash
python3 engine/server/db/jobs/recompute-popularity.py \
  --db engine/server/db/whitelist.db \
  --like-weight 10.0 \
  --reset
```


## 9) Build prepared Discovery data

Prepared Discovery keeps request-time tag filters and facets off the raw JSON/corpus
hot paths. Rebuild it after any direct canonical mutation of fields that feed
`video_tags` or facets and before normal serving resumes:

```bash
python3 engine/server/db/jobs/rebuild-video-discovery-data.py \
  --db engine/server/db/whitelist.db
```

The rebuild creates its own prepared tables when absent, normalizes tags, and writes
the facet snapshot atomically with the new tag relation. Facets summarize canonical
metadata rows whose `invalid_reason` is empty; they intentionally do not mirror
runtime error thresholds, instance denylist, or channel moderation counts.

For the first rollout onto an older production DB, keep Engine stopped, deploy the
new code without automatic restart, run `ensure-video-indexes.py`, run the prepared
rebuild above, verify `video_facets_snapshot.snapshot_id=1`, then start Engine. If any
step fails, do not start Engine.

## Logs and progress
All crawler and job commands log to stdout. Redirect if needed:
```bash
npm run crawl:channels -- --resume > /tmp/crawl-channels.log
```

Check progress directly in SQLite:
```bash
sqlite3 engine/crawler/data/crawl.db "select count(*) from instances;"
sqlite3 engine/crawler/data/crawl.db "select status, count(*) from channel_crawl_progress group by status;"
sqlite3 engine/crawler/data/crawl.db "select status, count(*) from video_crawl_progress group by status;"
sqlite3 engine/server/db/whitelist.db "select count(*) from videos;"
sqlite3 engine/server/db/whitelist.db "select count(*) from video_embeddings;"
sqlite3 engine/server/db/similarity-cache.db "select count(*) from similarity_sources;"
sqlite3 engine/server/db/random-cache.db "select count(*) from random_index_ids;"
```
