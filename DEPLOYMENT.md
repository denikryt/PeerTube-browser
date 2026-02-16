# Deployment Guide

This project now has separate services:
- Engine API (read/analytics) — default: `http://127.0.0.1:7070`
- Client backend API (write/profile) — recommended local port: `7072` (dev default is `7172`)
- Static client (built assets)

Below is a clean, minimal order of operations. Docker is intentionally not used.

## 1) Prepare the database
Follow `DATA_BUILD.md`. It explains how to create the SQLite files and FAISS index in `engine/server/db/`.

Expected files (examples):
- `engine/server/db/whitelist.db`
- `engine/server/db/similarity-cache.db`
- `engine/server/db/random-cache.db`
- `engine/server/db/whitelist-video-embeddings.faiss`

Client backend keeps its own users DB (default):
- `client/backend/db/users.db`

## 2) Build the client
From the project root:
```bash
cd client
npm install
npm run build
```

Output is in `client/dist/` (static files to be served).

## 3) Run the API server
From the project root:
```bash
python3 -m venv venv
./venv/bin/python3 -m pip install --no-cache-dir -r ./engine/server/requirements.txt
ENGINE_INGEST_MODE=bridge ./venv/bin/python3 engine/server/api/server.py
```

Engine API listens on `http://127.0.0.1:7070`.

## 4) Run the client backend service
From the project root:
```bash
CLIENT_PUBLISH_MODE=bridge ./venv/bin/python3 client/backend/server.py \
  --port 7072 \
  --engine-ingest-base http://127.0.0.1:7070
```

## 5) Serve the client
You can serve the static build with any web server. The simplest local option:
```bash
cd client
npx serve -l 5173 dist
```

Dev mode shortcut:
```bash
cd client
npm run dev
```

Optional overrides:
```bash
# Split Engine/Client API targets in dev
npm run dev -- --engine-api-port 7171 --client-api-port 7172

# Or set full API bases directly
npm run dev -- --engine-api-base http://127.0.0.1:7070 --client-api-base http://127.0.0.1:7072

# Vite port flags still work
npm run dev -- --port 5175 --strictPort --engine-api-port 7171 --client-api-port 7172
```

## 6) Verify
Open:
- `/` (home)
- `/videos.html`
- `/debug.html`

Optional debug toggle:
```
RECOMMENDATIONS_DEBUG_ENABLED = True  # engine/server/api/server_config.py
```
