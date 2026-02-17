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

## Current service split
- Engine API (read): `/recommendations`, `/videos/{id}/similar`, `/videos/similar`, `/api/video`, `/api/health`.
- Client backend (write/profile): `/api/user-action`, `/api/user-profile/*`.
- Internal Client->Engine read contract: `/internal/videos/resolve`, `/internal/videos/metadata`.
- Temporary bridge contract: Client backend publishes events to Engine `/internal/events/ingest`.
- Boundary rule: Client backend must not import `engine.server.*` modules and must not read `engine/server/db/*` directly.

## Split architecture smoke test
Run the boundary/bridge smoke test:
```bash
bash tests/run-arch-split-smoke.sh
```

The script automatically starts Engine (`7072`) and Client (`7272`), runs all checks,
aggregates errors, prints diagnostics, and always stops started processes.

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
