# Frontend

Static web UI for PeerTube Browser. It renders recommendations and video pages
using data from the backend API. The client stays UI‑only: no database access and
no ranking logic.

## What it does
- Fetches Client-backend gateway routes (`/recommendations`, `/videos/similar`, `/api/video`, `/api/channels`).
- Renders feeds (recommendations/random) and the video page.
- Stores likes locally in the browser (temporary profile).

## Boundary Contract (Frontend-side)
- Frontend must use Client API base (`window.location.origin` or `VITE_CLIENT_API_BASE`) for reads.
- Frontend must not use direct Engine API base or Engine internal endpoints.

## Build
```
npm install
npm run build
```

## Local About Overrides
- Default production source is `client/frontend/dev-pages/about.template.html`.
- Local developer overrides can be placed in:
  - `client/frontend/dev-pages/about.html`
