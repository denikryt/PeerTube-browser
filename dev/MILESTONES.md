# Milestones (working version v2)

This version is built based on notes: early validation of already implemented parts, moving security closer to production, and a separate milestone for the indexing track (`29/30/31/32`) with `31` as top priority.

## Planning assumptions

- Team size: 1-2 developers.
- Client is 100% public.
- Estimates are rough (`solo full-time`) and are refined after each completed milestone.

## Milestone 1: Baseline contour and validation of what is already implemented

**Goal:** lock and verify the already implemented baseline elements of Engine/Client separation.

**Engine track:**
- Close remaining Engine/Client separation points and formally fix module boundaries.
- Formalize the Client ↔ Engine API contract in a separate specification and make it the source of truth.

**Client track:**
- Lock and document the baseline Client ↔ Engine integration contract (validation, error handling, proxy behavior).

**Integration checkpoint:**
- The baseline contour is formally validated: dev/prod flows are reproducible and match the current architecture.

**Estimate:** 1-2 weeks

## Milestone 2: Video-ID indexing and recomputation contour

**Goal:** isolate the indexing contour into a separate milestone and complete migration to a stable ID scheme.

**Engine track:**
- Migrate to video-ID-based indexing (top priority of this milestone).
- Adapt the existing full index rebuild mechanism to video ID.
- Implement/adapt incremental vector and index recomputation for the new scheme.
- Ensure correct content deletion without full index rebuild.

**Client track:**
- Perform a major frontend refactor (replace static HTML/CSS).
- Introduce a scalable frontend framework and component architecture.
- Design and implement a unified design system.
- Implement a responsive and mobile-friendly interface.
- Implement the Home page (feed modes, video cards, dynamic loading).
- Implement the video search page.
- Implement the video page (player, comments, similar/up-next block).
- Implement like/dislike functionality (add/remove).

**Integration checkpoint:**
- Migration to video ID does not break delivery or API contract; full/incremental/rebuild scenarios are aligned.

**Estimate:** 4-6 weeks

## Milestone 3: API v1 + UI rewrite with feature parity

**Goal:** rewrite the current UI on the new architecture without losing existing capabilities.

**Engine track:**
- Design and implement a public REST API.
- Implement API versioning.
- Implement feed modes: `random`, `hot`, `popular`, `fresh`, `recommendations`.
- Implement endpoint `similar(video_id)`.
- Implement endpoint `recommendations(list_of_video_ids)`.
- Implement a separate search API.

**Client track:**
- Verify client read compatibility during indexing scheme changes.

**Integration checkpoint:**
- Home/Search/Video run on the new UI architecture with API v1 and feed modes.

**Estimate:** 4-7 weeks

## Milestone 4: Discovery and controlled content scope

**Goal:** improve source controllability and discovery behavior without mandatory deep personalization.

**Engine track:**
- Implement content selection endpoint within a specified instance/source.
- Add crawler mode with federated scope limitation (via a new flag).

**Client track:**
- Implement storage of local user actions (likes/comments) in a local data model. *(if required by product)*
- Implement a feed parameter panel. *(if required by product)*

**Integration checkpoint:**
- Content sources and crawler scope are controlled explicitly and predictably.

**Estimate:** 3-5 weeks

## Milestone 5: Federation and social delivery + test layer

**Goal:** build a working federated contour and validate it in practical hosting modes.

**Engine track:**
- Implement ActivityPub actor for Engine.
- Implement follow logic and processing of incoming ActivityPub updates.
- Implement deduplication of incoming ActivityPub activities.

**Client track:**
- Implement sending likes and comments via ActivityPub to the source instance.
- Implement user profile (avatar, nickname, settings). *(if required by product)*
- Implement user data export mechanism. *(if required by product)*

**System/test layer:**
- Add integration and contract tests for the federated flow.
- Fix the interaction architecture for the scenario where Engine and Client are hosted on one machine.

**Integration checkpoint:**
- Social actions from Client and federated ingest in Engine pass end-to-end and are covered by tests.

**Estimate:** 5-8 weeks

## Milestone 6: Moderation and governance

**Goal:** ship a practical moderation MVP with transparent rules and entities.

**Engine track:**
- Implement Engine moderation system (ban instances, channels).
- Implement public Engine dashboard (key statistics).
- Implement collection and publication of statistical data.
- Implement display of blocked / active / new instances.
- Implement moderation and data management UI for Engine.
- Implement UI for Engine analytics.

**Client track:**
- Implement user reporting mechanism (report + reason).
- Implement moderation dashboard.
- Implement client-side moderation system (users/content/comments).

**Integration checkpoint:**
- Reports and moderation outcomes are consistent between Client UI and Engine moderation state.

**Estimate:** 5-8 weeks

## Milestone 7: Production operations and perimeter security

**Goal:** close production contour and security layer on top of a stable architecture.

**Engine track:**
- Implement independent production deployment for Engine.
- Simplify build and data build into a "single command" workflow (production-ready).
- Implement database migration system.
- Implement data backup mechanism (database and indexes).
- Implement task queue system for heavy operations.
- Enable third-party instances to use Engine via API (plugin-like scenario).
- Implement API-level rate limiting (IP, instance, service keys).
- Implement IP and instance-level blocking and restriction mechanisms.
- Implement input size limits and request validation.
- Implement service/API keys for internal and admin scenarios (not end-user auth).
- Implement service key management (create, revoke, limits).
- Implement baseline roles/permissions for admin operations.

**Client track:**
- Implement independent production deployment for Client.
- Implement client-side security hardening (XSS, CSRF, session protection, secure headers).

**Integration checkpoint:**
- Production deployment and security perimeter operate together without degrading public client availability.

**Estimate:** 5-9 weeks

## Milestone 8: Presentation site and complete documentation

**Goal:** make the platform understandable and integrable for external users.

**Presentation/docs track:**
- Create a separate project presentation website.
- Describe architecture (Engine + Client + interaction model).
- Describe platform capabilities and usage scenarios.
- Add a section about the public API and integration possibilities.
- Add links to live demo / UI.
- Prepare full technical documentation (installation, startup, deployment, data build, API usage).
- Provide clear documentation for third-party developers who want to use Engine.

**Integration checkpoint:**
- Documentation reflects real Engine+Client behavior and is understandable for external developers without implicit knowledge.

**Estimate:** 2-4 weeks

## Suggested release grouping

- **Release A (baseline contour + UI/API):** Milestones 1-2
- **Release B (indexing + discovery + federation):** Milestones 3-5
- **Release C (moderation + production/security + external adoption):** Milestones 6-8
