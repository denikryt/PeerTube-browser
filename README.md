# PeerTube Browser

PeerTube Browser is a video discovery project for the federated PeerTube network.
It crawls instances, builds a local dataset, creates ANN indexes for fast similarity
search, and serves a web UI with recommendation feeds.

## Why this exists
PeerTube has great content but weak discovery across the federation. This project
tries to make exploration easier by aggregating public data and providing
similarity-based recommendations.

## High-level pipeline
1) Crawler discovers instances via subscriptions and walks channels/videos.
2) Filtering keeps instances that appear in the JoinPeerTube whitelist.
3) Embeddings are built from video metadata (title, description, tags, channel, etc.).
4) ANN index (FAISS) is created for fast similarity lookups.
5) Server serves recommendations and metadata from the local DB/index.
6) Client renders the feed and video pages.

## Data build
See `DATA_BUILD.md` for the end-to-end steps to build the SQLite dataset and ANN index.

## Components
- `engine/`: read/analytics workspace.
- `engine/crawler/`: crawler subsystem (part of Engine).
- `engine/server/`: read-only recommendation API + bridge ingest.
- `client/frontend/`: frontend app and static assets.
- `client/backend/`: client write/profile API that publishes normalized events to Engine.

## Recommendations (current)
The recommendation system is a mix of filtering + scoring:
- similarity to liked videos,
- freshness,
- popularity,
- layer mixing (explore/exploit/popular/random/fresh).

Likes are used as a signal to find similar content. Engine reads likes from the
current request context only (provided by Client/Frontend) and does not depend
on local `engine/server/db/users.db` for recommendation ranking. Bridge-ingested
events update aggregated `interaction_signals`, which are also used by ranking.
This is not a heavy ML system; it is a transparent, controllable pipeline.

## Canonical Engine/Client boundary contract
| Concern | Owner | Contract | Forbidden coupling |
|---|---|---|---|
| Public read API (`/recommendations`, `/videos/{id}/similar`, `/videos/similar`, `/api/video`, `/api/health`) | Engine | Exposed by Engine HTTP API only. | Client backend importing Engine modules or reading Engine DB files directly. |
| Browser-facing write/profile API (`/api/user-action`, `/api/user-profile/*`) | Client backend | Exposed by Client backend only. | Moving write/profile ownership into Engine handlers. |
| Browser-facing read gateway (`/recommendations`, `/videos/similar`, `/api/video`, `/api/channels`) | Client backend | Frontend reads use Client API base and gateway routes only. | Direct frontend Engine API base usage. |
| Internal Client->Engine read contract (`/internal/videos/resolve`, `/internal/videos/metadata`) | Engine (provider), Client backend (consumer) | Client backend consumes these internal endpoints over HTTP. | Direct DB coupling instead of HTTP contract. |
| Temporary bridge ingest (`/internal/events/ingest`) | Engine (ingest), Client backend (publisher) | Client backend publishes normalized events to Engine ingest endpoint. | Frontend direct ingest calls or bypassing Client normalization path. |

Boundary guard policy:
- Client backend must not import `engine.server.*`/`engine.*` internals and must not read `engine/server/db/*` directly.
- Frontend runtime reads must stay Client-gateway only (no direct Engine API base or Engine internal route usage).

## Service installers
Installer topology:
- Service-specific installers:
  - `engine/install-engine-service.sh` (`--mode prod|dev`)
  - `client/install-client-service.sh` (`--mode prod|dev`)
- Centralized mode installer (source of truth):
  - `install-service.sh --mode prod|dev|all`

Examples:
```bash
# Prod contour defaults to: --force + --with-updater-timer
sudo bash install-service.sh --mode prod

# Dev contour defaults to: --force + --uninstall
sudo bash install-service.sh --mode dev

# Centralized direct mode usage
sudo bash install-service.sh --mode prod --force --with-updater-timer
sudo bash install-service.sh --mode dev --force --uninstall

```

## Service uninstallers
Uninstall topology:
- Service-specific uninstallers:
  - `engine/uninstall-engine-service.sh` (`--mode prod|dev`)
  - `client/uninstall-client-service.sh` (`--mode prod|dev`)
- Centralized mode uninstaller (source of truth):
  - `uninstall-service.sh --mode prod|dev|all`

Examples:
```bash
# Keep updater state artifacts while uninstalling prod contour
sudo bash uninstall-service.sh --mode prod --keep-updater-state

# Purge updater state artifacts while uninstalling dev contour
sudo bash uninstall-service.sh --mode dev --purge-updater-state

# Centralized direct mode usage
sudo bash uninstall-service.sh --mode all --purge-updater-state
```

## Split architecture smoke tests
Two smoke scripts are available:

1. Installer/uninstaller matrix + runtime checks:
```bash
# Contract-only checks (safe, no system changes)
bash tests/run-installers-smoke.sh --dry-run-only

# Full dev contour install/uninstall verification (systemd + HTTP + e2e)
sudo bash tests/run-installers-smoke.sh --mode dev
```

2. Boundary/interaction checks with temporary local processes:
```bash
bash tests/run-arch-split-smoke.sh
```

`run-arch-split-smoke.sh` starts Engine (`7072`) and Client (`7272`) locally,
runs boundary + bridge checks, aggregates errors, prints diagnostics, and always
stops started processes.

### Split smoke stages and failure semantics
1. Contract preflight checks:
   - `tests/check-client-engine-boundary.sh`
   - `tests/check-frontend-client-gateway.sh`
   Any failure here is a hard fail and startup is aborted.
2. Runtime readiness:
   - Engine `/api/health` must become `200` within timeout.
   - Client `/api/health` must become `200` within timeout.
   Timeout/non-200 is a hard fail.
3. Boundary enforcement checks:
   - Engine must reject Client-owned endpoints (`/api/user-profile`, `/api/user-action`) with non-success.
   - Client gateway routes must answer successfully (`/api/channels`, `/recommendations`, `/videos/similar`).
   Any unexpected status is a hard fail.
4. Bridge flow checks:
   - Seed extraction from client recommendations response must succeed (`uuid+host`).
   - Client proxy `/api/video` must return `200`.
   - Client `/api/user-action` response must validate `ok=true`, `bridge_ok=true`, and empty `bridge_error`.
   - Client `/api/user-profile/likes` must return a non-empty likes array after like action.
   Parse/validation mismatch is a hard fail.
5. Engine users DB ownership guard:
   - Engine process must not keep `engine/server/db/users.db` file descriptor open.
   Any open FD match is a hard fail.
6. Failure diagnostics:
   - Script prints aggregated check/error summary and stores run/check/error logs and service log tails for troubleshooting.

## Future ideas
- ActivityPub integration (receive new video events, send likes/comments).
- User accounts and server-side profiles (opt-in).
- Better discovery modes and ranking logic.
- Viewing modes (Hot / Popular / Random / Fresh) as separate feeds or tabs.
- User‑tunable recommendation settings (mix ratios, weights, or presets).
- Peer-to-peer communication between aggregators to share or refresh metadata.
- Far‑beyond‑the‑horizon experiments (collaborative indexing, distributed caches).
- etc

## About the author
This project was started by a developer from Ukraine during the war. It is both
a personal coping project and an attempt to improve discovery in federated media.

## Contributing / support
If you want to help, contributions are welcome. You can open issues or submit PRs.

If you want to support this project, here are quick options:
- [Donatello](https://donatello.to/nachitima/about)
- [Patreon](https://www.patreon.com/c/nachitima)
