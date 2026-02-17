# Crawler

Collects and updates data from PeerTube instances and stores it in SQLite.
This component does not handle ranking, API, or UI — only data collection.

## Layout

- `src/`: crawling workflows (instances, channels, videos).
- `engine/server/db/jobs/`: offline data enrichment (embeddings, ANN indexes).
- `data/`: SQLite database and derived artifacts.

## Entry points

- `npm run crawl` (federation crawl)
- `npm run crawl-videos` (video metadata)
- `python3 ../server/db/jobs/build-video-embeddings.py`

## Notes
- Uses the shared DB that is later read by the backend.
