# Milestones (working version v2)

This version is built based on notes: early validation of already implemented parts, moving security closer to production, and a separate milestone for the indexing track (`29/30/31/32`) with `31` as top priority.

## Planning assumptions

- Team size: 1-2 developers.
- Client is 100% public.
- Estimates are rough (`solo full-time`) and are refined after each completed milestone.

## Milestone 1: Baseline contour and validation of what is already implemented

**Goal:** lock and verify the already implemented baseline elements of Engine/Client separation.

**Engine track:**
- Engine `1`: Close remaining Engine/Client separation points and formally fix module boundaries.
- Engine `2`: Formalize the Client ↔ Engine API contract in a separate specification and make it the source of truth.

**Client track:**
- Client `20`: Lock and document the baseline Client ↔ Engine integration contract (validation, error handling, proxy behavior).

**Integration checkpoint:**
- The baseline contour is formally validated: dev/prod flows are reproducible and match the current architecture.

**Estimate:** 1-2 weeks

## Milestone 2: Video-ID indexing and recomputation contour

**Goal:** isolate the indexing contour into a separate milestone and complete migration to a stable ID scheme.

**Engine track:**
- Engine `31`: Migrate to video-ID-based indexing (top priority of this milestone).
- Engine `30`: Adapt the existing full index rebuild mechanism to video ID.
- Engine `29`: Implement/adapt incremental vector and index recomputation for the new scheme.
- Engine `32`: Ensure correct content deletion without full index rebuild.

**Client track:**
- Client `1`: Perform a major frontend refactor (replace static HTML/CSS).
- Client `2`: Introduce a scalable frontend framework and component architecture.
- Client `3`: Design and implement a unified design system.
- Client `4`: Implement a responsive and mobile-friendly interface.
- Client `5`: Implement the Home page (feed modes, video cards, dynamic loading).
- Client `6`: Implement the video search page.
- Client `7`: Implement the video page (player, comments, similar/up-next block).
- Client `13`: Implement like/dislike functionality (add/remove).

**Integration checkpoint:**
- Migration to video ID does not break delivery or API contract; full/incremental/rebuild scenarios are aligned.

**Estimate:** 4-6 weeks

## Milestone 3: API v1 + UI rewrite with feature parity

**Goal:** rewrite the current UI on the new architecture without losing existing capabilities.

**Engine track:**
- Engine `7`: Design and implement a public REST API.
- Engine `8`: Implement API versioning.
- Engine `18`: Implement feed modes: `random`, `hot`, `popular`, `fresh`, `recommendations`.
- Engine `19`: Implement endpoint `similar(video_id)`.
- Engine `20`: Implement endpoint `recommendations(list_of_video_ids)`.
- Engine `21`: Implement a separate search API.

**Client track:**
- Client `20`: Verify client read compatibility during indexing scheme changes.

**Integration checkpoint:**
- Home/Search/Video run on the new UI architecture with API v1 and feed modes.

**Estimate:** 4-7 weeks

## Milestone 4: Discovery and controlled content scope

**Goal:** improve source controllability and discovery behavior without mandatory deep personalization.

**Engine track:**
- Engine `22`: Implement content selection endpoint within a specified instance/source.
- Engine `23`: Add crawler mode with federated scope limitation (via a new flag).

**Client track:**
- Client `12`: Implement storage of local user actions (likes/comments) in a local data model. *(if required by product)*
- Client `19`: Implement a feed parameter panel. *(if required by product)*

**Integration checkpoint:**
- Content sources and crawler scope are controlled explicitly and predictably.

**Estimate:** 3-5 weeks

## Milestone 5: Federation and social delivery + test layer

**Goal:** build a working federated contour and validate it in practical hosting modes.

**Engine track:**
- Engine `24`: Implement ActivityPub actor for Engine.
- Engine `25`: Implement follow logic and processing of incoming ActivityPub updates.
- Engine `26`: Implement deduplication of incoming ActivityPub activities.

**Client track:**
- Client `14`: Implement sending likes and comments via ActivityPub to the source instance.
- Client `10`: Implement user profile (avatar, nickname, settings). *(if required by product)*
- Client `11`: Implement user data export mechanism. *(if required by product)*

**System/test layer:**
- Add integration and contract tests for the federated flow.
- Fix the interaction architecture for the scenario where Engine and Client are hosted on one machine.

**Integration checkpoint:**
- Social actions from Client and federated ingest in Engine pass end-to-end and are covered by tests.

**Estimate:** 5-8 weeks

## Milestone 6: Moderation and governance

**Goal:** ship a practical moderation MVP with transparent rules and entities.

**Engine track:**
- Engine `33`: Implement Engine moderation system (ban instances, channels).
- Engine `34`: Implement public Engine dashboard (key statistics).
- Engine `35`: Implement collection and publication of statistical data.
- Engine `36`: Implement display of blocked / active / new instances.
- Engine `37`: Implement moderation and data management UI for Engine.
- Engine `38`: Implement UI for Engine analytics.

**Client track:**
- Client `16`: Implement user reporting mechanism (report + reason).
- Client `17`: Implement moderation dashboard.
- Client `18`: Implement client-side moderation system (users/content/comments).

**Integration checkpoint:**
- Reports and moderation outcomes are consistent between Client UI and Engine moderation state.

**Estimate:** 5-8 weeks

## Milestone 7: Production operations and perimeter security

**Goal:** close production contour and security layer on top of a stable architecture.

**Engine track:**
- Engine `3`: Implement independent production deployment for Engine.
- Engine `6`: Simplify build and data build into a "single command" workflow (production-ready).
- Engine `15`: Implement database migration system.
- Engine `16`: Implement data backup mechanism (database and indexes).
- Engine `17`: Implement task queue system for heavy operations.
- Engine `39`: Enable third-party instances to use Engine via API (plugin-like scenario).
- Engine `11`: Implement API-level rate limiting (IP, instance, service keys).
- Engine `12`: Implement IP and instance-level blocking and restriction mechanisms.
- Engine `13`: Implement input size limits and request validation.
- Engine `9`: Implement service/API keys for internal and admin scenarios (not end-user auth).
- Engine `10`: Implement service key management (create, revoke, limits).
- Engine `14`: Implement baseline roles/permissions for admin operations.

**Client track:**
- Client `22`: Implement independent production deployment for Client.
- Client `21`: Implement client-side security hardening (XSS, CSRF, session protection, secure headers).

**Integration checkpoint:**
- Production deployment and security perimeter operate together without degrading public client availability.

**Estimate:** 5-9 weeks

## Milestone 8: Presentation site and complete documentation

**Goal:** make the platform understandable and integrable for external users.

**Presentation/docs track:**
- Presentation `1`: Create a separate project presentation website.
- Presentation `2`: Describe architecture (Engine + Client + interaction model).
- Presentation `3`: Describe platform capabilities and usage scenarios.
- Presentation `4`: Add a section about the public API and integration possibilities.
- Presentation `5`: Add links to live demo / UI.
- Presentation `6`: Prepare full technical documentation (installation, startup, deployment, data build, API usage).
- Presentation `7`: Provide clear documentation for third-party developers who want to use Engine.

**Integration checkpoint:**
- Documentation reflects real Engine+Client behavior and is understandable for external developers without implicit knowledge.

**Estimate:** 2-4 weeks

## Suggested release grouping

- **Release A (baseline contour + UI/API):** Milestones 1-2
- **Release B (indexing + discovery + federation):** Milestones 3-5
- **Release C (moderation + production/security + external adoption):** Milestones 6-8
