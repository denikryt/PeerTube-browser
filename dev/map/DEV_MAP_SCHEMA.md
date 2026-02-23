# DEV_MAP Schema

Canonical hierarchy:

`Milestone -> Feature -> Issue -> Task`

Allowed status values for nodes with status fields (`Feature`, `Issue`, `Task`):
- `Planned`
- `Done`

Milestone nodes do not have a `status` field.

## Milestone Metadata

Milestone nodes include metadata fields used for planning context and classification:
- `goal`: milestone goal text.
- `features`: list of feature nodes.
- `non_feature_items`: list of milestone items that are not feature nodes.
  - `classification`:
    - `not_feature` (checkpoint/validation criterion),
    - `needs_split` (too broad and must be decomposed before becoming feature/issue).

## ID Rules

- Milestone ID: `M<global_number>`
  - example: `M1`, `M2`
- Feature ID (local to milestone, with dash format): `F<local_number>-M<milestone_number>`
  - example: `F1-M1`, `F2-M1`
- Issue ID (local to feature, with dash format): `I<local_number>-F<feature_local_number>-M<milestone_number>`
  - example: `I1-F1-M1`, `I2-F1-M1`
- Task ID: global task id from `dev/TASK_LIST.md`
  - examples: `58`, `8b`, `16l`
- Non-feature item ID (local to milestone): `NF<local>-M<milestone_number>` or `NS<local>-M<milestone_number>`
  - examples: `NF1-M1`, `NS1-M5`

## Example A: Current minimal state (milestones only)

```json
{
  "schema_version": "1.1",
  "statuses": ["Planned", "Done"],
  "updated_at": "2026-02-23T23:45:00+02:00",
  "milestones": [
    {
      "id": "M1",
      "title": "Baseline contour and validation",
      "goal": "Milestone goal",
      "non_feature_items": [],
      "features": []
    }
  ]
}
```

## Example B: Full hierarchy template (empty placeholders)

```json
{
  "schema_version": "1.1",
  "statuses": ["Planned", "Done"],
  "updated_at": "YYYY-MM-DDTHH:MM:SS+TZ:TZ",
  "milestones": [
    {
      "id": "M1",
      "title": "Milestone title",
      "goal": "Milestone goal",
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
                  "title": "Task title",
                  "status": "Planned"
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
          "classification": "not_feature",
          "kind": "integration_checkpoint",
          "reason": "Validation criterion, not a standalone feature."
        },
        {
          "id": "NS1-M1",
          "title": "Broad architecture statement",
          "classification": "needs_split",
          "kind": "architecture_scope",
          "reason": "Must be decomposed before feature/issue/task planning."
        }
      ]
    }
  ]
}
```
