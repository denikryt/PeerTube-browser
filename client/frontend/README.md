# Frontend

Vue 3 + TypeScript web UI for PeerTube Browser. It renders discovery feeds,
search, channels, video detail, and profile-like UI through the Client backend.
The browser frontend stays UI-only: no Engine access, database access, or ranking
logic lives here.

## What it does

- Uses Vue Router history-mode routes: `/`, `/search`, `/channels`, `/video/:host/:id`, and `/about`.
- Fetches Client-backend public routes such as `/api/v1/discovery/*`, `/api/v1/search/*`, `/api/v1/videos/*`, `/api/channels`, and profile/action routes.
- Stores local likes in browser storage and syncs profile actions through the Client backend.

## Boundary Contract

- Frontend must use Client API base (`window.location.origin` or `VITE_CLIENT_API_BASE`) for API calls.
- Frontend must not use direct Engine API bases, Engine ports, or Engine internal endpoints.
- Vue Router owns browser paths; API calls remain ordinary `fetch` calls to Client backend routes.

## Build

```bash
npm install
npm run build
```

## Source layout

```text
src/main.ts          Vue app bootstrap
src/App.vue          app shell
src/router/          canonical route table
src/views/           route-level Vue views
src/components/      reusable Vue components and legacy pure render helpers still under test
src/composables/     stateful route behavior and API orchestration
src/data/            Client-backend-facing API helpers
src/types/           API row and payload types
src/utils/           formatting and video-field helpers
```

## Tests

Frontend tests are Node-prerequisite checks and are not part of the root fast
Python baseline:

```bash
npm install
npm test -- --run
npm run build

# from repository root:
make test-frontend
```

## Discovery and Search state

Home selection is represented by `mode=recommendations|fresh|popular|random` plus optional `language`, `category`, `tag`, and `instance` query parameters. Search uses the same filters alongside `q`. Control changes use Vue Router replacement, so direct URLs reconstruct the same selection without polluting browser history.

`useFeed()`/`useSearch()` own request generations, cursors, duplicate guards, continuation errors, and retry behavior. Views own only their `IntersectionObserver` resources. Home is the only cached route: `<KeepAlive>` preserves loaded rows/Recommended buffer across video-detail Back navigation, and the observer is disconnected while Home is inactive.

`/api/v1/video-facets` supplies global service-visible language/category/tag/instance options. Facet errors are shown separately from result errors and do not clear URL-owned filters.
