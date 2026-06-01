# Milestones

## Notes

* Process/tooling initiatives are tracked outside product milestones:

  * Automate repeatable workflow and pipeline operations with scripts.
  * Decouple DEV_MAP ownership from ID format and support feature moves between milestones.
* Until Milestone 4 (API v1), the Client <-> Engine contract is considered internal and allowed to evolve.

---

## Milestone 1: Boundary lock and internal contract (v0)

**Goal:** Establish a clean architectural baseline and reproducible development environment.

**Engine track:**

* Close remaining Engine/Client separation points and formally fix module boundaries.
* Define an internal (v0) Client <-> Engine API contract.
* Document module boundaries and responsibility map.

**Client track:**

* Lock and document baseline Client <-> Engine integration behavior (validation, error handling, proxy behavior).
* Remove implicit coupling and undocumented cross-dependencies.

---

## Milestone 2: Runtime modernization (Engine first)

**Goal:** Establish a stable, production-capable runtime foundation for Engine.

**Engine track:**

* Migrate Engine HTTP server from ThreadingHTTPServer to FastAPI (ASGI).
* Introduce unified startup/shutdown lifecycle and app wiring.
* Define baseline request validation and error response model.
* Add health/readiness endpoints and structured logging baseline.
* Define concurrency model and async/sync boundaries.

**Client track:**

* No structural changes. Adjust integration if required by Engine runtime changes.

---

## Milestone 3: Runtime alignment (Client)

**Goal:** Synchronize Client runtime with Engine architecture.

**Engine track:**

* Stabilize runtime behavior after migration.

**Client track:**

* Migrate Client backend HTTP server from ThreadingHTTPServer to FastAPI.
* Align backend proxy/error handling with Engine API contract and new runtime model.
* Introduce unified lifecycle handling consistent with Engine.

---

## Milestone 4: Video-ID indexing migration

**Goal:** Complete migration to stable video-ID-based indexing and recomputation flows.

**Engine track:**

* Migrate to video-ID-based indexing.
* Adapt the existing full index rebuild mechanism to video ID.
* Implement/adapt incremental vector and index recomputation for the new scheme.
* Ensure correct content deletion without full index rebuild.
* Introduce versioned index schema.

**Client track:**

* No changes required.

---

## Milestone 5: API v1 and discovery contract

**Goal:** Ship a stable public API contract for feed/search/recommendation scenarios.

**Engine track:**

* Design and implement a public REST API contract.
* Implement API versioning policy.
* Implement feed modes: `random`, `hot`, `popular`, `fresh`, `recommendations`.
* Implement endpoint `similar(video_id)`.
* Implement endpoint `recommendations(list_of_video_ids)`.
* Implement a separate search API.
* Publish OpenAPI/contract documentation and compatibility policy.
* Define cache and invalidation strategy for feed/search/recommendation responses.
* Define pagination and deterministic ordering guarantees.

**Client track:**

* Adapt integration to API v1.
* Remove usage of internal (v0) endpoints.

---

## Milestone 6: Client architecture refactor (UI foundation)

**Goal:** Modernize frontend architecture without introducing new social features.

**Engine track:**

* Stabilization only.

**Client track:**

* Perform a major frontend refactor (replace static HTML/CSS with a component architecture).
* Design and implement a unified design system.
* Implement a responsive and mobile-friendly interface.
* Implement Home page (feed modes, video cards, dynamic loading).
* Implement video search page.
* Implement video page (player, comments, similar/up-next block).

---

## Milestone 7: Client interaction layer

**Goal:** Introduce user interaction baseline without federation.

**Engine track:**

* Provide minimal support endpoints required for interaction flows.

**Client track:**

* Implement like/dislike functionality (add/remove).
* Implement authentication/session baseline required for profile/reporting/moderation flows.
* Implement storage of local user actions (likes/comments) in a local data model.
* Implement a feed parameter panel. *(optional)*

---

## Milestone 8: Discovery scope control

**Goal:** Control indexing scope and discovery boundaries before federation.

**Engine track:**

* Implement content selection endpoint within a specified instance/source.
* Add crawler mode with federated scope limitation (via a new flag).

**Client track:**

* Expose scope controls where relevant.

---

## Milestone 9: Federation foundation

**Goal:** Implement a safe and minimal ActivityPub layer.

**Engine track:**

* Implement ActivityPub actor for Engine.
* Implement Engine actor identity and key lifecycle (key generation, secure storage, rotation, revoke).
* Implement inbox signature verification and anti-replay protection for incoming ActivityPub requests.
* Implement deduplication and idempotency for incoming/outgoing ActivityPub activities.
* Enforce federation allowlist policy for inbound/outbound instance interactions.

**Client track:**

* Implement Client ActivityPub actor backend (server-side actor keys/signatures/outbox; no browser-side private keys).

---

## Milestone 10: Federation delivery and social flow

**Goal:** Complete end-to-end federated social interactions.

**Engine track:**

* Implement outbox delivery queue with retry/backoff and dead-letter handling.
* Implement follow logic and processing of incoming ActivityPub updates.

**Client track:**

* Implement sending likes and comments via ActivityPub to the source instance.
* Implement user profile (avatar, nickname, settings).
* Implement user data export mechanism.

**System/test layer:**

* Add integration and contract tests for the federated flow.

---

## Milestone 11: Production operations foundation

**Goal:** Establish reliable deployment and operational baseline.

**Engine track:**

* Independent production deployment for Engine.
* Simplify build and data build into a "single command" workflow (production-ready).
* Database migration system with rollback strategy.
* Data backup mechanism (database and indexes).
* Task queue system for heavy operations.
* Fix the interaction architecture for the scenario where Engine and Client are hosted on one machine.

**Client track:**

* Independent production deployment for Client.

---

## Milestone 12: Security and platform controls

**Goal:** Harden system for external usage.

**Engine track:**

* Enable third-party instances to use Engine via API (plugin-like scenario).
* API-level rate limiting (IP, instance, service keys).
* IP and instance-level blocking and restriction mechanisms.
* Input size limits and request validation.
* Service/API keys for internal and admin scenarios (not end-user auth).
* Service key management (create, revoke, limits).
* Baseline roles/permissions for admin operations.
* Add observability baseline (metrics, traces/log correlation, alert-ready signals).

**Client track:**

* Client-side security hardening (XSS, CSRF, session protection, secure headers).

---

## Milestone 13: Moderation, governance, and external readiness

**Goal:** Deliver moderation capabilities and complete external developer/product readiness.

**Engine track:**

* Engine moderation system (ban instances, channels).
* Public Engine dashboard (key statistics).
* Collection and publication of statistical data.
* Display of blocked / active / new instances.
* Moderation and data management UI for Engine.
* UI for Engine analytics.

**Client track:**

* User reporting mechanism (report + reason).
* Moderation dashboard.
* Client-side moderation system (users/content/comments).

**Presentation/docs track:**

* Create a separate project presentation website.
* Describe architecture (Engine + Client + interaction model).
* Describe platform capabilities and usage scenarios.
* Add a section about the public API and integration possibilities.
* Add links to live demo / UI.
* Prepare full technical documentation (installation, startup, deployment, data build, API usage).
* Provide clear documentation for third-party developers who want to use Engine.
