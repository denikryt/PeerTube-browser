# Engine Server

Read-only Engine API for PeerTube Browser recommendations and video metadata.
This service does not own user write/profile endpoints.

## What it does
- `/recommendations` recommendations.
- `/videos/{id}/similar` and `/videos/similar` read aliases.
- `/api/video` metadata for the video page.
- `/internal/videos/resolve` internal read lookup for Client (`video_id/uuid + host`).
- `/internal/videos/metadata` internal metadata batch lookup for Client likes/profile.
- `/internal/events/ingest` temporary trusted bridge ingest for normalized events
  (`ENGINE_INGEST_MODE=bridge`).

## Boundary Contract (Engine-side)
- Engine owns read/analytics APIs and internal read/ingest contracts.
- Engine does not own browser-facing write/profile routes (`/api/user-action`, `/api/user-profile/*`).
- Engine runtime must not depend on `engine/server/db/users.db` for recommendation ranking.
- Client backend integration with Engine must go through HTTP contracts, not direct Engine module or DB coupling.

## Notes
- Reads from `DEFAULT_DB_PATH` and FAISS index.
- Recommendation ranking does not depend on local users likes DB; likes are read
  from request-scoped client input. Bridge-ingested `interaction_signals` remain
  stored/aggregated, but current serving and ranking paths do not consume them.
- Test docs:
  - `engine/server/db/jobs/docs/MODERATION_INTEGRATION_TEST.md`
  - `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`

## Runtime Framework

`engine/server/api/server.py` remains the executable entrypoint and launches the FastAPI app from `engine/server/api/app.py` through uvicorn. FAISS/index startup prerequisites are unchanged. Framework compatibility decisions are documented in `docs/FRAMEWORK_COMPATIBILITY.md`.


## Internal Discovery Providers

Engine provides computation/data routes used by the Client backend. Fresh, popular, and persisted-order random providers live under `/internal/discovery/...`; global service-visible filter options live at `/internal/video-facets`. These routes are not browser-facing `/api/v1` routes. `language`, `category`, `tag`, and `instance` share one Engine-owned `VideoFilters` semantic contract across Discovery and video Search.

Fresh/Popular use provider-owned keyset cursors and read canonical `videos` directly; Fresh is ordered by publication time and Popular/Trending by persisted `videos.popularity`. Runtime tag filters use updater-prepared `video_tags`, while `/internal/video-facets` reads the updater-prepared singleton facet snapshot rather than aggregating the corpus on request. Random uses the updater-built `random-cache.db` order and a generation-bound cursor, with the canonical DB attached read-only; its canonical compatibility check also requires `video_tags`. Engine startup applies current read indexes, but it never rebuilds prepared tags/facets or Random data. Missing/incompatible Random artifacts make only Random unavailable; missing/incompatible prepared facets return controlled facet unavailability.
