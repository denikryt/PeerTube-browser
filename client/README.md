# Client

Static web UI for PeerTube Browser. It renders recommendations and video pages
using data from the backend API. The client stays UI‑only: no database access and
no ranking logic.

## What it does
- Fetches `/api/similar` and `/api/video`.
- Renders feeds (recommendations/random) and the video page.
- Stores likes locally in the browser (temporary profile).

## Build
```
npm install
npm run build
```
