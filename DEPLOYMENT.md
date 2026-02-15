# Deployment Guide

This project has two parts:
- API server (Python, this repo) — default: `http://127.0.0.1:7070`
- Static client (built assets, this repo)

Below is a clean, minimal order of operations. Docker is intentionally not used.

## 1) Prepare the database
Follow `DATA_BUILD.md`. It explains how to create the SQLite files and FAISS index in `server/db/`.

Expected files (examples):
- `server/db/whitelist.db`
- `server/db/users.db`
- `server/db/similarity-cache.db`
- `server/db/random-cache.db`
- `server/db/whitelist-video-embeddings.faiss`

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
./venv/bin/python3 -m pip install --no-cache-dir -r ./server/requirements.txt
./venv/bin/python3 server/api/server.py
```

The server listens on `http://127.0.0.1:7070`.

Optional (recommended for production): use `install-service.sh` to install systemd units.

API service only:
```bash
sudo ./install-service.sh
```

API service + daily updater timer:
```bash
sudo ./install-service.sh --with-updater-timer
```

To refresh unit files and updater sudoers permissions after installer updates:
```bash
sudo ./install-service.sh --with-updater-timer --force
```

Checks:
```bash
systemctl status peertube-browser
journalctl -u peertube-browser -f
```

If updater timer is installed:
```bash
systemctl status peertube-updater.timer
journalctl -u peertube-updater.service -f
```

## 4) Serve the client
You can serve the static build with any web server. The simplest local option:
```bash
cd client
npx serve -l 5173 dist
```

If the client is served from a different origin than the API, add a query param:
```
?api=http://127.0.0.1:7070
```

## 5) Verify
Open:
- `/` (home)
- `/videos.html`
- `/debug.html`

Optional debug toggle:
```
RECOMMENDATIONS_DEBUG_ENABLED = True  # server/api/server_config.py
```
