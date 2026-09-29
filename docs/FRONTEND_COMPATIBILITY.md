# Frontend Compatibility

This document records frontend compatibility decisions that preserve browser-visible behavior while page code is split into API, state, components, and utilities.

## Vanilla Vite entrypoints remain unchanged

Decision:
`videos.html`, `video-page.html`, and `channels.html` continue to load their existing page entrypoint modules.

Reason:
Stage 8 is an internal frontend split, not a router or framework migration.

Implementation action:
Keep the HTML files and page entrypoint paths unchanged while moving reusable rendering/state helpers into `src/components`, `src/state`, `src/utils`, and `src/api`.

Tests:
`make build-frontend` when Node dependencies are available; frontend component tests exercise extracted renderers.

Removal condition, if any:
Only a later frontend-routing plan may replace these entrypoints.

## Project API calls go through the Client backend

Decision:
Frontend project API calls continue to use the Client backend gateway through existing `src/data/*` functions or `src/api/client.ts` wrappers.

Reason:
The Client backend remains the browser-facing gateway and profile/write owner.

Implementation action:
Keep API paths and request payloads unchanged; add `src/api/client.ts` as a conservative facade over existing data modules.

Tests:
`bash tests/check-frontend-client-gateway.sh` and `client/frontend/test/data/client-api-boundary.test.ts`.

Removal condition, if any:
No planned removal. Any direct Engine API use would require a later architecture-changing plan.

## Generated markup classes and data attributes are preserved

Decision:
Extracted renderers preserve current CSS classes, links, and `data-video-key` / `data-stat` attributes.

Reason:
Current CSS and live-stat update code depend on those selectors.

Implementation action:
Move video-card, similar-card, and channel-row rendering into component modules without renaming selectors or changing output semantics.

Tests:
`client/frontend/test/components/video-card.test.ts` and `client/frontend/test/components/channel-row.test.ts`.

Removal condition, if any:
Only a later CSS/markup redesign plan may change these selectors.

## Local likes storage remains `localLikes:v1`

Decision:
The local likes key and payload shape remain `localLikes:v1` with `{video_uuid, instance_domain}` entries.

Reason:
Client recommendation requests and video-page actions already depend on this browser-local compatibility format.

Implementation action:
Move only like-action orchestration helpers; keep storage reads/writes in `src/data/local-likes.ts` and preserve request shape through `sendUserAction`.

Tests:
`client/frontend/test/pages/video-page-like-action.test.ts`.

Removal condition, if any:
Only a later storage-migration plan may introduce a new key or payload version.

## Direct PeerTube video metadata fallback remains public instance behavior

Decision:
The video page may still call public PeerTube instance APIs for metadata/stat fallback where the current page already does so.

Reason:
This is not an Engine bypass; it is PeerTube-specific public fallback behavior used by the existing video page.

Implementation action:
Keep fallback helpers inside the video-page module during Stage 8 unless they can be moved without changing URL behavior.

Tests:
Frontend gateway checks continue to reject Engine direct/internal API strings while allowing public PeerTube instance fallback code.

Removal condition, if any:
A later metadata strategy plan may replace direct PeerTube fallback with Client/Engine-mediated behavior.

## Frontend tests are Node-prerequisite checks

Decision:
Frontend DOM/unit tests are run through `make test-frontend` and are not part of `make test-fast`.

Reason:
The fast regression baseline must remain Python/static and independent from Node package installation.

Implementation action:
Add Vitest/jsdom scripts inside `client/frontend/package.json` and root wrapper `make test-frontend` only.

Tests:
`make test` remains independent from frontend Node dependencies; `make test-frontend` runs frontend tests when Node dependencies are installed.

Removal condition, if any:
A later CI policy may decide to run frontend tests in a broader target.


## Discovery API v1

Production frontend feed, Search, facets, and video metadata code call Client backend `/api/v1/...` routes only; Engine `/internal/...` routes are forbidden in browser code. Home exposes `Recommended | Fresh | Popular | Random`. Home/Search selection is URL-owned through `mode`, `q`, `language`, `category`, `tag`, and `instance`.

Fresh/Popular/Random infinite scroll is a thin `IntersectionObserver -> loadMore()` trigger over opaque public cursors. Ordinary continuation errors preserve rows/cursor and pause automatic loading until explicit Retry. A stale Random generation resets that selection to page 1 instead of retrying the stale cursor. Recommended is finite: Home fetches the current batch once and reveals it locally in 20-row windows until a native recommendation continuation exists.

Only Home is wrapped in `<KeepAlive>`. Its observer disconnects while deactivated and reconnects on activation without refetching an unchanged selection; Router `savedPosition` restores Back-navigation scroll. Search is not cached by this compatibility contract. Facet failures are independent from result loading and never erase an existing URL filter.

## Ordered thumbnail fallback remains Client-gateway data

Decision:
The browser receives full ordered `thumbnail_candidates` objects (`url`, `width`, `height`) from the Client backend, plus compatible `thumbnail_url` and `thumbnail_urls` mirrors. Client normalization resolves relative thumbnail paths against the row instance, deduplicates candidates in order, retains only positive integer dimensions, and never promotes `preview_path` into the card-thumbnail set.

Reason:
Crawler persistence contains legacy/backfill state that must not leak into Vue components, while broken remote image URLs are only observable at the browser `<img>` boundary.

Implementation action:
`VideoThumbnail.vue` renders exactly one `src` at a time. From candidates with known dimensions it selects the smallest image at least `500×300`; if none qualifies it begins with the crawler's first (largest-known) candidate. It starts remote thumbnail requests for one origin at least 500 ms apart, showing the local default while a later same-host slot waits. On an image `error`, it advances through every other candidate in crawler order under that same host spacing and finally uses `/default-video-thumbnail.svg`. Feed/profile cards and similar-video cards reuse this component; they do not probe or prefetch alternative images themselves.

Initial Home/Search metadata loads render eight `VideoCardSkeleton` placeholders with the same thumbnail/avatar/text geometry as a card; page continuation appends four more. A remote thumbnail keeps its matching thumbnail skeleton visible until the browser emits `load`, including while a same-host request waits for its 500 ms slot. This reserves layout and avoids presenting a completed-looking card before its image is ready.

Tests:
`client/frontend/test/components/video-thumbnail.test.ts`, Client video-row normalization tests, and the frontend Client-gateway boundary check.

Removal condition, if any:
Any switch to `srcset`, parallel preloading, or direct PeerTube image selection would require a later explicit frontend/media plan.
