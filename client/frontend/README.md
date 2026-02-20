# Frontend

Static web UI for PeerTube Browser. It renders recommendations and video pages
using data from the backend API. The client stays UI‑only: no database access and
no ranking logic.

## What it does
- Fetches Engine read endpoints (`/recommendations`, `/videos/similar`, `/api/video`).
- Renders feeds (recommendations/random) and the video page.
- Stores likes locally in the browser (temporary profile).

## Build
```
npm install
npm run build
```

## Local About Overrides
- Default production source is `about.template.html`.
- Local developer overrides can be placed in:
  - `client/frontend/dev-pages/about.html`
- Files inside `client/frontend/dev-pages/` are ignored by Git (except `client/frontend/dev-pages/.gitignore`).
