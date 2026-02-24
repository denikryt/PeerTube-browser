# DEV_MAP Schema

Canonical hierarchies:

- Product path: `Milestone -> Feature -> Issue -> Task`
- Standalone path (non-product work): `Milestone -> StandaloneIssue -> Task`

Allowed status values for nodes with status fields (`Feature`, `Issue`, `Task`):
- `Planned`
- `Approved`
- `Done`

Milestone nodes do not have a `status` field.

## Root Metadata

Root object must include:
- `schema_version`: schema contract version.
- `statuses`: allowed status values.
- `updated_at`: last map update timestamp.
- `task_count`: global count of already allocated numeric task IDs.
  - This is the only source for allocating a new numeric task ID.
  - Allocation rule: `new_id = task_count + 1`, then set `task_count = new_id` in the same change set.
  - Never derive next ID by scanning/removing entries in `dev/TASK_LIST.md`.

## Milestone Metadata

Milestone nodes include metadata fields used for planning context:
- `goal`: milestone goal text.
- `features`: list of feature nodes.
- `standalone_issues`: list of standalone issue nodes (`SI*`) for non-product work.
- `non_feature_items`: list of milestone items that are not feature nodes.

## ID Rules

- Milestone ID: `M<global_number>`
  - example: `M1`, `M2`
- Feature ID (local to milestone, with dash format): `F<local_number>-M<milestone_number>`
  - example: `F1-M1`, `F2-M1`
- Issue ID (local to feature, with dash format): `I<local_number>-F<feature_local_number>-M<milestone_number>`
  - example: `I1-F1-M1`, `I2-F1-M1`
- Standalone Issue ID (local to milestone): `SI<local_number>-M<milestone_number>`
  - examples: `SI1-M1`, `SI2-M4`
- Task ID: global task id from `dev/TASK_LIST.md`
  - numeric IDs are allocated from `task_count` (`new_id = task_count + 1`)
  - existing alphanumeric legacy IDs stay valid (`8b`, `16l`)
  - examples: `58`, `59`, `8b`, `16l`
- Non-feature item ID (local to milestone): `NF<local>-M<milestone_number>` or `NS<local>-M<milestone_number>`
  - examples: `NF1-M1`, `NS1-M5`

## Task Node Contract

Task node in `DEV_MAP` must carry these fields:
- `id`: canonical task id from `dev/TASK_LIST.md` (`58`, `8b`, `16l`, ...)
- `date`: `YYYY-MM-DD`
- `time`: `HH:MM:SS`
- `status`: `Planned` or `Done`
- `title`: short task title
- `summary`: detailed task description

## Example A: Current minimal state (milestones only)

```json
{
  "schema_version": "1.4",
  "statuses": ["Planned", "Approved", "Done"],
  "updated_at": "2026-02-23T23:45:00+02:00",
  "task_count": 58,
  "milestones": [
    {
      "id": "M1",
      "title": "Baseline contour and validation",
      "goal": "Milestone goal",
      "standalone_issues": [],
      "non_feature_items": [],
      "features": []
    }
  ]
}
```

## Example B: Full hierarchy template (empty placeholders)

```json
{
  "schema_version": "1.4",
  "statuses": ["Planned", "Approved", "Done"],
  "updated_at": "YYYY-MM-DDTHH:MM:SS+TZ:TZ",
  "task_count": 59,
  "milestones": [
    {
      "id": "M1",
      "title": "Milestone title",
      "goal": "Milestone goal",
      "standalone_issues": [
        {
          "id": "SI1-M1",
          "title": "Standalone issue title",
          "status": "Planned",
          "gh_issue_number": null,
          "gh_issue_url": null,
          "tasks": [
            {
              "id": "58",
              "date": "2026-02-23",
              "time": "20:37:07",
              "title": "Task title",
              "status": "Planned",
              "summary": "Task description/details in roadmap-style wording."
            }
          ]
        }
      ],
      "features": [
        {
          "id": "F1-M1",
          "title": "Feature title",
          "status": "Planned",
          "track": "Engine|Client|Presentation/Docs|System/Test",
          "optional": false,
          "note": null,
          "gh_issue_number": null,
          "gh_issue_url": null,
          "issues": [
            {
              "id": "I1-F1-M1",
              "title": "Issue title",
              "status": "Planned",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": [
                {
                  "id": "58",
                  "date": "2026-02-23",
                  "time": "20:37:07",
                  "title": "Task title",
                  "status": "Planned",
                  "summary": "Task description/details in roadmap-style wording."
                }
              ]
            }
          ]
        }
      ],
      "non_feature_items": [
        {
          "id": "NF1-M1",
          "title": "Checkpoint title",
          "reason": "Validation criterion, not a standalone feature."
        },
        {
          "id": "NS1-M1",
          "title": "Broad architecture statement",
          "reason": "Must be decomposed before feature/issue/task planning."
        }
      ]
    }
  ]
}
```
