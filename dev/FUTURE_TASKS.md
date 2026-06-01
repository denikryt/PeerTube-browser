# Future Tasks

This file tracks tasks discovered during planning that are intentionally out of scope for the current implementation plan. Add items here when they are real follow-up work, not vague ideas.

## Cleanup workflow for inactive `video_index_ids`

### Source

`plans/15_stable_ann_index_identity.md`

### Reason

The Stable ANN / Index Identity migration keeps inactive `video_index_ids` rows to avoid unsafe id reuse. This is the safe default for Milestone 0, but inactive rows may accumulate over time when videos or embeddings disappear.

### Future Work

Add a cleanup workflow that can safely delete old inactive mappings only after obsolete FAISS/random artifacts are guaranteed to be gone.

The future design must define:

- how old an inactive row must be before it is eligible for deletion;
- how to prove no active artifact can still reference the inactive `index_id`;
- whether cleanup is manual, scheduled, or part of a maintenance command;
- whether deleted mappings need an audit log before removal;
- how cleanup interacts with backups and rollback.

### Not In Current Scope

Milestone 0 must only soft-retire inactive mappings with `is_active = 0`, `retired_at`, and `retired_reason`. It must not hard-delete mappings.

## Public API identity cleanup for Discovery API v1

### Source

`plans/15_stable_ann_index_identity.md`

### Reason

The Stable ANN / Index Identity migration changes only internal ANN/random artifact identity. It does not change public API responses, frontend URLs, or request identity rules.

The project still needs a clear public video identity contract before or during Discovery API v1.

### Future Work

Define and implement the public API identity contract for videos:

- when to use `video_id`;
- when to use `video_uuid`;
- whether `host` or `instance_domain` is required;
- how `/videos/{id}` should resolve ambiguous ids;
- what frontend URLs should store;
- which fields are public and which fields are internal-only;
- how Client backend should normalize browser-facing identity before forwarding to Engine.

### Not In Current Scope

Milestone 0 must not expose `index_id`, rename API response fields, change frontend URL identity, or redesign public Discovery API routes.
