# DEV_MAP Schema

Canonical runtime hierarchy:

- `Milestone -> Feature -> Issue`
- `Milestone -> StandaloneIssue`

`Task` is local plan decomposition and lives in `dev/FEATURE_PLANS.md`.

## Target-state statuses

- `Pending`
- `Draft`
- `Planned`
- `Done`

Legacy statuses such as `Approved`, `Tasked`, and `Rejected` may still appear in existing nodes until they are rewritten or retired.

## IDs

- Milestone ID: `M<global_number>`
- Feature ID: stable local feature id (legacy examples: `F18-M1`; target-state examples may be shorter stable ids such as `F18`)
- Issue ID: stable local issue id (legacy examples: `I3-F18-M1`; target-state examples may be shorter stable ids such as `I3`)

Ownership is explicit and must not depend on the identifier string:

- `Feature.milestone_id`
- `Issue.feature_id`
- `Issue.milestone_id`

## Feature node

- `id`
- `milestone_id`
- `title`
- `description`
- `status`
- `track`
- `gh_issue_number`
- `gh_issue_url`
- `issues`
- `branch_name`
- `branch_url`

## Issue node

- `id`
- `feature_id`
- `milestone_id`
- `title`
- `description`
- `status`
- `gh_issue_number`
- `gh_issue_url`

## Root metadata

- `schema_version`
- `statuses`
- `updated_at`
- `task_count`

`task_count` remains available only as legacy metadata while old task allocation helpers still exist.
