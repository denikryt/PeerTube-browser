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
- Crawler: discovers instances/channels/videos and stores raw data.
- Dataset/DB: local SQLite database with video/channel metadata.
- ANN index: FAISS index for similarity search.
- Server: API for /api/similar, /api/video, profile/likes endpoints.
- Client: static web UI (recommendations, video page, channels).

## Recommendations (current)
The recommendation system is a mix of filtering + scoring:
- similarity to liked videos,
- freshness,
- popularity,
- layer mixing (explore/exploit/popular/random/fresh).

Likes are used as a signal to find similar content. This is not a heavy ML system;
it is a transparent, controllable pipeline.

## Privacy
Currently, likes are stored locally in the browser and sent to the server as JSON
per request. The server does not keep user profiles by default.

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
