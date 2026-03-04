---
description: Persist local Issue -> Task decomposition across trackers
---
1. Analyze existing bindings: Review `dev/map/DEV_MAP.json` to prepare candidate targets for tasks.
2. Read the code before drafting tasks:
   - Open and read the real runtime files, handlers, modules, schemas, docs, and tests touched by each issue in scope.
   - Do not decompose tasks from plan text alone; task decomposition must be grounded in the current codebase state.
3. Formulate Task Scopes from code findings:
   - For each issue, define minimal-sufficient task scopes tied to concrete files and code paths.
   - Mandatory `concrete_steps` must describe exact changes such as what to remove, what to add, what to rename, what to move, and what to validate.
   - Do not write generic tasks like "implement issue scope" or "refine behavior" without naming the concrete code changes.
4. Derive overlaps from code, not from vague topic similarity:
   - Add overlaps only when tasks actually touch the same files, shared primitives, shared parser/handler paths, or one dependency chain in the code.
   - Overlap descriptions must state the concrete shared surface that creates the risk of duplication, drift, or ordering constraints.
   - A short generalized summary is allowed after the concrete basis, but the overlap may not rely on generalized wording alone.
5. Ensure task marker correctness: Formulate `[M*][F*]` or `[M*][SI*]` strings for tasks based on their parent chain.
6. Quality Check: Verify compliance with **Gate B: Pre-sync (local decomposition)** in `.agents/protocols/feature-planning-protocol.md`.
7. Only after task decomposition is completely mapped out conceptually from code evidence and quality check is passed, utilize the CLI to synchronize everything.

// turbo
8. Run: `python3 dev/workflow plan tasks --feature-id <feature_id>` OR `python3 dev/workflow plan tasks --issue-id <issue_id> ...`

9. Review the synced tasks in `dev/TASK_LIST.json` to ensure `concrete_steps`, markers, and overlap-derived pipeline entries reflect the actual code-informed decomposition.
10. Stop and use `notify_user` with `BlockedOnUser=true` to await explicitly synced local decomposition review.
