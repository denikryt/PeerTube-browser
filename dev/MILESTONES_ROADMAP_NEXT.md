# PeerTube Browser — Next Milestone Roadmap

This roadmap supersedes the older milestone drafts as the recommended implementation order after the Engine/Client runtime refactors.

It is based on:

- `dev/PROJECT_FEATURES.md`
- `dev/MILESTONES_FEATURES_WITH_VERIFICATION.md`
- the current project state after the Engine/Client separation, FastAPI migration, schema cleanup, crawler/updater split, and identity/indexing audit

The older roadmap is still useful as a feature inventory, but its order should be adjusted. The main correction is that Discovery API v1 should not be the next large feature before stabilizing ANN/random-cache identity.

## Current baseline

The following areas are considered mostly completed or no longer need to be treated as future product milestones:

- Engine runtime migration to FastAPI.
- Client backend runtime migration to FastAPI.
- Basic Engine/Client service separation.
- Internal Client <-> Engine API behavior sufficient for current UI flows.
- Crawler/database schema split and ownership cleanup.
- Basic video identity model in core tables.
- Baseline tests and characterization tests around current API behavior.
- Partial frontend architecture cleanup.
- Partial operational/dev tooling cleanup.

These areas may still need fixes, but they should be handled as maintenance work, not as the next strategic roadmap milestones.

## Roadmap principles

1. Stabilize data and index identity before exposing stronger public API contracts.
2. Build Discovery API v1 before expanding UI/product surfaces too far.
3. Keep federation, public third-party API access, full auth, PostgreSQL, and moderation dashboards out of the immediate path unless they directly unblock discovery.
4. Prefer small contract-tested milestones over large vague rewrites.
5. Keep local/personal mode viable before adding federated social behavior.

---

## Milestone 0. Stable ANN / index identity migration

### Goal

Remove `video_embeddings.rowid` as a long-lived identity in ANN, random-cache, and related index artifacts.

The stable logical video identity is already mostly:

```text
(video_id, instance_domain)
```

But FAISS and random cache still use SQLite `rowid`. That makes index artifacts fragile across rebuilds, deletes, and future incremental updates.

### Scope

**Engine**

- Add a stable numeric index identity table, for example:

```sql
video_index_ids (
  index_id INTEGER PRIMARY KEY,
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(video_id, instance_domain)
)
```

- Backfill `video_index_ids` from existing `video_embeddings`.
- Ensure `index_id` is never reused for a different video.
- Change FAISS index build to store `video_index_ids.index_id` instead of `video_embeddings.rowid`.
- Change ANN metadata lookup from:

```text
rowid -> video_embeddings -> videos
```

  to:

```text
index_id -> video_index_ids -> video_id + instance_domain -> videos/video_embeddings
```

- Change random cache from `random_rowids(video_rowid)` to stable index ids.
- Update ANN similarity precompute code to treat FAISS IDs as stable `index_id`, not SQLite rowid.
- Add index metadata schema version and `id_source = "video_index_ids.index_id"`.
- Document the identity model in `docs/VIDEO_IDENTITY.md` or an equivalent dev document.

### Out of scope

- Full online incremental FAISS updates.
- PostgreSQL migration.
- Public API redesign.

Full rebuilds may still be allowed after this milestone. The important change is that rebuilt artifacts no longer depend on volatile SQLite rowids.

### Expected result

ANN, random feed, and similarity precompute artifacts use stable numeric IDs that map back to `(video_id, instance_domain)`.

### Verification check

- FAISS metadata reports `id_source = "video_index_ids.index_id"`.
- Rebuilding embeddings/index does not change existing `index_id` assignments for unchanged videos.
- Random feed works without using `video_embeddings.rowid` as the stored cache identity.
- Similar-video lookup works through `index_id -> video identity -> metadata`.
- Deleting or hiding a video prevents it from appearing in random/similar responses, without relying on rowid semantics.

---

## Milestone 1. Index metadata and rebuild lifecycle baseline

### Goal

Make index artifacts explicitly versioned and safely rebuildable.

This is the practical continuation of the old `Incremental recomputation and index versioning` milestone, but without requiring full incremental updates yet.

### Scope

**Engine**

- Define index artifact metadata schema:
  - index schema version;
  - embedding model name/version;
  - embedding dimension;
  - id source;
  - build timestamp;
  - source database/schema fingerprint if practical;
  - total indexed vectors;
  - deleted/skipped rows count if applicable.
- Add startup/runtime validation for index metadata.
- Fail clearly when index artifacts are incompatible with current code/data.
- Add a safe full rebuild command/path for:
  - embeddings;
  - ANN index;
  - random cache;
  - precomputed similarities.
- Define cache invalidation rules for rebuilt artifacts.
- Add basic deletion/inactive-content filtering semantics.

### Out of scope

- PostgreSQL.
- Distributed task queues.
- True partial FAISS mutation.

### Expected result

The system can detect incompatible/stale index artifacts and rebuild them safely.

### Verification check

- Runtime refuses to use an index with incompatible metadata.
- Full rebuild produces valid ANN/random/similarity artifacts.
- Deletion/inactive filtering tests pass for random and similar flows.
- Metadata compatibility tests cover at least one old/invalid schema case.

---

## Milestone 2. Discovery API v1

### Goal

Expose a stable public discovery API and move the Client away from internal/v0 Engine endpoints where practical.

### Scope

**Engine**

- Design and implement versioned public REST API v1.
- Define API versioning policy.
- Implement or stabilize discovery endpoints:
  - random feed;
  - popular feed;
  - fresh feed;
  - hot feed if scoring is ready;
  - recommendations feed;
  - `similar(video_id)` or equivalent;
  - `recommendations(list_of_video_ids)` or equivalent;
  - video metadata endpoint.
- Define request/response schemas.
- Define error response format.
- Define pagination rules.
- Define deterministic ordering guarantees where relevant.
- Define cache behavior and invalidation expectations.
- Publish OpenAPI/contract documentation.
- Make identity semantics explicit:
  - canonical internal identity is `(video_id, instance_domain)`;
  - PeerTube UUID may be accepted as input only through documented resolve behavior;
  - `host`/`instance_domain` must be required or strongly enforced where ambiguity is possible;
  - no API exposes FAISS IDs, rowids, or internal cache IDs.

**Client**

- Adapt discovery calls to API v1.
- Remove direct dependency on internal/v0 endpoints for public discovery flows.
- Normalize video links and route parameters around the documented identity model.

### Expected result

Discovery API v1 is stable enough for the Client and future third-party usage.

### Verification check

- Contract tests pass for every v1 endpoint.
- Pagination/order tests pass.
- Client discovery flows use v1 endpoints.
- API responses expose stable video identity only, never rowid/index internals.
- OpenAPI docs match runtime behavior.

---

## Milestone 3. Engine video search

### Goal

Add first-class video search to Engine and Client.

### Scope

**Engine**

- Implement video search logic.
- Add dedicated search API endpoint(s).
- Define searchable fields:
  - title;
  - description;
  - channel;
  - tags/categories if available;
  - instance/source if available.
- Define ranking strategy for the first version.
- Add pagination and request validation.
- Add performance smoke tests.

**Client**

- Implement or stabilize the search page.
- Connect UI search to Engine API v1 search.
- Show empty/error/loading states.

### Expected result

Users can search videos through a stable API and UI flow.

### Verification check

- Search API schema tests pass.
- Search relevance smoke tests pass on fixture data.
- Client search page works end-to-end.
- Invalid/large queries are rejected consistently.

---

## Milestone 4. Discovery UI surfaces

### Goal

Make the core product experience usable: home feed, search, and video page.

This milestone depends on Discovery API v1 and Search API being stable enough.

### Scope

**Client**

- Implement or finish Home page:
  - feed modes;
  - video cards;
  - dynamic loading/pagination;
  - loading/empty/error states.
- Implement or finish Search page.
- Implement or finish Video page:
  - player/embed;
  - metadata;
  - related/up-next block;
  - comments placeholder or local comments if already available.
- Continue frontend componentization where needed.
- Ensure responsive/mobile behavior for these core pages.

### Expected result

The app has a coherent discovery experience across Home, Search, and Video pages.

### Verification check

- Feed loading UI tests pass.
- Search flow UI tests pass.
- Video page renders metadata/player/related videos correctly.
- Mobile/tablet/desktop smoke checks pass.

---

## Milestone 5. Discovery scope control

### Goal

Allow discovery to be restricted by source/instance scope.

This should happen before major personalization/federation work, because scoped discovery affects crawler assumptions, API semantics, and UI controls.

### Scope

**Engine**

- Implement source/instance-scoped content selection.
- Implement scoped recommendations.
- Add crawler mode or flags for federated scope limitation.
- Define scope behavior for:
  - random;
  - fresh;
  - popular/hot;
  - recommendations;
  - similar;
  - search.
- Define validation for unknown/disallowed scopes.

**Client**

- Add UI controls for source/instance scope where relevant.
- Persist or remember scope preference if appropriate.

### Expected result

Users and operators can restrict discovery to selected instances or source scopes.

### Verification check

- Scope-restricted API responses contain only allowed-source content.
- Scoped recommendations do not leak out-of-scope videos.
- Client scope controls alter API requests correctly.

---

## Milestone 6. Local interaction and personalization baseline

### Goal

Make local user interactions useful for recommendation quality without requiring federation.

### Scope

**Engine**

- Implement intake of user interactions needed for scoring:
  - likes;
  - dislikes if supported;
  - watched/ignored signals if available later;
  - personalization parameters.
- Define recommendation request contract based on user/video signals.
- Add validation and limits for interaction payloads.

**Client**

- Implement or stabilize local-only mode.
- Store user likes/comments locally in the Client database.
- Implement like/dislike add/remove behavior.
- Disable ActivityPub delivery in local-only mode.
- Implement user personalization panel for recommendation parameters.
- Ensure local interactions are sent to Engine only through the documented contract.

### Expected result

Local/personal use works without federation and can influence recommendations.

### Verification check

- Local like/dislike persistence tests pass.
- Local-only mode never attempts ActivityPub delivery.
- Recommendation requests include normalized video identity.
- Personalization parameters affect recommendation calls in a testable way.

---

## Milestone 7. User account baseline

### Goal

Add account/session features needed for multi-user Client instances and durable personalization.

### Scope

**Client**

- Implement registration if public multi-user mode is enabled.
- Implement authentication and session management.
- Implement single-user bootstrap without public registration flow.
- Implement user profile:
  - avatar;
  - nickname;
  - settings.
- Implement user data export.
- Implement remote sign-in to Client instances from a locally deployed Client frontend, if still part of the product direction.

### Expected result

The Client supports both personal/single-user and shared/multi-user account modes.

### Verification check

- Registration/login/logout/session-restore tests pass.
- Single-user bootstrap works without public registration.
- Profile settings persist.
- User data export produces valid output.

---

## Milestone 8. Production/development workflow baseline

### Goal

Make the project easier to install, run, rebuild, and recover.

This milestone can be done earlier if development friction becomes a blocker.

### Scope

**Engine**

- Implement independent production deployment.
- Implement full development mode.
- Implement install/uninstall processes for dev and prod.
- Simplify build/data build to a single-command workflow.
- Implement backup/restore for database and indexes.
- Add task queue only if rebuild/import operations are already painful enough to justify it.

**Client**

- Implement independent production deployment.
- Implement development mode.
- Implement install/uninstall processes for dev and prod.
- Implement one-command personal Client deployment without domain, TLS, or ActivityPub setup.
- Ensure Engine + Client single-machine topology is documented and tested.

### Expected result

A developer or personal user can run and rebuild the project with predictable commands.

### Verification check

- Fresh setup smoke test passes.
- One-command personal deployment smoke test passes.
- Backup/restore smoke test passes.
- Data rebuild command produces valid index/cache artifacts.

---

## Milestone 9. Security and API access controls

### Goal

Harden the API and runtime before serious third-party access or public deployment.

### Scope

**Engine**

- Implement service/API keys.
- Implement token creation/revocation.
- Implement token limits.
- Implement API-level rate limiting:
  - per token;
  - per IP;
  - per instance if applicable.
- Implement IP and instance blocking/restriction mechanisms.
- Implement input size limits and request validation.
- Implement baseline roles/permissions for admin operations.

**Client**

- Add client-side security hardening:
  - XSS protections;
  - CSRF protection;
  - session protection;
  - secure headers.

### Expected result

The system has baseline protections for public or semi-public operation.

### Verification check

- Rate-limit tests pass.
- API key lifecycle tests pass.
- Block/restriction tests pass.
- Input limit tests pass.
- Client security header/session/CSRF checks pass.

---

## Milestone 10. PostgreSQL and migration system

### Goal

Move Engine storage from local SQLite-oriented workflows to a production-grade database model.

This should not block early discovery/product work unless SQLite becomes an operational bottleneck.

### Scope

**Engine**

- Implement database migration system.
- Define rollback strategy.
- Migrate Engine database storage to PostgreSQL.
- Define migration path from current SQLite data.
- Align backups, indexes, and rebuild assumptions with PostgreSQL.
- Re-check stable index identity after migration.

### Expected result

Engine can use PostgreSQL as primary storage with reversible migrations.

### Verification check

- Fresh install migration-up test passes.
- SQLite-to-PostgreSQL migration test passes on fixture data.
- Rollback test restores previous schema/state where supported.
- Index rebuild works from PostgreSQL-backed data.

---

## Milestone 11. Observability and moderation baseline

### Goal

Give operators enough visibility and control to run the system safely.

### Scope

**Engine**

- Add observability baseline:
  - metrics;
  - structured logs;
  - trace/log correlation if practical;
  - alert-ready signals.
- Implement moderation system:
  - ban instances;
  - ban channels;
  - hide/delete videos from discovery.
- Implement public Engine dashboard for open statistics.
- Expose statistics for:
  - instances;
  - videos;
  - channels;
  - load;
  - updates;
  - tokens if API keys exist.
- Implement display of blocked/active/new instances.

**Client**

- Implement user reporting:
  - report;
  - reason;
  - target type.
- Implement moderation dashboard.
- Implement client-side moderation actions:
  - ban users;
  - remove comments;
  - review reports.

### Expected result

Operators can inspect system state and enforce basic moderation decisions.

### Verification check

- Metrics/logging smoke tests pass.
- Instance/channel ban tests affect discovery results.
- Report intake and moderation workflow tests pass.
- Dashboard surfaces show live data from real endpoints.

---

## Milestone 12. Federation foundation

### Goal

Add safe ActivityPub primitives, but only after local discovery and interaction flows are stable.

### Scope

**Engine**

- Implement ActivityPub actor for Engine if still required by the architecture.
- Implement actor identity and key lifecycle:
  - key generation;
  - secure storage;
  - rotation;
  - revocation.
- Implement inbox signature verification.
- Implement anti-replay protection.
- Implement deduplication/idempotency for incoming ActivityPub activities.
- Enforce federation allowlist policy.

**Client**

- Implement Client ActivityPub actor backend.
- Keep private keys server-side only.
- Define actor ownership model for local/personal vs shared Client modes.

### Expected result

The project has secure ActivityPub protocol primitives before sending social actions to remote instances.

### Verification check

- Signature verification tests pass.
- Anti-replay tests pass.
- Idempotency/deduplication tests pass.
- Allowlist enforcement rejects disallowed instances.
- Private keys are never exposed to browser code.

---

## Milestone 13. Federated social delivery

### Goal

Send and receive federated social interactions reliably.

### Scope

**Engine**

- Implement outbox delivery queue.
- Implement retry/backoff.
- Implement dead-letter handling.
- Implement follow logic.
- Process incoming ActivityPub updates.

**Client**

- Implement migration from local-only mode to federated mode.
- Implement authenticated proxying of user actions from local Client frontend to remote Client instance.
- Send likes/comments via ActivityPub to source instances.
- Preserve local account/interactions state during migration.

**System/test layer**

- Add end-to-end federated flow tests.

### Expected result

Federated likes/comments/follows work with retries and safe failure handling.

### Verification check

- Federated like/comment/follow tests pass.
- Retry and dead-letter tests pass.
- Local-only to federated migration preserves user data.
- Duplicate incoming/outgoing activities are handled idempotently.

---

## Milestone 14. External product readiness

### Goal

Prepare the project for demos, third-party evaluation, and external developers.

### Scope

**Presentation/docs**

- Create a separate presentation website.
- Describe architecture:
  - Engine;
  - Client;
  - interaction model;
  - local-only mode;
  - federation model if implemented.
- Describe product capabilities and usage scenarios.
- Document public API and integration possibilities.
- Add links to live demo/UI if available.
- Prepare technical documentation:
  - installation;
  - startup;
  - deployment;
  - data build;
  - API usage;
  - backup/restore;
  - troubleshooting.
- Provide third-party developer guide for using Engine API.

### Expected result

A new developer or external evaluator can understand, run, and integrate with the project using docs only.

### Verification check

- Documentation review checklist passes.
- Fresh-user onboarding dry run succeeds from docs only.
- Public API examples work against a real local or demo instance.

---

## Recommended immediate next tasks

Start with Milestone 0.

Concrete first implementation slice:

1. Add `video_index_ids` schema and backfill logic.
2. Change `build-ann-index.py` to use `index_id` instead of `video_embeddings.rowid`.
3. Change ANN metadata lookup to resolve through `video_index_ids`.
4. Change random cache schema from rowids to stable index IDs.
5. Update metadata to `id_source = "video_index_ids.index_id"`.
6. Add tests proving `index_id` remains stable across rebuilds.

After that, do Milestone 1 only as far as needed to make rebuild/version behavior safe. Then proceed to Discovery API v1.

## Deferred or intentionally not first

The following are important, but should not be the immediate next focus:

- PostgreSQL migration.
- Full auth/RBAC system.
- ActivityPub federation.
- Public moderation dashboard.
- Presentation website.
- Third-party API marketplace/plugin scenario.

They become much more valuable after the discovery/index foundation is stable.
