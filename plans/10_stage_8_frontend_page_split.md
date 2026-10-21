# Stage 8: Refactor Frontend Page Code Into API, State, and Components

## Problem / Goal

The frontend currently works and must remain working while its large page entry modules are split into smaller, readable modules. Stage 8 exists to make the frontend easier to scan, test, and change without changing browser-visible behavior, Client backend contracts, Engine API contracts, route URLs, HTML entrypoints, CSS class names, or build/deployment behavior.

Current frontend shape observed in the real codebase:

```text
client/frontend/src/data/api-base.ts
client/frontend/src/data/cache.ts
client/frontend/src/data/channels.ts
client/frontend/src/data/local-likes.ts
client/frontend/src/data/user-actions.ts
client/frontend/src/data/user-profile.ts
client/frontend/src/data/videos.ts
client/frontend/src/pages/channels/index.ts          # 351 lines
client/frontend/src/pages/videos/index.ts            # 951 lines
client/frontend/src/pages/video-page/index.ts        # 1117 lines
client/frontend/src/types/channels.ts
client/frontend/src/types/videos.ts
```

The largest frontend responsibility problems are:

- `client/frontend/src/pages/videos/index.ts` mixes page bootstrapping, state, feed-mode resolution, fetching, infinite scroll, card rendering, profile modal rendering, live stat refresh, URL construction, formatting, icons, escaping, and DOM mutation.
- `client/frontend/src/pages/video-page/index.ts` mixes page bootstrapping, server metadata reads, direct PeerTube fallback reads, channel/instance metadata reads, similar video loading, similar-card rendering, live stat refresh, reaction handling, URL construction, formatting, icons, escaping, and DOM mutation.
- `client/frontend/src/pages/channels/index.ts` is smaller but still mixes query-state parsing, data loading, table rendering, pagination, and filter event wiring.
- Existing data modules are useful and must be preserved, but they are not enough to separate page controllers from rendering and UI state.
- Frontend tests currently rely mainly on static gateway checks and build checks. Stage 8 must add frontend-specific behavior checks before moving page code.

Stage 8 goal:

```text
Keep the current Vite/vanilla TypeScript frontend and HTML pages, but extract stable frontend API, state, component rendering, formatting, and page-controller boundaries so page entrypoints become composition files instead of mixed-responsibility scripts.
```

This is a frontend-only refactor stage. It must not implement a frontend framework migration, UI redesign, new recommendation behavior, new Client backend routes, new Engine routes, or new crawler/job behavior.

## Expected Behavior

After Stage 8, the visible frontend behavior must remain equivalent to the current behavior.

Preserved browser behavior:

- `client/frontend/videos.html` remains the home/feed page and continues to load `/src/pages/videos/index.ts` as its Vite entrypoint.
- `client/frontend/video-page.html` remains the video detail page and continues to load `/src/pages/video-page/index.ts` as its Vite entrypoint.
- `client/frontend/channels.html` remains the channels page and continues to load `/src/pages/channels/index.ts` as its Vite entrypoint.
- Existing CSS files and CSS class names continue to drive layout and styling. Stage 8 may move TypeScript rendering functions, but it must not rename DOM ids/classes in HTML or generated markup unless the same change is covered by tests and documented as an intentional compatibility-preserving markup update.
- Frontend API calls continue to use the Client backend gateway only. No frontend code may call Engine internal routes or Engine API bases directly.
- Existing query parameters keep their current meaning:
  - `?api=` still controls the Client API base through `resolveClientApiBase`.
  - feed/video params such as `id`, `host`, `limit`, `random`, and `debug` keep their current behavior.
  - channel filters/pagination params keep their current behavior.
- Feed rendering continues to show the same video card fields where available: title, channel/instance identity, thumbnail/embed/image fallback, stats, duration, published time, debug metrics when currently enabled, and links to video pages/original videos.
- Infinite scroll continues to load cards in chunks and fill the viewport when necessary.
- Feed mode buttons continue to select recommendation/random modes using the current URL/query behavior.
- Profile modal behavior continues to show current user likes from `fetchUserProfileLikes` and close through existing close/backdrop actions.
- Video page metadata behavior remains unchanged:
  - Client backend `/api/video` remains the preferred server metadata source.
  - Direct PeerTube metadata fallback remains a frontend fallback only where currently implemented.
  - Dynamic channel/instance metadata enrichment keeps current URL and asset resolution rules.
- Like button behavior on the video page remains unchanged:
  - clicking like updates the local visual active state through current button logic;
  - local likes storage is updated;
  - `/api/user-action` is called through the Client backend data function;
  - errors are handled with the current visible behavior.
- Similar videos on the video page continue to request recommendations through the Client backend and render current card markup/links/stats behavior.
- Channels page filters, pagination, summary text, table rows, links, and error states remain unchanged.
- `npm run build` remains the frontend build command.
- `make build-frontend` remains the root wrapper for the frontend build.

Concrete preserved action examples:

```text
Given videos.html has an empty feed and the Client backend recommendation payload contains two rows,
when the page controller loads the feed,
then the page renders video cards with the same title/link/stat markup and no direct Engine URL calls.
```

```text
Given video-page.html is opened with ?id=uuid-1&host=example.org,
when server metadata is available from /api/video,
then the page renders that metadata, keeps original/similar links, and does not call Engine directly.
```

```text
Given the video page like button is clicked,
when /api/user-action succeeds,
then local visual state and local-likes storage are updated using current behavior and the Client backend call shape remains unchanged.
```

```text
Given channels.html filters are changed,
when the page reloads or fetches channels,
then the request still uses /api/channels on the Client backend and the table/pagination state remains compatible with current behavior.
```

## Architecture

Stage 8 introduces frontend-internal boundaries while keeping the existing Vite and vanilla TypeScript runtime architecture.

Current runtime architecture to preserve:

```text
HTML entrypoint
  -> page TypeScript entrypoint
      -> data modules in client/frontend/src/data/*
      -> Client backend HTTP routes only
      -> DOM rendering through current CSS/HTML ids/classes
```

Target frontend responsibility split:

```text
client/frontend/src/api/
  Client-backend-facing API convenience layer. This may wrap existing data modules but must not call Engine directly.

client/frontend/src/state/
  Page-local and browser-local state helpers, including feed mode, local likes, pagination state, modal state, and query-state parsing.

client/frontend/src/components/
  Pure or mostly-pure rendering helpers for video cards, similar cards, channel rows, like buttons, icons, loading states, error states, profile modal content, and shared DOM fragments.

client/frontend/src/utils/
  Formatting, escaping, URL construction, number/date/duration helpers, asset resolution helpers, and DOM helper functions that do not own page lifecycle.

client/frontend/src/pages/*/index.ts
  Page controller and composition entrypoint only: read DOM roots, wire events, call data/state/component modules, and manage page lifecycle.
```

Stage 8 must keep these ownership rules:

- Frontend owns UI state, rendering, and calls to Client backend only.
- Client backend remains the browser-facing profile/write/read gateway owner. Stage 8 must not add new Client backend routes or change existing Client backend behavior.
- Engine remains recommendation/metadata/internal-ingest owner. Stage 8 must not call Engine directly and must not change Engine API behavior.
- Crawler/jobs remain data collection/update owners. Stage 8 must not touch crawler or updater behavior.
- CSS/HTML entrypoints remain current Vite/vanilla assets. Stage 8 must not introduce React, Vue, Svelte, routing libraries, state frameworks, or component compilers.

### Remaining ownership after Stage 8

After Stage 8, page entrypoints intentionally remain responsible for:

```text
- locating page root DOM nodes;
- creating page controller state;
- calling the right data/state/component modules;
- wiring page-specific event listeners;
- triggering initial page load;
- handling page-level errors through existing visible behavior.
```

After Stage 8, page entrypoints must no longer own large blocks of reusable logic:

```text
- reusable video-card/similar-card/channel-row markup construction;
- shared icon SVG generation;
- shared formatting helpers;
- local-likes state parsing beyond calling state/data helpers;
- repeated live-stat fetch/apply helpers where common behavior can be extracted safely;
- profile modal rendering helpers;
- channel filter/pagination parsing helpers where current behavior is stable.
```

Deferred work is not a gap:

- A framework migration is Stage 10 or a later dedicated frontend plan.
- Major CSS redesign is out of scope.
- Changing API payloads is out of scope.
- Full browser E2E coverage can be expanded later; Stage 8 adds focused DOM/unit coverage and keeps build/static checks.
- Deep direct PeerTube fallback redesign is out of scope; Stage 8 may move existing fallback helpers but must not change their behavior.

## Touched Files

```text
AGENTS.md
README.md
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/TESTING.md
client/README.md
client/frontend/README.md
client/frontend/package.json
client/frontend/tsconfig.json
client/frontend/vite.config.ts
client/frontend/src/data/api-base.ts
client/frontend/src/data/cache.ts
client/frontend/src/data/channels.ts
client/frontend/src/data/local-likes.ts
client/frontend/src/data/user-actions.ts
client/frontend/src/data/user-profile.ts
client/frontend/src/data/videos.ts
client/frontend/src/pages/channels/index.ts
client/frontend/src/pages/video-page/index.ts
client/frontend/src/pages/videos/index.ts
client/frontend/src/types/channels.ts
client/frontend/src/types/videos.ts
tests/check-frontend-client-gateway.sh
Makefile
pyproject.toml
plans/10_stage_8_frontend_page_split.md
```

Stage 8 should edit only the subset needed for the actual frontend split, tests, and documentation. `AGENTS.md` normally should not change unless implementation discovers that the existing project rules lack a frontend-specific rule required by this stage. If that happens, the change must be limited to the missing general rule and not to implementation details.

## New Files

```text
plans/10_stage_8_frontend_page_split.md
client/frontend/src/api/client.ts
client/frontend/src/components/icons.ts
client/frontend/src/components/video-card.ts
client/frontend/src/components/channel-row.ts
client/frontend/src/components/profile-modal.ts
client/frontend/src/components/status.ts
client/frontend/src/state/feed-mode.ts
client/frontend/src/state/page-query.ts
client/frontend/src/state/profile-likes.ts
client/frontend/src/utils/dom.ts
client/frontend/src/utils/format.ts
client/frontend/src/utils/video-fields.ts
client/frontend/test/setup.ts
client/frontend/test/components/video-card.test.ts
client/frontend/test/components/channel-row.test.ts
client/frontend/test/state/feed-mode.test.ts
client/frontend/test/data/client-api-boundary.test.ts
client/frontend/test/pages/video-page-like-action.test.ts
client/frontend/tsconfig.test.json
docs/FRONTEND_COMPATIBILITY.md
```

Optional only if implementation shows that live-stat code can be moved without changing behavior:

```text
client/frontend/src/state/live-stats.ts
client/frontend/test/state/live-stats.test.ts
```

Do not create:

```text
client/frontend/src/router/*
client/frontend/src/framework/*
client/frontend/src/react/*
client/frontend/src/vue/*
client/frontend/src/svelte/*
```

## Implementation Steps

### 1. Run baseline checks before frontend changes

Run these commands before changing frontend production code:

```bash
make test
make lint
bash tests/check-frontend-client-gateway.sh
```

Run this prerequisite-sensitive check if local Node dependencies are available:

```bash
make build-frontend
```

If `make build-frontend` fails because `client/frontend/node_modules` is missing, record that as an environment prerequisite and continue with TypeScript/test changes that can be reviewed. Do not change frontend production behavior to work around missing local dependencies.

### 2. Add frontend test infrastructure without changing runtime behavior

Add minimal frontend tests under `client/frontend/test/*` using Vitest with jsdom.

Modify `client/frontend/package.json` only to add test scripts and test dependencies required for Stage 8:

```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "devDependencies": {
    "@vitest/ui": "... only if not used, do not add",
    "jsdom": "...",
    "vitest": "..."
  }
}
```

Required action:

- Add `vitest` and `jsdom` only.
- Do not add React Testing Library or framework-specific test tools.
- Do not add browser E2E tools in Stage 8.
- Do not put frontend tests into `make test-fast`; they are Node-prerequisite checks and must remain separate.

Add root Makefile targets:

```makefile
test-frontend:
	cd client/frontend && npm run test
```

`make test` remains the existing Python/contract fast baseline. It must not depend on Node.

### 3. Add frontend behavior tests before moving code

Add focused tests for behavior that will be moved.

Required tests:

```text
client/frontend/test/components/video-card.test.ts
client/frontend/test/components/channel-row.test.ts
client/frontend/test/state/feed-mode.test.ts
client/frontend/test/data/client-api-boundary.test.ts
client/frontend/test/pages/video-page-like-action.test.ts
```

The tests must characterize current behavior, not preferred future behavior.

#### 3.1 Video card rendering test

Given a representative `VideoRow` with:

```json
{
  "video_id": "v1",
  "video_uuid": "uuid-1",
  "instance_domain": "example.org",
  "title": "Example Video",
  "channel_name": "Example Channel",
  "channel_url": "https://example.org/video-channels/example",
  "thumbnail_url": "https://example.org/static/thumb.jpg",
  "views": 1234,
  "likes": 10,
  "dislikes": 1,
  "duration": 95,
  "published_at": "2024-01-01T00:00:00Z"
}
```

When the extracted video-card renderer is called.

Then assert:

- title appears escaped as text/HTML-safe output;
- card links to current video page URL rules;
- original video link uses current original URL rules;
- channel label appears;
- duration/stat fields use current formatting helpers;
- debug metrics appear only when renderer is called with debug mode.

#### 3.2 Channel row rendering test

Given a representative `ChannelRow` with instance, followers, videos, and last-check fields.

When the extracted channel-row renderer is called.

Then assert current table cell order, link hrefs, displayed number formatting, and unavailable/null fallback text.

#### 3.3 Feed mode state test

Given current URL query params:

```text
?random=1
?random=true
?random=0
?mode=random
```

When the extracted feed-mode helper runs.

Then assert the exact current mode selection behavior from `resolveFeedMode` and `setFeedMode`, including URL param mutation behavior.

The implementation must first read current code behavior and assert that behavior exactly. Do not invent a new `mode=` contract if the current code only uses `random=`.

#### 3.4 Client API boundary test

Given the frontend source tree.

When the test scans `client/frontend/src`.

Then assert:

- no direct Engine internal route strings appear in production frontend code;
- API helper modules construct URLs through `resolveClientApiBase` or wrappers around it;
- the test allows current PeerTube instance fallback URLs in `video-page/index.ts` or moved metadata helpers because those call public PeerTube instance APIs, not Engine internals.

This test supplements `tests/check-frontend-client-gateway.sh`; it does not replace it.

#### 3.5 Like action test

Given DOM nodes for the video-page like button and fake `fetch`/`localStorage` boundaries.

When the extracted like-action handler is invoked with current metadata/id/host inputs.

Then assert:

- local visual active state changes according to current `toggleReaction` behavior;
- local likes storage receives the same `{video_uuid, instance_domain}` identity;
- Client backend `/api/user-action` request body matches current `sendUserAction` behavior;
- errors preserve current visible/fallback behavior.

If the current like behavior is too tightly coupled to `video-page/index.ts`, first extract only a narrow function that accepts existing dependencies as arguments. Do not rewrite the page lifecycle to make the test pass.

### 4. Extract shared formatting and DOM helpers

Create:

```text
client/frontend/src/utils/format.ts
client/frontend/src/utils/dom.ts
client/frontend/src/utils/video-fields.ts
```

Move only stable helpers that are duplicated or non-page-specific.

Likely candidates from `videos/index.ts` and `video-page/index.ts`:

```text
escapeHtml
formatDuration
formatStatValue
normalizeStatValue
publishedAtMs
formatTimeAgo
channelName/channelInitials-like helpers where behavior is shared
resolve video id/uuid/host fields
thumbnail/avatar/asset resolution helpers only if identical behavior can be preserved
```

Required action:

- If helper behavior differs between pages, either keep page-specific helpers or name them specifically, such as `formatFeedDuration` and `formatVideoPageDuration`.
- Do not unify helpers by changing behavior.
- Every exported helper must have a docstring/comment describing what compatibility behavior it preserves.

### 5. Extract components without changing markup semantics

Create component modules:

```text
client/frontend/src/components/icons.ts
client/frontend/src/components/video-card.ts
client/frontend/src/components/channel-row.ts
client/frontend/src/components/profile-modal.ts
client/frontend/src/components/status.ts
```

Move rendering helpers in small steps:

- `iconEye`, `iconThumbUp`, `iconThumbDown` -> `components/icons.ts`.
- feed `renderCard` -> `components/video-card.ts`.
- video-page `renderSimilarCard` -> `components/video-card.ts` only if one renderer can preserve both card variants through explicit options. If not, keep separate exported functions: `renderFeedVideoCard` and `renderSimilarVideoCard`.
- channels row rendering from `pages/channels/index.ts` -> `components/channel-row.ts`.
- `renderLikes`, `openProfileModal`, and close helpers where reusable -> `components/profile-modal.ts` or `state/profile-likes.ts` plus a DOM renderer.
- loading/error/status text helpers -> `components/status.ts` only if present and repeated.

Required action:

- Preserve existing CSS classes and element ids/data attributes used by live stat updates.
- Preserve `data-video-key`/similar identifiers if current stat update logic depends on them.
- Preserve link hrefs exactly unless a test asserts a corrected current behavior.
- Keep renderers returning `string` if current code uses `innerHTML`, or return `HTMLElement` only if the adapter preserves output equivalence. Do not mix approaches in a way that changes escaping behavior.

### 6. Extract frontend API wrapper layer conservatively

Create:

```text
client/frontend/src/api/client.ts
```

This module may re-export or wrap existing data modules:

```text
fetchSimilarVideosPayload
fetchStaticVideosPayload
fetchChannelsPayload
fetchUserProfileLikes
resetUserProfileLikes
sendUserAction
resolveClientApiBase
```

Required action:

- Keep existing `src/data/*` modules as compatibility owners for current Client API calls unless moving a function is purely mechanical.
- Do not change request payloads, URL paths, query params, cache keys, or error message behavior.
- Do not call Engine URLs directly.
- If an existing page imports from `src/data/*`, Stage 8 may either keep that import or update it to `src/api/client.ts` only if tests show behavior is unchanged.

### 7. Extract state helpers

Create state modules:

```text
client/frontend/src/state/feed-mode.ts
client/frontend/src/state/page-query.ts
client/frontend/src/state/profile-likes.ts
```

Move logic that currently lives inside page files:

- `resolveFeedMode` and `setFeedMode` -> `state/feed-mode.ts`.
- shared query parsing wrappers -> `state/page-query.ts`, only for behavior that is actually shared and stable.
- profile modal/profile likes state orchestration -> `state/profile-likes.ts` only if it can be done without changing modal behavior.

Required action:

- Keep browser globals (`window.location`, `window.history`, `localStorage`) injectable for tests where practical.
- Do not introduce global state stores or framework-style state managers.
- Do not change localStorage key `localLikes:v1` or local-likes payload shape.

### 8. Reduce page entrypoints to controllers

Refactor page entrypoints in this order:

1. `client/frontend/src/pages/channels/index.ts` because it is smallest and validates the extraction pattern.
2. `client/frontend/src/pages/videos/index.ts` because it contains feed rendering, profile modal, and live stats.
3. `client/frontend/src/pages/video-page/index.ts` because it contains the most fallback metadata and like-action behavior.

For each page:

- move one responsibility at a time;
- run affected frontend tests after each page split if Node dependencies are available;
- run `bash tests/check-frontend-client-gateway.sh` after all page imports are updated;
- preserve page bootstrap behavior and top-level `load*().catch(...)` error handling.

Expected final page entrypoint responsibilities:

```text
pages/channels/index.ts
  -> read DOM roots, parse initial state, wire filter/pagination events, call fetch/render helpers.

pages/videos/index.ts
  -> read DOM roots, choose feed source, wire infinite scroll and profile controls, call render helpers.

pages/video-page/index.ts
  -> read DOM roots, load metadata/similar videos, wire reactions, call render/helpers.
```

### 9. Document frontend compatibility decisions

Create:

```text
docs/FRONTEND_COMPATIBILITY.md
```

Purpose paragraph:

```text
This document records frontend compatibility decisions that preserve browser-visible behavior while page code is split into API, state, components, and utilities.
```

Each compatibility decision implemented in Stage 8 must use this format:

```text
Decision:
Reason:
Implementation action:
Tests:
Removal condition, if any:
```

Required Stage 8 entries:

- Vite/vanilla TypeScript entrypoints remain unchanged.
- Frontend uses Client backend only for project API calls.
- CSS classes/DOM ids generated by card renderers are preserved.
- Local likes storage key and payload shape remain `localLikes:v1` with `{video_uuid, instance_domain}` entries.
- Direct PeerTube metadata fallback on the video page remains a public PeerTube fallback, not an Engine bypass.
- Frontend tests are Node-prerequisite checks and are not included in `make test-fast`.

Also update:

```text
docs/ARCHITECTURE.md
docs/DEVELOPMENT.md
docs/TESTING.md
client/frontend/README.md
```

Only update sections whose stated responsibility covers frontend layout, frontend commands, or frontend compatibility.

### 10. Update build/test tooling

Update `client/frontend/package.json`:

```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

Add test config only if required by Vitest/jsdom. Prefer keeping Vite config minimal. If `vite.config.ts` can host test config without changing build behavior, use it. Otherwise create only the minimal test setup file required.

Update root `Makefile`:

```makefile
test-frontend:
	cd client/frontend && npm run test
```

Do not add `test-frontend` to `test-fast` or `test`.

Update `docs/TESTING.md` to state:

- `make test` is Python/static fast baseline.
- `make test-frontend` requires Node frontend dependencies.
- `make build-frontend` remains the production build check.
- frontend tests are focused DOM/unit checks, not full browser E2E.

### 11. Run verification

Required checks after implementation:

```bash
make test
make lint
bash tests/check-frontend-client-gateway.sh
```

Prerequisite-sensitive checks to run if Node dependencies are available:

```bash
make build-frontend
make test-frontend
```

If Node dependencies are not available or cannot be installed, record the exact blocker in the final implementation report. Do not mark the frontend test/build commands as passed unless they actually ran.

Run additional direct checks when available:

```bash
cd client/frontend && npm run build
cd client/frontend && npm run test
```

## Tests

Stage 8 must add frontend tests before moving the behavior they cover.

Required new frontend tests:

```text
client/frontend/test/components/video-card.test.ts
client/frontend/test/components/channel-row.test.ts
client/frontend/test/state/feed-mode.test.ts
client/frontend/test/data/client-api-boundary.test.ts
client/frontend/test/pages/video-page-like-action.test.ts
```

Required existing checks remain:

```bash
make test
make lint
bash tests/check-frontend-client-gateway.sh
```

Prerequisite-sensitive checks:

```bash
make build-frontend
make test-frontend
```

Test scope rules:

- Do not use frontend tests to define new UI behavior.
- Tests must characterize current markup, state, request payloads, and Client gateway behavior.
- Use jsdom for DOM tests.
- Fake only fetch, localStorage, Date/time, and browser APIs not available in jsdom.
- Do not mock internal component functions just to assert that they were called.
- Assert generated HTML/DOM, request URLs/bodies, storage contents, and visible text.

## Documentation Maintenance

Update only documentation whose responsibility covers frontend structure or verification commands.

Required documentation updates:

```text
docs/FRONTEND_COMPATIBILITY.md
  Stage 8 compatibility decisions.

docs/ARCHITECTURE.md
  Frontend ownership and internal API/state/component split.

docs/DEVELOPMENT.md
  Frontend test/build commands and Node prerequisite notes.

docs/TESTING.md
  make test-frontend, make build-frontend, and frontend test scope.

client/frontend/README.md
  Frontend source layout and local commands.
```

Do not update:

```text
docs/ENGINE_API_COMPATIBILITY.md
docs/RECOMMENDATION_COMPATIBILITY.md
docs/CRAWLER_COMPATIBILITY.md
```

unless implementation unexpectedly touches those areas. Touching those areas would mean Stage 8 scope has been exceeded.

## Regression and Blind-Spot Analysis

### Risk: Frontend starts calling Engine directly

Action:

- Keep or improve `tests/check-frontend-client-gateway.sh` coverage.
- Add `client/frontend/test/data/client-api-boundary.test.ts` that scans production frontend source for forbidden Engine/internal API strings.
- Use `resolveClientApiBase` or `src/api/client.ts` for project API calls.
- Preserve direct public PeerTube fallback only in video metadata fallback helpers and document it in `docs/FRONTEND_COMPATIBILITY.md`.

### Risk: Extracted renderers change markup, CSS classes, or DOM ids

Action:

- Add component tests before moving renderers.
- Preserve generated class names and data attributes exactly.
- If renderer differences are unavoidable, keep separate feed/similar renderers rather than forcing a shared renderer.
- Record any intentional markup-preserving compatibility wrapper in `docs/FRONTEND_COMPATIBILITY.md`.

### Risk: Local likes identity changes

Action:

- Do not change `localLikes:v1`.
- Do not change stored entry shape `{video_uuid, instance_domain}`.
- Keep `getRandomLikes()` output shape `{uuid, host}`.
- Test video-page like action and local-likes storage contents.

### Risk: Feed mode URL behavior changes

Action:

- Extract `resolveFeedMode` and `setFeedMode` only after tests assert current `random` query-param behavior.
- Do not introduce a new `mode=` public contract unless a later behavior-change plan says so.
- Keep `setFeedMode` URL mutation behavior exactly as current code.

### Risk: Live stat updates stop finding rendered cards

Action:

- Preserve card keys, `data-*` attributes, and DOM selectors used by `applyStatsToDom` and similar video stat functions.
- If live stat helpers are not safely extractable, leave them in page modules for Stage 8 and document the deferred work.
- Do not change stat request URLs or batching behavior.

### Risk: Direct PeerTube video-page fallback gets mistaken for Engine bypass

Action:

- Keep fallback helpers isolated under video-page metadata helpers or clearly named utilities.
- Add compatibility doc entry explaining that these calls target public PeerTube instance APIs, not Engine internal/read APIs.
- Client gateway tests must continue to reject Engine direct routes while allowing PeerTube instance fallback behavior.

### Risk: Vitest/jsdom dependencies make fast tests heavier

Action:

- Add frontend tests under `make test-frontend` only.
- Do not add Node tests to `make test-fast` or `make test`.
- Document Node dependency prerequisites in `docs/TESTING.md` and `docs/DEVELOPMENT.md`.

### Risk: Build behavior changes while adding test config

Action:

- Keep Vite build config unchanged except minimal test configuration if necessary.
- Run `make build-frontend` when Node dependencies are available.
- If test config requires non-build settings, keep them scoped to Vitest and do not alter build entrypoints.

### Risk: Page lifecycle changes during extraction

Action:

- Keep existing page entrypoint bootstrap order.
- Keep top-level `loadVideos`, `loadVideo`, and channels load error handling behavior until equivalent controller tests exist.
- Move helper functions first, not the lifecycle root.

### Blind spot: No full browser E2E yet

Action:

- Do not pretend jsdom unit tests cover all browser behavior.
- Keep `make build-frontend` as the production bundle check.
- Leave Playwright/browser E2E for a later dedicated plan if needed.

### Blind spot: Node dependencies may be unavailable in this environment

Action:

- Add package/test files correctly and run Node checks when dependencies are present.
- If dependencies cannot be installed, report exact failure and still run Python/static boundary checks.
- Do not mark Node checks passed unless they actually execute.

## Compatibility and Protocol Notes

Generic behavior:

- Splitting frontend modules should preserve observable UI behavior before changing internals.
- DOM/unit tests are appropriate for extracted rendering and state helpers.
- Node-dependent frontend checks should remain separate from Python fast tests.

Project-specific behavior:

- Frontend project API calls must go through the Client backend gateway.
- Client backend remains the owner of user actions/profile writes and Engine proxying.
- Engine remains the owner of recommendation and metadata API behavior.
- Local likes use project-specific localStorage compatibility key `localLikes:v1`.
- Direct PeerTube metadata fallback is PeerTube-specific public instance behavior, not a generic recommendation or Engine API protocol.

## Non-negotiable Implementation Constraints

### Constraint: no framework migration

Required action:

- Do not introduce React, Vue, Svelte, router libraries, or framework build plugins.
- Keep Vite and vanilla TypeScript entrypoints.

### Constraint: no Client/Engine API changes

Required action:

- Do not edit Client backend or Engine backend runtime code in Stage 8.
- If frontend extraction appears to require backend changes, keep the frontend behavior in the page module and defer the backend-dependent change to a later plan.

### Constraint: no CSS/HTML redesign

Required action:

- Do not rename ids/classes in HTML templates or generated markup.
- If a helper extraction cannot preserve markup, do not extract that helper in Stage 8.

### Constraint: no local-likes storage migration

Required action:

- Keep `localLikes:v1` and current payload parsing compatibility.
- Do not add a new storage version in Stage 8.

### Constraint: no build/workspace migration

Required action:

- Do not introduce npm workspaces or root package management.
- Keep frontend commands inside `client/frontend/package.json` and root Makefile wrappers only.

### Constraint: no hidden browser-only behavior in tests

Required action:

- Use jsdom tests for extracted units only.
- Keep full browser concerns documented as a blind spot, not silently assumed covered.

### Constraint: no plan changes during implementation

Required action:

- If implementation discovers an unplanned required backend/API/schema/deployment change, do not implement that change in Stage 8.
- Leave the affected frontend code in place, document the deferred item in the final implementation report, and keep tests/build green for the completed Stage 8 scope.

## Open Questions

None for the current Stage 8 scope.
