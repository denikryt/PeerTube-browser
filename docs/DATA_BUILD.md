# Data Build (Crawler + Jobs)

This document explains how to build the local SQLite dataset plus derived
artifacts (embeddings, ANN index, caches) used by the API.

All paths below are relative to the repository root.

## Outputs
- `engine/crawler/data/crawl.db` raw crawl database.
- `engine/server/db/whitelist.db` filtered dataset used by the API.
- `engine/server/db/whitelist-video-embeddings.faiss` and `engine/server/db/whitelist-video-embeddings.faiss.json` ANN index + metadata.
- `engine/server/db/similarity-cache.db` precomputed similar cache (optional).
- `engine/server/db/random-cache.db` random rowid cache (optional).

## Prerequisites
- Node.js + npm for the crawler (`engine/crawler/package.json`).
- Python 3.10+ for jobs (`engine/server/requirements.txt`).
- Optional CUDA if you plan to run embeddings with `--gpu`.

## Automatic background updater
You can run the same build/update flow automatically with the updater worker:

- Worker entrypoint: `engine/server/db/jobs/updater-worker.py`
- It runs: crawl to staging -> embeddings -> merge to prod -> popularity -> ANN rebuild -> similarity precompute.
- Systemd installation: `install-service.sh --with-updater-timer`
- Timer runs daily (`OnUnitInactiveSec=1d`).

Detailed behavior, flags, lock/resume logic, and systemd notes are documented in:

- `engine/server/db/jobs/UPDATER_WORKER.md`

## 1) Crawl data

### Build crawler
```bash
cd engine/crawler
npm install
npm run build
```

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

### Channel video counts
```bash
cd engine/crawler
npm run crawl:channels:videos-count
```

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

If the whitelist DB schema is outdated, migrate it:
```bash
python3 engine/server/db/jobs/migrate-whitelist.py --db engine/server/db/whitelist.db
```

## 3) Build embeddings
Embeddings use SentenceTransformers. The text payload is built from:
- `title`
- `description`
- `tags_json`
- `category`
- `channel_name`
- `comments_count`

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

## 4) Build FAISS ANN index
The index uses `video_embeddings.rowid` as ids.

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

## 5) Precompute similarity cache (optional)
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

## 6) Precompute random cache (optional)
This prepares a random rowid pool for the random feed.
```bash
python3 engine/server/db/jobs/precompute-random-rowids.py \
  --db engine/server/db/whitelist.db \
  --out engine/server/db/random-cache.db \
  --size 5000 \
  --filtered \
  --max-per-author 100 \
  --max-per-instance 0 \
  --reset
```

## 7) Recompute popularity (one-time after dataset build)
Materialize a `videos.popularity` score for fast popular queries.
```bash
python3 engine/server/db/jobs/recompute-popularity.py \
  --db engine/server/db/whitelist.db \
  --like-weight 2.0 \
  --reset
```

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
sqlite3 engine/server/db/random-cache.db "select count(*) from random_rowids;"
```
