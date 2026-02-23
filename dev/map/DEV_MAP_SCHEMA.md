# DEV_MAP Schema

Canonical hierarchy:

`Milestone -> Feature -> Issue -> Task`

Allowed status values for nodes with status fields (`Feature`, `Issue`, `Task`):
- `Planned`
- `Done`

Milestone nodes do not have a `status` field.

## ID Rules

- Milestone ID: `M<global_number>`
  - example: `M1`, `M2`
- Feature ID (local to milestone, with dash format): `F<local_number>-M<milestone_number>`
  - example: `F1-M1`, `F2-M1`
- Issue ID (local to feature, with dash format): `I<local_number>-F<feature_local_number>-M<milestone_number>`
  - example: `I1-F1-M1`, `I2-F1-M1`
- Task ID: global task id from `dev/TASK_LIST.md`
  - examples: `58`, `8b`, `16l`

## Example A: Current minimal state (milestones only)

```json
{
  "schema_version": "1.0",
  "statuses": ["Planned", "Done"],
  "updated_at": "2026-02-23T23:45:00+02:00",
  "milestones": [
    {
      "id": "M1",
      "title": "Baseline contour and validation",
      "features": []
    }
  ]
}
```

## Example B: Full hierarchy template (empty placeholders)

```json
{
  "schema_version": "1.0",
  "statuses": ["Planned", "Done"],
  "updated_at": "YYYY-MM-DDTHH:MM:SS+TZ:TZ",
  "milestones": [
    {
      "id": "M1",
      "title": "Milestone title",
      "features": [
        {
          "id": "F1-M1",
          "title": "Feature title",
          "status": "Planned",
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
                  "title": "Task title",
                  "status": "Planned"
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```
