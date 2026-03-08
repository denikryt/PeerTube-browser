---
description: Build or update issue-level overlaps through CLI plus analysis workflow
---
> [!IMPORTANT]
> Input feature/issue IDs in this workflow are **seed scope**, not a hard limit on final overlap pairs.
> The workflow must:
> - start from the explicitly requested feature/issue scope,
> - discover all related issues through `index-dependencies` + `show-related`,
> - read plan blocks for those discovered candidates,
> - and produce overlaps for **all real intersections found from that discovered candidate set**.
>
> Do not reduce the result to only the inner pairs between explicitly named IDs unless the user asks for a narrow/manual pair-only operation explicitly.

1. Run `python3 dev/workflow plan index-dependencies --feature-id <feature_id> --write` or `--issue-id <issue_id> --write`.
2. Run `python3 dev/workflow plan show-related --feature-id <feature_id>` or `--issue-id <issue_id>` to collect candidate issue pairs and matched surfaces.
   - Treat this output as the expanded overlap-analysis scope.
   - If the seed scope is one or more issue IDs, the final overlap set still includes external related issues discovered from those seeds.
3. Run `python3 dev/workflow plan get-plan-block --feature-id <feature_id>` or `--issue-id <issue_id>` to fetch Dependencies-only plan blocks for the candidate issues.
   - Read plan blocks for all discovered candidate issues required to reason about the expanded overlap scope, not just the originally named seed IDs.
4. Read `Expected Behaviour` from the same candidate issue blocks in `dev/FEATURE_PLANS.md`.
   - Use it together with Dependencies so overlap classification does not contradict the declared runtime outcome for any issue in scope.
5. Run `python3 dev/workflow plan show-overlaps --feature-id <feature_id>` or `--issue-id <issue_id>` to inspect current overlap state for the same scope.
6. Run `python3 dev/workflow plan build-overlaps --feature-id <feature_id> --delta-file tmp/workflow/<scope>-overlaps-draft.json` or the issue-scoped variant to write the draft payload.
7. Read `tmp/workflow/<scope>-overlaps-draft.json`, analyze the candidate pairs, and enrich each final overlap row manually:
   - choose `type`: `dependency`, `conflict`, or `shared_logic`
   - if `type=dependency`, add `order: "<issue_a>-><issue_b>"`
   - add `surface`
   - add `description` with `why: ...; impact: ...; action: ...`
   - cross-check the chosen type and description against both Dependencies and Expected Behaviour,
   - keep every candidate pair that has a real code-level intersection or dependency chain in the expanded candidate set,
   - do not drop externally discovered pairs only because they were not in the original user-provided seed list.
8. Save the enriched payload back to a JSON file (for example `tmp/workflow/<scope>-overlaps-final.json`) with root shape `{ "overlaps": [ ... ] }`.
9. Run `python3 dev/workflow plan apply-overlaps --delta-file tmp/workflow/<scope>-overlaps-final.json --write`.
10. Review the command output and stop if overlap count or validation results do not match the expanded candidate scope discovered from the seeds.
