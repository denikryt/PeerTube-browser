# Task Execution Pipeline

This file is the coordination source of truth for multi-task execution.
Use it before implementing any task bundle.

## Recommended implementation order

### Execution sequence (recommended)
1. **37** (stable ANN IDs: `video_id+host -> int64`)  
   First establish stable ANN id contract before further similarity tuning.
2. **33** (video-page similars diversity + larger pools)  
   Build on finalized ANN/cache config and incremental recompute behavior.
3. **3** (video metadata completeness + refresh mutable fields)  
   Improves data quality on video page and creates better API/DB test baseline.
4. **1** then **2** (video-page UX flow for similars)  
   First fast initial response, then progressive loading/scroll behavior.
5. **4** (comments) and **9/9b** (description + single-like removal)  
   Video/profile UX improvements with low backend risk.
6. **12a** then **8b** (popular weighted-random + feed modes)  
   Finalize popular-layer behavior before exposing it as user-facing feed mode.
7. **10** (search page) and **8c** (about outbound analytics)  
   Mostly orthogonal product features.
8. **41** then **38** then **43** (timestamped lifecycle logs + request correlation + static-page visit logs)  
   Establish one logging contract first, then add request-id linked lifecycle logs, then extend observability to nginx-served static pages.
9. **16l** then **39** then **44** then **56** then **40** (cache runtime safety + similarity precompute scope + shadow swap + zero-downtime deploy)  
   Add background/atomic cache refresh primitives first, then startup no-downtime hardening, then similarity-cache precompute scoping, then shadow cutover, then blue/green nginx switch automation.
10. **57** (subtree split workflow + sync automation)  
    Formalize split push flow only after current service/runtime topology is stable.
11. **16**, **11** (docs + docstrings)  
   Finalize documentation polish after behavior/stability changes land.

### Functional blocks (aligned with the same order)
- **Block A: Similarity and recommendation core**
  - Tasks: **37 -> 33 -> 12a**
  - Scope: ANN/similarity defaults, impacted recompute, upnext diversity, popular-layer sampling quality.
  - Outcome: ANN switches to stable `ann_id` mapping, upnext refresh stops repeating the same 8 cards, and popular feed uses weighted-random by similarity instead of flat random sampling.
- **Block B: Video page data + UX behavior**
  - Tasks: **3 -> 1 -> 2 -> 4 -> 9 -> 9b**
  - Scope: metadata completeness, fast similar rendering, comments, profile/likes interactions.
  - Outcome: video page loads similars immediately (without waiting for remote metadata), renders progressive similars from one larger batch on scroll, shows tags/category with mutable-field refresh, supports read-only comments with pagination, has collapsible description, and allows removing one like instead of only full reset.
- **Block C: Feed and discovery product features**
  - Tasks: **8b -> 10 -> 15**
  - Scope: feed modes, search UX/API, crawler seed mode from one instance/subscriptions.
  - Outcome: home page gets explicit feed mode switch (`recommendations/hot/recent/random/popular`), backend exposes video search API (`/api/search/videos` with paging/sort), and crawler can start from one `--seed-instance` and expand through federated subscriptions.
- **Block D: Analytics and style infrastructure**
  - Tasks: **8c -> 8**
  - Scope: outbound click analytics and optional styling-system consolidation.
  - Outcome: About-page outbound links send tracked events to a dedicated API endpoint and SQLite analytics table (with validation/rate-limit path), while repeated styling patterns can be migrated to a shared Tailwind-based system for new blocks.
- **Block E: Documentation and maintenance**
  - Tasks: **16 -> 11**
  - Scope: recommendations docs alignment and missing docstrings.
  - Outcome: `RECOMMENDATIONS_OVERVIEW` is aligned with actual runtime pipeline (candidate generation/mixing/filters), and touched modules/functions/classes have explicit docstrings so behavior is readable without code archaeology.
- **Block F: Logging and observability**
  - Tasks: **41 -> 38 -> 43**
  - Scope: explicit timestamped request logs, request-id correlation across request lifecycle, and static-page visit visibility for About/Changelog.
  - Outcome: every API request gets `request-start -> work logs -> request-end` with one shared `request_id` and explicit timestamp format, and nginx adds dedicated visit logs for static `about/changelog` routes with request-correlation-compatible fields.
- **Block G: Runtime reliability and operations**
  - Tasks: **16l -> 39 -> 44 -> 56 -> 40 -> 57**
  - Scope: safe cache refresh/swap runtime behavior (random + similarity), scoped similarity precompute updates, and automated blue/green nginx cutover.
  - Outcome: random/similarity caches refresh via shadow files + atomic swap, updater similarity stage can rewrite scoped cache sources instead of full rebuilds, deploy script performs blue/green switch on `7070/7071` with health-check gate and rollback, and one sync command can split/push `engine` and `client` into separate subtree remotes.

### Cross-task overlaps and dependencies
- **1 <-> 2 <-> 33**: all touch video-page similar retrieval/rendering behavior.  
  Backend candidate quality/diversity (**33**) should be stable before final UX behavior (**1**, **2**).
- **8b <-> 12a**: both touch popular layer output behavior.  
  Weighted-random in popular should be finished before exposing/locking popular mode UX.
- **41 <-> 38**: same logging contract and request context propagation.  
  Introduce timestamp/log format first (**41**), then request lifecycle + shared request id (**38**) to avoid duplicate logging rewrites.
- **38 <-> 43**: both rely on cross-log correlation (`request_id`, timestamp conventions, runbook).  
  Implement request-trace contract first (**38**), then static-page visit visibility in nginx (**43**).
- **8c <-> 43**: both touch About-page observability and can overlap in intent (analytics vs logging).  
  Keep `8c` as event analytics and `43` as request log visibility to avoid duplicate instrumentation responsibilities.
- **38 <-> 40**: both touch nginx-facing request metadata (`X-Request-ID` propagation and operational config).  
  Keep request-id forwarding contract compatible with blue/green switch scripts and nginx templates.
- **16l <-> 39**: same random-cache runtime path (background refresh, atomic swap, locks).  
  Keep one cache refresh source of truth; implement startup non-blocking behavior on top of `16l` primitives.
- **39 <-> 44**: same operational primitives (shadow file build, atomic swap, lock-scoped reconnect).  
  Reuse one swap/reopen safety pattern across random and similarity cache paths.
- **44 <-> 56**: both touch updater similarity stage and cache rewrite behavior.  
  Land scoped rewrite behavior (**56**) before finalizing long-running shadow/cutover behavior (**44**) to avoid duplicate precompute rewrites.
- **44 <-> 40**: deploy orchestration and cache cutover both affect runtime availability windows.  
  Land in-process similarity cache cutover first, then finalize full blue/green deploy automation.
- **39 <-> 40**: deploy safety depends on fast readiness and warm startup behavior.  
  Zero-downtime cutover (**40**) should be implemented after random-cache startup hardening (**39**).
- **40 <-> 57**: both are operational automation tasks touching release workflow reliability.  
  Finalize runtime/deploy behavior first (**40**), then lock split/push automation contract (**57**) so remote repos mirror stable boundaries.
- **57 <-> 16/11**: subtree workflow adds commands and maintenance conventions that must be reflected in docs/docstrings.  
  Keep docs polish after subtree sync tooling lands to avoid repeated documentation rewrites.
- **16 / 11** depend on nearly all feature tasks.  
  Doing them earlier causes repeated rewrites.

## Multi-task execution protocol

Protocol is maintained in `TASK_EXECUTION_PROTOCOL.md`.
Use it for every multi-task bundle run together with this pipeline file.

## Update policy when a new task is added

Update policy is maintained in `TASK_EXECUTION_PROTOCOL.md`.

## Bundle command format

Use this command style when requesting multiple tasks:

`Execute bundle: <taskA> -> <taskB> -> <taskC>, mode=strict, no-duplicate-logic`
