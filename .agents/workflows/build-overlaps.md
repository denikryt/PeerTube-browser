---
description: Build or update issue-level overlaps through CLI plus analysis workflow
---
1. Run `python3 dev/workflow plan index-dependencies --feature-id <feature_id> --write` or `--issue-id <issue_id> --write`.
2. Run `python3 dev/workflow plan show-related --feature-id <feature_id>` or `--issue-id <issue_id>` to collect candidate issue pairs and matched surfaces.
3. Run `python3 dev/workflow plan get-plan-block --feature-id <feature_id>` or `--issue-id <issue_id>` to fetch Dependencies-only plan blocks for the candidate issues.
4. Run `python3 dev/workflow plan show-overlaps --feature-id <feature_id>` or `--issue-id <issue_id>` to inspect current overlap state for the same scope.
5. Run `python3 dev/workflow plan build-overlaps --feature-id <feature_id> --delta-file tmp/workflow/<scope>-overlaps-draft.json` or the issue-scoped variant to write the draft payload.
6. Read `tmp/workflow/<scope>-overlaps-draft.json`, analyze the candidate pairs, and enrich each final overlap row manually:
   - choose `type`: `dependency`, `conflict`, or `shared_logic`
   - if `type=dependency`, add `order: "<issue_a>-><issue_b>"`
   - add `surface`
   - add `description` with `why: ...; impact: ...; action: ...`
7. Save the enriched payload back to a JSON file (for example `tmp/workflow/<scope>-overlaps-final.json`) with root shape `{ "overlaps": [ ... ] }`.
8. Run `python3 dev/workflow plan apply-overlaps --delta-file tmp/workflow/<scope>-overlaps-final.json --write`.
9. Review the command output and stop if overlap count or validation results do not match the intended scope.
