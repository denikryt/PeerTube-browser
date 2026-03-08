---
description: Build or update issue-level overlaps through scoped discovery plus full-draft validation/apply
---
1. Run `python3 dev/workflow plan index-dependencies --feature-id <feature_id> --write` or `--issue-id <issue_id> --write`.
2. Run `python3 dev/workflow plan show-related --feature-id <feature_id>` or `--issue-id <issue_id>` to collect candidate issue pairs and matched surfaces for the requested seed scope.
3. Run `python3 dev/workflow plan get-plan-block --feature-id <feature_id>` or `--issue-id <issue_id>` to fetch Dependencies-only plan blocks for the candidate issues.
4. Read `Expected Behaviour` from the same candidate issue blocks in `dev/FEATURE_PLANS.md` so overlap type and description stay aligned with the declared runtime outcome.
5. Run `python3 dev/workflow plan show-overlaps --feature-id <feature_id>` or `--issue-id <issue_id>` to inspect current overlap rows for the same scope.
6. Optionally run `python3 dev/workflow plan build-overlaps --feature-id <feature_id> --delta-file tmp/workflow/<scope>-overlaps-draft.json` (or the issue-scoped variant) to capture discovery output, current overlaps, and current issue_execution_order as drafting context.
7. Prepare a full editable `ISSUE_OVERLAPS.json` draft snapshot:
   - start from the current `dev/ISSUE_OVERLAPS.json` payload,
   - add or update overlap rows for the analyzed scope,
   - keep unrelated existing overlap rows unless you are intentionally changing them,
   - edit `issue_execution_order.ordered_issue_ids` explicitly in the same draft.
8. For each overlap row in the final draft:
   - normalize `issues` to the canonical pair for that row,
   - choose `type`: `dependency`, `conflict`, or `shared_logic`,
   - if `type=dependency`, set `order: "<issue_a>-><issue_b>"`,
   - add `surface`,
   - add `description` with `why: ...; impact: ...; action: ...`.
9. Save the final full draft to JSON with the canonical root shape:
   - `schema_version`
   - `issue_execution_order`
   - `overlaps`
10. Run `python3 dev/workflow plan apply-overlaps --delta-file tmp/workflow/<scope>-overlaps-final.json --write`.
11. Stop if validation fails:
   - schema validation must pass for the full payload shape,
   - semantic validation must confirm referenced issue IDs exist, duplicate pair keys are absent, dependency orders match their pairs, and `issue_execution_order` matches the dependency-overlap participants and ordering.
