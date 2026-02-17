# Task Execution Pipeline

This file is the coordination source of truth for multi-task execution.
Use it before implementing any task bundle.

## Recommended implementation order

Block A (`35 -> 32 -> 31 -> 34 -> 36`) is completed and moved to `COMPLETED_TASKS.md`.
Task 45 is completed and moved to `COMPLETED_TASKS.md`.

### Execution sequence (recommended)
1. **50** (remove Engine users-like DB dependency in recommendation path)  
   Keep split architecture strict by using request likes + aggregated interaction signals only in Engine ranking flow.
2. **37** (stable ANN IDs: `video_id+host -> int64`)  
   First establish stable ANN id contract before further similarity tuning.
3. **30** (incremental similar cache + config defaults)  
   Stabilize ANN/similar precompute parameters before video-page similar tuning.
4. **33** (video-page similars diversity + larger pools)  
   Build on finalized ANN/cache config and incremental recompute behavior.
5. **3** (video metadata completeness + refresh mutable fields)  
   Improves data quality on video page and creates better API/DB test baseline.
6. **1** then **2** (video-page UX flow for similars)  
   First fast initial response, then progressive loading/scroll behavior.
7. **4** (comments) and **9/9b** (description + single-like removal)  
   Video/profile UX improvements with low backend risk.
8. **12a** then **8b** (popular weighted-random + feed modes)  
   Finalize popular-layer behavior before exposing it as user-facing feed mode.
9. **10** (search page) and **8c** (about outbound analytics)  
   Mostly orthogonal product features.
10. **41** then **38** then **43** (timestamped lifecycle logs + request correlation + static-page visit logs)  
   Establish one logging contract first, then add request-id linked lifecycle logs, then extend observability to nginx-served static pages.
11. **46** then **47** then **16l** then **39** then **44** then **40** (prod/dev installers + smoke tests + cache runtime safety + similarity shadow swap + zero-downtime deploy)  
   First establish contour-isolated Engine/Client installer primitives, then lock smoke coverage for installer/runtime interaction contracts, then add background/atomic cache refresh primitives, then startup no-downtime hardening, then similarity-cache shadow cutover, then blue/green nginx switch automation.
12. **16**, **11** (docs + docstrings)  
   Finalize documentation polish after behavior/stability changes land.
13. **42** (public roadmap changelog with status + client filters)  
   Implement after major feature blocks to avoid repeated migration/status churn while core tasks are still changing.

### Functional blocks (aligned with the same order)
- **Block A: Moderation and ingest control (completed)**
  - Tasks: **35 -> 32 -> 31 -> 34 -> 36**
  - Scope: permanent deny/block rules, purge tooling, guaranteed exclusion during sync/crawl/merge, and one integrated regression pass for the whole block.
- **Block B: Architecture split and federation readiness**
  - Tasks: **50**
  - Scope: finalize split contracts by removing Engine recommendation dependence on local users-like tables and keeping interaction-signal-driven ranking inputs.
- **Block C: Similarity and recommendation core**
  - Tasks: **37 -> 30 -> 33 -> 12a**
  - Scope: ANN/similarity defaults, impacted recompute, upnext diversity, popular-layer sampling quality.
- **Block D: Video page data + UX behavior**
  - Tasks: **3 -> 1 -> 2 -> 4 -> 9 -> 9b**
  - Scope: metadata completeness, fast similar rendering, scrolling behavior, comments, profile/likes interactions.
- **Block E: Feed and discovery product features**
  - Tasks: **8b -> 10 -> 15**
  - Scope: feed modes, search UX/API, crawler seed mode from one instance/subscriptions.
- **Block F: Analytics and style infrastructure**
  - Tasks: **8c -> 8**
  - Scope: outbound click analytics and optional styling-system consolidation.
- **Block G: Documentation and maintenance**
  - Tasks: **16 -> 11**
  - Scope: recommendations docs alignment and missing docstrings.
- **Block H: Logging and observability**
  - Tasks: **41 -> 38 -> 43**
  - Scope: explicit timestamped request logs, request-id correlation across request lifecycle, and static-page visit visibility for About/Changelog.
- **Block I: Runtime reliability and operations**
  - Tasks: **46 -> 47 -> 16l -> 39 -> 44 -> 40**
  - Scope: contour-isolated prod/dev service installers for Engine+Client, smoke coverage for install/runtime interaction contracts, safe cache refresh/swap runtime behavior (random + similarity), and automated blue/green nginx cutover.
- **Block J: Public roadmap and changelog UX**
  - Tasks: **42**
  - Scope: roadmap-style public changelog entries with task statuses and client-side completed/not-completed filters.

### Cross-task overlaps and dependencies
- **50 <-> 3/1/2/4/9/9b/8b/10**: these tasks rely on stable API boundaries and request ownership.  
  Keep post-split contracts strict to avoid repeated rewrites of routes and service responsibilities.
- **50 <-> 30/33/12a**: similarity/recommendation tuning should use final signal-source contract.  
  Land **50** before core recommendation tuning to prevent duplicate rewrites across source/feature selection logic.
- **50 <-> 38/41/43**: request tracing/logging spans multiple services after split and should reflect final recommendation input sources.  
  Keep correlated logging conventions aligned with post-50 Engine/Client runtime behavior.
- **50 <-> 46/47/16l/39/44/40**: runtime/deploy automation and smoke checks should target the finalized signal-source contract as well.  
  Keep installer/smoke/runtime hardening aligned with post-50 Engine/Client behavior to avoid service-level rework.
- **46 <-> 47**: smoke tests validate the installer contracts directly (unit names, ports, timer modes, cleanup guarantees).  
  Land installer contour and unit naming contracts first to avoid immediate smoke test rewrites.
- **47 <-> 39/44/40**: runtime/deploy changes can affect smoke assumptions and readiness/interaction checks.  
  Keep smoke scripts aligned with post-installer runtime contracts to avoid flaky operational verification.
- **37 <-> 30 <-> 33**: same ANN/similarity core and ID contracts.  
  Stable ANN id source (**37**) must land before tuning/recompute behavior (**30**, **33**) to avoid duplicate rewrites.
- **30 <-> 33**: same ANN/similarity knobs (`top-k`, `nprobe`, precompute behavior).  
  Implement config source-of-truth first in **30**, then tuning/diversity in **33**.
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
- **30 <-> 44**: both touch similarity precompute behavior and cache DB lifecycle.  
  Stabilize incremental similarity contracts in **30** before introducing shadow-cache cutover in **44**.
- **39 <-> 44**: same operational primitives (shadow file build, atomic swap, lock-scoped reconnect).  
  Reuse one swap/reopen safety pattern across random and similarity cache paths.
- **44 <-> 40**: deploy orchestration and cache cutover both affect runtime availability windows.  
  Land in-process similarity cache cutover first, then finalize full blue/green deploy automation.
- **39 <-> 40**: deploy safety depends on fast readiness and warm startup behavior.  
  Zero-downtime cutover (**40**) should be implemented after random-cache startup hardening (**39**).
- **42 <-> AGENTS / TASK state management**: same operational contract for how completion is reflected publicly.  
  Update changelog workflow and instructions together to avoid conflicting write rules.
- **42** should land late in the sequence.  
  It changes public task-tracking format; doing it early causes repeated migrations while many tasks are still moving between planned/in-progress/done.
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
