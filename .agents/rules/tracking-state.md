---
trigger: always_on
glob:
description: Runtime tracking-state rules
---

1. Do not mark a feature or issue `Done` until the user explicitly requests completion.
2. `done feature <id>` and `done issue <id>` are the canonical completion actions.
3. Remote completion side effects must run only when `--remote` is explicitly provided.
4. Keep `dev/FEATURE_PLANS.md`, `dev/map/DEV_MAP.json`, and runtime command semantics aligned when lifecycle rules change.
