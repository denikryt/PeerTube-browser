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
