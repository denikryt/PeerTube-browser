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
- Default source is `client/frontend/about.template.html`.
- Local developer overrides can be placed in:
  - `client/frontend/about.html`
- Production build always emits `/about.html`. If `client/frontend/about.html` does not exist, Vite temporarily materializes it from `client/frontend/about.template.html` during the build.

## Source layout

Stage 8 keeps the frontend as Vite and vanilla TypeScript while splitting reusable code:

```text
src/api/          Client-backend-facing facade over existing data modules
src/components/   reusable string/DOM render helpers
src/state/        page and browser state helpers
src/utils/        formatting, escaping, DOM, and video-field helpers
src/pages/        page lifecycle controllers and event wiring
```

## Tests

Frontend tests are Node-prerequisite checks and are not part of the root fast Python baseline:

```bash
npm install
npm run test

# from repository root:
make test-frontend
```
