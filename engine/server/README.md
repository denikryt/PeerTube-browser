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

## Notes
- Reads from `DEFAULT_DB_PATH` and FAISS index.
- Recommendation ranking does not depend on local users likes DB; likes are read
  from request-scoped client input, and write-derived signals are consumed from
  aggregated `interaction_signals`.
- Test docs:
  - `engine/server/db/jobs/docs/MODERATION_INTEGRATION_TEST.md`
  - `engine/server/db/jobs/docs/ORCHESTRATOR_SMOKE_TEST.md`
