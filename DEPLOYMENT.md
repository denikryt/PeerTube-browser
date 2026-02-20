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

Note: Engine recommendation ranking does not require local `engine/server/db/users.db`.
Write-derived ranking signals in Engine come from bridge-ingested aggregated
`interaction_signals`.

## 2) Install systemd services (prod/dev contours)
Centralized installer (source of truth):
```bash
# Prod contour (force reinstall default + updater timer enabled by default)
sudo bash install-service.sh --mode prod --force --with-updater-timer

# Dev contour (separate unit names/ports, safe for local parallel run with prod)
sudo bash install-service.sh --mode dev --force --uninstall
```

Convenience wrappers:
```bash
sudo bash install-service-prod.sh
sudo bash install-service-dev.sh --uninstall
```

Service-specific installers (each supports its own `--mode prod|dev`):
```bash
sudo bash engine/install-engine-service.sh --mode prod --force
sudo bash client/install-client-service.sh --mode dev --force --engine-url http://127.0.0.1:7171
```

Uninstall (symmetric):
```bash
# Centralized contour uninstall
sudo bash uninstall-service.sh --mode dev
sudo bash uninstall-service.sh --mode prod --purge-updater-state

# Wrapper presets
sudo bash uninstall-service-dev.sh
sudo bash uninstall-service-prod.sh --purge-updater-state

# Service-specific uninstallers
sudo bash engine/uninstall-engine-service.sh --mode dev
sudo bash client/uninstall-client-service.sh --mode dev
```

## 3) Build the client
From the project root:
```bash
cd client/frontend
npm install
npm run build
```

Output is in `client/frontend/dist/` (static files to be served).

## 4) Run the API server
From the project root:
```bash
python3 -m venv venv
./venv/bin/python3 -m pip install --no-cache-dir -r ./engine/server/requirements.txt
ENGINE_INGEST_MODE=bridge ./venv/bin/python3 engine/server/api/server.py
```

Engine API listens on `http://127.0.0.1:7070`.

## 5) Run the client backend service
From the project root:
```bash
CLIENT_PUBLISH_MODE=bridge ./venv/bin/python3 client/backend/server.py \
  --port 7072 \
  --engine-url http://127.0.0.1:7070
```

Boundary contract (mandatory):
- Client backend talks to Engine only over HTTP (`/internal/videos/resolve`, `/internal/videos/metadata`, `/internal/events/ingest`).
- Client backend must not import `engine.server.*` modules and must not open `engine/server/db/*` files.
- Frontend runtime reads/writes must use Client API base; no direct Engine API base calls from UI code.

## 6) Serve the client
You can serve the static build with any web server. The simplest local option:
```bash
cd client/frontend
npx serve -l 5173 dist
```

Dev mode shortcut:
```bash
cd client/frontend
npm run dev
```

Optional overrides:
```bash
# Set Client API target explicitly in dev
npm run dev -- --client-api-port 7172
npm run dev -- --client-api-base http://127.0.0.1:7072

# Vite port flags still work
npm run dev -- --port 5175 --strictPort --client-api-port 7172
```

## 7) Verify
Open:
- `/` (home)
- `/videos.html`
- `/debug.html`

Optional debug toggle:
```
RECOMMENDATIONS_DEBUG_ENABLED = True  # engine/server/api/server_config.py
```

## 8) Split architecture smoke tests
Use two dedicated smoke scripts.

### A) Installer/uninstaller matrix and runtime behavior
Contract matrix only (safe, no service changes):
```bash
bash tests/run-installers-smoke.sh --dry-run-only
```

Full live dev contour verification (requires sudo/systemd):
```bash
sudo bash tests/run-installers-smoke.sh --mode dev
```

Live all-contours verification (explicit opt-in for prod changes):
```bash
sudo bash tests/run-installers-smoke.sh --mode all --allow-prod
```

What it verifies:
- all installer/uninstaller entrypoints support `--help` and `--dry-run`,
- install -> HTTP/e2e verify -> uninstall -> verify cleanup,
- idempotent re-install/re-uninstall,
- contour isolation checks,
- teardown on exit.

### B) Client/Engine boundary + bridge interaction
This script starts temporary local processes on test ports and validates split
boundaries and bridge interaction:
```bash
bash tests/run-arch-split-smoke.sh
```

Optional explicit endpoints:
```bash
ENGINE_URL=http://127.0.0.1:7072 CLIENT_URL=http://127.0.0.1:7272 \
  bash tests/run-arch-split-smoke.sh
```
