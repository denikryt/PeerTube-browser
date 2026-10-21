# Running

Purpose: install, start, stop, and verify PeerTube Browser.

Run commands from the repository root unless a command changes directory explicitly.

## Requirements

- Python 3.10 or newer;
- Node.js and npm;
- SQLite CLI for manual database checks;
- CUDA for GPU data builds, or CPU mode where supported;
- systemd and sudo only for service installation.

## Install Dependencies

Create the Python environment:

```bash
python3 -m venv venv
./venv/bin/python3 -m pip install --no-cache-dir -r engine/server/requirements.txt
./venv/bin/python3 -m pip install -r engine/server/requirements-dev.txt
```

Install component-local Node dependencies:

```bash
cd client/frontend && npm install
cd ../../engine/crawler && npm install
cd ../..
```

## Required Engine Data

Engine requires these production artifacts before it can start:

```text
engine/server/db/whitelist.db
engine/server/db/whitelist-video-embeddings.faiss
engine/server/db/whitelist-video-embeddings.faiss.json
```

These caches provide Random and cached similarity behavior:

```text
engine/server/db/random-cache.db
engine/server/db/similarity-cache.db
```

Client creates `client/backend/db/users.db` when it starts.

### Build an Initial Dataset

Build the crawler and collect data:

```bash
cd engine/crawler
npm run build
npm run crawl:instances
npm run crawl:channels
npm run crawl:channels:videos-count
npm run crawl:videos
cd ../..
```

Crawler include scopes intersect `--hosts-file` with any in-process host selection; an explicitly empty include selects zero hosts. Exclusions still apply afterward. A missing include file is an error.

A channel listing stopped by `--max-channels` remains incomplete (`in_progress`, restart offset zero). Only a validated remote end with no eligible rows dropped by the budget is `done`. Host-pipeline stops that host before count/video stages when its channel listing is incomplete.

Build the canonical database:

```bash
./venv/bin/python3 engine/server/db/jobs/sync-whitelist.py \
  --db engine/crawler/data/crawl.db \
  --output-db engine/server/db/whitelist.db
```

Build Engine data and derived artifacts:

```bash
./venv/bin/python3 engine/server/db/jobs/build-video-embeddings.py \
  --db-path engine/server/db/whitelist.db \
  --cpu

./venv/bin/python3 engine/server/db/jobs/recompute-popularity.py \
  --db engine/server/db/whitelist.db \
  --like-weight 10.0 \
  --reset

./venv/bin/python3 engine/server/db/jobs/rebuild-video-discovery-data.py \
  --db engine/server/db/whitelist.db

./venv/bin/python3 engine/server/db/jobs/sync-video-index-ids.py \
  --db engine/server/db/whitelist.db

./venv/bin/python3 engine/server/db/jobs/rebuild-video-search-index.py \
  --db engine/server/db/whitelist.db

./venv/bin/python3 engine/server/db/jobs/build-ann-index.py \
  --db-path engine/server/db/whitelist.db \
  --index-path engine/server/db/whitelist-video-embeddings.faiss \
  --meta-path engine/server/db/whitelist-video-embeddings.faiss.json \
  --cpu \
  --normalize

./venv/bin/python3 engine/server/db/jobs/precompute-random-index-ids.py \
  --db engine/server/db/whitelist.db \
  --out engine/server/db/random-cache.db \
  --size 500000 \
  --filtered \
  --max-per-author 100 \
  --max-per-instance 0 \
  --refresh

./venv/bin/python3 engine/server/db/jobs/precompute-similar-ann.py \
  --db engine/server/db/whitelist.db \
  --index engine/server/db/whitelist-video-embeddings.faiss \
  --out engine/server/db/similarity-cache.db \
  --top-k 20 \
  --nprobe 16 \
  --reset
```

Production refresh after the initial build is owned by `docs/UPDATER.md`.

## Start Locally

Use three terminals.

### Engine

```bash
ENGINE_INGEST_MODE=bridge ./venv/bin/python3 engine/server/api/server.py
```

Engine listens on `http://127.0.0.1:7070`.

### Client

```bash
CLIENT_PUBLISH_MODE=bridge ./venv/bin/python3 client/backend/server.py \
  --host 127.0.0.1 \
  --port 7172 \
  --engine-url http://127.0.0.1:7070
```

Client listens on `http://127.0.0.1:7172`.

### Frontend

```bash
cd client/frontend
npm run dev -- --client-api-base http://127.0.0.1:7172
```

Vite prints the frontend URL, normally `http://127.0.0.1:5173`.

## Verify a Local Run

Check both APIs:

```bash
curl -fsS http://127.0.0.1:7070/api/health
curl -fsS http://127.0.0.1:7172/api/health
```

Open the frontend and verify:

```text
/                         discovery feed
/search                   video and channel search
/channels                 channel list
/about                    project description
/video/<host>/<id>        video page
```

## Stop a Local Run

Stop Frontend, Client, and Engine with `Ctrl+C`. Stop Frontend first, then Client, then Engine.

## Build the Frontend

```bash
cd client/frontend
npm run build
```

Static output is written to `client/frontend/dist/`.

## Install systemd Services

Production defaults to Engine `7070`, Client `7072`, and an enabled updater timer:

```bash
sudo bash install-service.sh --mode prod
```

Development uses Engine `7171`, Client `7172`, and no updater timer:

```bash
sudo bash install-service.sh --mode dev
```

Preview generated units without changing the system:

```bash
sudo bash install-service.sh --mode prod --dry-run
```

Remove services while retaining updater state:

```bash
sudo bash uninstall-service.sh --mode prod --keep-updater-state
```

Remove services and updater state:

```bash
sudo bash uninstall-service.sh --mode prod --purge-updater-state
```

## Verification Commands

Fast Python and boundary baseline:

```bash
make test-fast
```

Focused suites and builds:

```bash
make test-jobs
make test-framework
make test-crawler-db
make test-frontend
make build-crawler
make build-frontend
make lint
```

Architecture smoke with temporary local services:

```bash
make test-smoke-arch
```

Installer contract check without system changes:

```bash
make test-installers-dry-run
```

Full live development-contour install and uninstall check:

```bash
sudo bash tests/run-installers-smoke.sh --mode dev
```

## Manual Maintenance and Deployment Barriers

After `npm run build` inside `engine/crawler`, standalone maintenance scripts are available as `npm run crawl:instances`, `crawl:instances:health`, `crawl:channels`, `crawl:channels:health`, `crawl:channels:videos-count`, `crawl:host-pipeline`, `crawl:videos`, `crawl:videos:tags`, `crawl:videos:comments`, `crawl:videos:metadata`, and `crawl:videos:thumbnails` (each accepts its own flags after `--`). An explicit `--hosts-file` selects only its normalized hosts; never run a standalone writer alongside the production Updater. See `docs/UPDATER.md` for scheduled refresh and publication.

The initial dataset commands above are for a fresh installation. For ongoing production updates use `docs/UPDATER.md`; do not run another crawler writer against an active Updater staging database.

Migrate an existing canonical database before using operations that require a newer schema:

```bash
python3 engine/server/db/jobs/migrate-whitelist.py --db engine/server/db/whitelist.db
```

To refresh historical video metadata, stop Engine and other writers, then run the data-only metadata CLI against a migrated database; it validates the schema and never migrates it:

```bash
cd engine/crawler
npm run crawl:videos:metadata -- --db ../server/db/whitelist.db
cd ../..
python3 engine/server/db/jobs/rebuild-video-discovery-data.py --db engine/server/db/whitelist.db
```

A thumbnail-candidate backfill can be limited to a host batch and resumed by SQL-`NULL` candidate state:

```bash
cd engine/crawler
npm run crawl:videos:thumbnails -- --db ../server/db/whitelist.db --resume --hosts-file /path/to/host-batch.txt
cd ../..
```

Run thumbnail maintenance against production only in a controlled offline write window. Candidate repair does not, by itself, require a rebuild of embeddings or search. The existing single-thumbnail field remains the read fallback when `thumbnail_candidates_json` is SQL `NULL`; an authoritative empty list is `[]` and must not be treated as missing.

Changing `title`, `description`, tags, category or channel name after embeddings were produced requires a coordinated rebuild of embeddings, stable IDs, FAISS, and similarity cache. Do not restart Engine or enable the updater timer until all compatible artifacts pass validation. Routine comments-count maintenance does not change embedding inputs. After direct canonical changes to language, category or tags, rebuild prepared Discovery before Engine resumes serving. Fail closed if a required prepared snapshot is absent.

For the first deployment of a database without prepared tags/facets, stop Engine before deploying code that depends on those structures:

```bash
python3 engine/server/db/jobs/ensure-video-indexes.py --db engine/server/db/whitelist.db
python3 engine/server/db/jobs/rebuild-video-discovery-data.py --db engine/server/db/whitelist.db
sqlite3 engine/server/db/whitelist.db 'SELECT snapshot_id, schema_version FROM video_facets_snapshot WHERE snapshot_id=1;'
```

Only restart Engine after a valid singleton exists. The operational `--skip-systemctl` flag in Updater means an external operator owns this stop/start barrier (see `docs/UPDATER.md`). Replacing the configured production `random-cache.db` is also offline: stop Engine, run `precompute-random-index-ids.py --refresh --out <configured-path>`, then restart. The cache is atomically replaced and is not hot-reloaded.

## Development and Verification

`make test-fast` (same as `make test`) runs Python compilation, legacy event checks, Client/Engine boundary checks and pytest; it does **not** run the Node builds or live services. Use `python3 -m pytest` for focused Python regressions, `make lint` for scoped Ruff checks, `make test-jobs` for job and framework contracts, and `make test-framework` for framework adapters.

After installing Node dependencies separately in `engine/crawler` and `client/frontend`:

```bash
make build-crawler
make test-crawler-db
make build-frontend
make test-frontend
```

`npm run test:db` compiles crawler tests and exercises temporary SQLite databases without contacting PeerTube. `npm run test:live:thumbnails` from `engine/crawler` is an opt-in network smoke and may vary with PeerTube availability; use `-- --report /tmp/thumbnail-smoke.json` to retain findings and `-- --full-instance` only for deliberate exhaustive checks. The frontend uses Vitest; a successful frontend build is not proof its test runner completed.

For service verification run `make test-installers-dry-run` (no service changes), `make test-smoke-arch` (local API boundary smoke), or `sudo bash tests/run-installers-smoke.sh --mode dev` (installs/removes the development contour). The latter requires systemd and sudo. Do not use `--mode all --allow-prod` without explicit production-change approval.

## Split Repository Sync

The monorepo is the source of truth. After configuring `engine-remote` and `client-remote` with their respective split repositories, preview and run subtree publication:

```bash
bash ./sync-subtrees.sh --dry-run
bash ./sync-subtrees.sh --require-clean
bash ./sync-subtrees.sh --engine-only
bash ./sync-subtrees.sh --client-only
```

An intentional hotfix made in a split repository can be imported with `git subtree pull --prefix=engine engine-remote main --squash` (or `--prefix=client client-remote main --squash`) and reconciled in the monorepo before the next export. Use `bash ./sync-subtrees.sh --help` for branch/remote overrides; never publish with an unreviewed dirty working tree.
