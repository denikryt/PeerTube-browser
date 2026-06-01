# Milestones Draft

### Milestone 1. Engine runtime migration

- Migrate Engine backend from ThreadingHTTPServer to FastAPI.
- Introduce lifecycle wiring, readiness, and structured runtime behavior.
- Align validation and error handling with the runtime migration.

### Milestone 2. Client backend runtime migration

- Migrate Client backend from ThreadingHTTPServer to FastAPI.
- Align proxy/runtime behavior with the Engine contract.
- Stabilize Client backend lifecycle handling.

### Milestone 3. Video-ID indexing migration

- Migrate indexing to stable video IDs.
- Adapt full rebuild flow to the new identity model.
- Ensure correct content deletion semantics.

### Milestone 4. Incremental recomputation and index versioning

- Implement incremental vector and index recomputation.
- Introduce versioned index schema.
- Make recompute and rebuild flows migration-safe.

### Milestone 5. PostgreSQL migration

- Migrate Engine database storage to PostgreSQL.
- Define and implement the migration path from the current storage model.
- Align schema, migrations, and backup assumptions with PostgreSQL.

### Milestone 6. Discovery API v1

- Publish stable API v1.
- Implement feed, recommendation, and discovery contracts.
- Define pagination, ordering, caching, and compatibility policy.

### Milestone 7. Engine video search

- Implement search logic on the Engine side.
- Define search behavior and ranking strategy.
- Expose search through a dedicated backend/API contract.

### Milestone 8. Frontend architecture foundation

- Refactor frontend into a component-based architecture.
- Introduce a unified design system.
- Make the interface responsive and mobile-friendly.

### Milestone 9. Discovery UI surfaces

- Implement Home/feed UX.
- Implement search page.
- Implement video page with similar/up-next block.

### Milestone 10. User account baseline

- Implement authentication and session baseline.
- Implement user registration.
- Implement user profile and account state.
- Implement single-user bootstrap without public registration flow.
- Implement remote sign-in to Client instances from a locally deployed Client frontend.

### Milestone 11. Local interaction baseline

- Implement local-only Client mode where all user interactions are stored only in the Client database.
- Implement likes/dislikes and local comments flow.
- Implement disabling of ActivityPub delivery for likes and comments in local-only mode.
- Persist local user actions and basic profile state.

### Milestone 12. Discovery scope control

- Implement source/instance-scoped content selection.
- Add crawler scope limitation controls.
- Expose scope controls in Client UX.

### Milestone 13. Federation foundation

- Implement ActivityPub actor model.
- Implement key lifecycle and request verification.
- Add anti-replay, allowlist, idempotency, and safe protocol handling.

### Milestone 14. Federated social delivery

- Implement outbox delivery queue and retries.
- Process follows and incoming ActivityPub updates.
- Implement migration from local-only mode to federated mode.
- Implement authenticated proxying of user actions from local Client frontend to remote Client instance.
- Send likes/comments to remote instances.
- Add end-to-end federated flow tests.

### Milestone 15. Production deployment and operations

- Implement independent Engine and Client deployment.
- Implement one-command personal Client deployment without domain, TLS, or ActivityPub setup.
- Build a one-command production build/deploy path.
- Implement migrations, backups, task queue, and robust single-host topology.

### Milestone 16. Security and access controls

- Implement rate limiting and service keys.
- Implement admin permissions and restriction controls.
- Add input/resource limits and client-side security hardening.

### Milestone 17. Observability and moderation

- Add observability baseline.
- Implement moderation tooling for Engine and Client.
- Implement analytics and operator-facing dashboard surfaces.

### Milestone 18. External product readiness

- Publish project presentation site.
- Publish external-facing architecture and API documentation.
- Package the product for demos, stakeholders, and third-party adopters.
