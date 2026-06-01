# Milestones Draft 2 (With Verification)

### Milestone 1. Engine runtime migration

**Engine**

- Perform a major refactor to fully separate Engine from Client as an independent service.
- Close remaining Engine/Client separation points and formally fix module boundaries.
- Define an internal (v0) Client <-> Engine API contract.
- Design and formalize the API contract for Client ↔ Engine interaction.
- Document module boundaries and responsibility map.
- Migrate Engine HTTP server from ThreadingHTTPServer to FastAPI (ASGI).
- Introduce unified startup/shutdown lifecycle and app wiring.
- Define baseline request validation and error response model.
- Add health/readiness endpoints and structured logging baseline.
- Define concurrency model and async/sync boundaries.

**Expected Result**
- Engine runs on FastAPI with stable lifecycle and health/readiness behavior.
- Engine/Client boundaries are explicit and documented.

**Verification Check**
- Start/stop smoke test passes and health/readiness endpoints respond correctly.
- Contract validation and error-format checks pass against documented API behavior.

### Milestone 2. Client backend runtime migration

**Client**

- Lock and document baseline Client <-> Engine integration behavior (validation, error handling, proxy behavior).
- Remove implicit coupling and undocumented cross-dependencies.
- Migrate Client backend HTTP server from ThreadingHTTPServer to FastAPI (ASGI).
- Align backend proxy/error handling with Engine API contract and new runtime model.
- Introduce unified lifecycle handling consistent with Engine.
- Implement proper integration with Engine API (auth-aware requests, validation, rate limiting).

**Expected Result**
- Client backend runs on FastAPI and integrates with Engine contract without runtime regressions.

**Verification Check**
- Client backend startup/shutdown smoke test passes.
- Proxy and error-handling integration tests pass against Engine API v0/v1 expectations.

### Milestone 3. Video-ID indexing migration

**Engine**

- Migrate to video-ID-based indexing.
- Adapt the existing full index rebuild mechanism to video ID.
- Implement full index recalculation mechanism.
- Ensure correct content deletion without full index rebuild.
- Ensure proper content deletion without full index recalculation.

**Expected Result**
- Index and rebuild/delete flows are based on stable video IDs only.

**Verification Check**
- Rebuild produces valid index keyed by video IDs.
- Delete scenario test confirms removed content no longer appears without full rebuild.

### Milestone 4. Incremental recomputation and index versioning

**Engine**

- Implement/adapt incremental vector and index recomputation for the new scheme.
- Implement incremental vector and index recalculation.
- Introduce versioned index schema.

**Expected Result**
- Incremental recomputation works reliably and index schema versions are tracked.

**Verification Check**
- Incremental update test changes only affected vectors/index entries.
- Version migration compatibility test passes between previous and current schema versions.

### Milestone 5. PostgreSQL migration

**Engine**

- Implement database migration system.
- Database migration system with rollback strategy.
- Migrate Engine database storage to PostgreSQL.

**Expected Result**
- Engine uses PostgreSQL as primary storage with reversible migrations.

**Verification Check**
- Fresh install migration-up test passes.
- Migration rollback test restores previous schema/state without data corruption.

### Milestone 6. Discovery API v1

**Engine**

- Design and implement a public REST API.
- Implement API versioning.
- Implement API versioning policy.
- Implement content feed modes: `random`, `hot`, `popular`, `fresh`, `recommendations`.
- Implement feed modes: `random`, `hot`, `popular`, `fresh`, `recommendations`.
- Implement endpoint `similar(video_id)`.
- Implement endpoint `recommendations(list_of_video_ids)`.
- Publish OpenAPI/contract documentation and compatibility policy.
- Define cache and invalidation strategy for feed/search/recommendation responses.
- Define pagination and deterministic ordering guarantees.

**Client**

- Adapt integration to API v1.
- Remove usage of internal (v0) endpoints.

**Expected Result**
- Public, versioned discovery API v1 is stable and used by Client.

**Verification Check**
- API contract tests pass for feeds/similar/recommendations with pagination/order guarantees.
- Client no longer depends on internal v0 endpoints.

### Milestone 7. Engine video search

**Engine**

- Implement video search logic in Engine.
- Implement a dedicated search API.
- Implement a separate search API.

**Expected Result**
- Engine search is available via dedicated API endpoint(s).

**Verification Check**
- Search API integration tests return relevant results and valid response schema.
- Search endpoint performance smoke test stays within agreed response budget.

### Milestone 8. Frontend architecture foundation

**Client**

- Perform a major frontend refactor (replace static HTML/CSS with a component architecture).
- Design and implement a unified design system.
- Implement responsive and mobile-friendly interface.

**Expected Result**
- Client frontend is component-based, consistent in UI, and responsive.

**Verification Check**
- Core pages render through new component architecture.
- Responsive checks pass on target breakpoints (mobile/tablet/desktop).

### Milestone 9. Discovery UI surfaces

**Client**

- Implement Home page (feed modes, video cards, dynamic loading).
- Implement video search page.
- Implement Video page (player, comments, related/up next section).

**Expected Result**
- Discovery surfaces (Home/Search/Video) are fully functional end-to-end.

**Verification Check**
- UI integration tests pass for feed loading, search flow, and video page rendering.
- Manual smoke check confirms core discovery navigation works without blockers.

### Milestone 10. User account baseline

**Client**

- Implement user registration.
- Implement authentication and session management (including multiple login methods).
- Implement authentication/session baseline required for profile/reporting/moderation flows.
- Implement user profile (avatar, nickname, settings).
- Implement user data export mechanism.
- Implement single-user bootstrap without public registration flow.
- Implement remote sign-in to Client instances from a locally deployed Client frontend.

**Expected Result**
- Client supports account lifecycle for shared and single-user setups, including remote sign-in.

**Verification Check**
- Registration/login/session tests pass (including logout and session restore).
- Single-user bootstrap and remote sign-in flows pass end-to-end smoke checks.

### Milestone 11. Local interaction baseline

**Engine**

- Provide minimal support endpoints required for interaction flows.
- Implement intake of user interactions (likes, comments) for scoring.
- Implement receiving and processing personalization parameters from Client.

**Client**

- Implement local-only Client mode where all user interactions are stored only in the Client database.
- Implement storage of user likes and comments in database.
- Implement like/dislike functionality (add/remove).
- Implement disabling of ActivityPub delivery for likes and comments in local-only mode.
- Implement a feed parameter panel. *(optional)*
- Implement user personalization panel for recommendation parameters.

**Expected Result**
- Local interactions work reliably, including local-only mode without federation delivery.

**Verification Check**
- Like/comment persistence tests pass for local DB storage.
- Local-only mode test confirms no ActivityPub delivery attempts are made.

### Milestone 12. Discovery scope control

**Engine**

- Implement content selection endpoint within a specified instance/source.
- Implement scoped recommendations based on a specified instance.
- Add crawler mode with federated scope limitation (via a new flag).
- Implement crawler with federated scope limitation.

**Client**

- Expose scope controls where relevant.

**Expected Result**
- Discovery can be restricted by source/instance scope in Engine and Client.

**Verification Check**
- Scope-restricted API queries return only allowed-source content.
- Client scope UI controls correctly alter query behavior.

### Milestone 13. Federation foundation

**Engine**

- Implement ActivityPub actor for Engine.
- Implement Engine actor identity and key lifecycle (key generation, secure storage, rotation, revoke).
- Implement inbox signature verification and anti-replay protection for incoming ActivityPub requests.
- Implement deduplication of incoming ActivityPub activities.
- Implement deduplication and idempotency for incoming/outgoing ActivityPub activities.
- Enforce federation allowlist policy for inbound/outbound instance interactions.

**Client**

- Implement Client ActivityPub actor backend (server-side actor keys/signatures/outbox; no browser-side private keys).

**Expected Result**
- Safe baseline federation primitives are in place for Engine and Client backends.

**Verification Check**
- Signature/anti-replay/idempotency tests pass for inbound and outbound ActivityPub flow.
- Allowlist enforcement test rejects non-allowed instances.

### Milestone 14. Federated social delivery

**Engine**

- Implement outbox delivery queue with retry/backoff and dead-letter handling.
- Implement follow logic and processing of incoming ActivityPub updates.

**Client**

- Implement migration from local-only mode to federated mode.
- Implement authenticated proxying of user actions from local Client frontend to remote Client instance.
- Implement sending likes and comments via ActivityPub to the source instance.

**System/test layer**

- Add integration and contract tests for the federated flow.

**Expected Result**
- Federated delivery is reliable, with retries and full social interaction flow.

**Verification Check**
- End-to-end federated like/comment/follow tests pass with retry scenarios.
- Local-only to federated migration test preserves account/interactions state.

### Milestone 15. Production deployment and operations

**Engine**

- Implement independent production deployment for Engine.
- Implement a full development mode for Engine.
- Implement install / uninstall processes for Engine (dev / prod).
- Simplify build and data build to a “single command” workflow.
- Simplify build and data build into a "single command" workflow (production-ready).
- Implement data backup mechanism (database and indexes).
- Implement a task queue system for heavy operations.
- Fix the interaction architecture for the scenario where Engine and Client are hosted on one machine.

**Client**

- Implement independent production deployment for Client.
- Implement development mode for Client.
- Implement install / uninstall processes for Client (dev / prod).
- Implement one-command personal Client deployment without domain, TLS, or ActivityPub setup.

**Expected Result**
- Engine and Client are deployable and operable independently with reproducible workflows.

**Verification Check**
- One-command deploy smoke tests pass for shared and personal deployment modes.
- Backup/restore and queue-processing smoke tests pass in production-like environment.

### Milestone 16. Security and access controls

**Engine**

- Enable third-party instances to use Engine via API (plugin-like scenario).
- Implement an access token system (API keys) for Engine.
- Implement token management (creation, revocation, limits, moderation).
- Implement API-level rate limiting (including limits per token, IP, instance).
- Implement IP and instance-level blocking and restriction mechanisms.
- Implement input size limits and request validation.
- Implement a roles and permissions system (RBAC).
- Service/API keys for internal and admin scenarios (not end-user auth).
- Service key management (create, revoke, limits).
- Baseline roles/permissions for admin operations.

**Client**

- Implement client-side security hardening (XSS, CSRF, session protection).
- Client-side security hardening (XSS, CSRF, session protection, secure headers).

**Expected Result**
- Access control and security hardening are enforced across API and client runtime.

**Verification Check**
- Security test suite passes for authz, rate limits, input limits, and key lifecycle.
- Client-side security headers and CSRF/session protections are validated in integration tests.

### Milestone 17. Observability and moderation

**Engine**

- Add observability baseline (metrics, traces/log correlation, alert-ready signals).
- Implement Engine moderation system (ban instances, ban channels).
- Implement public Engine dashboard (open statistics).
- Implement collection and exposure of statistical data (instances, videos, channels, load, updates, tokens).
- Implement display of blocked / active / new instances in the dashboard.
- Implement moderation and data management interface for Engine via UI.
- Implement UI for Engine analytics (metrics, resource usage, token activity).

**Client**

- Implement user reporting mechanism (report + reason).
- Implement moderation dashboard.
- Implement client-side moderation system (ban users, remove comments).

**Expected Result**
- Operators have baseline observability and moderation capabilities on both sides.

**Verification Check**
- Metrics/log/trace pipeline smoke tests pass and dashboards display live data.
- Moderation workflow tests pass for report intake, review, and enforcement actions.

### Milestone 18. External product readiness

**Presentation/docs**

- Create a separate presentation website for the project.
- Describe the architecture (Engine + Client + interaction model).
- Describe platform capabilities and usage scenarios.
- Add a section about the public API and integration possibilities.
- Add links to live demo / UI.
- Prepare full technical documentation (installation, startup, deployment, data build, API usage).
- Provide clear documentation for third-party developers who want to use Engine.

**Expected Result**
- External stakeholders can understand, evaluate, and integrate the product.

**Verification Check**
- Public docs/presentation review checklist is fully passed.
- Onboarding dry-run confirms third-party developer can install and call API from docs only.
