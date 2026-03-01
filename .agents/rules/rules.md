---
trigger: always_on
glob:
description: General agent behavior and command style rules
---

## Multi-task execution requirements

1. Implement shared primitives first when tasks overlap.
2. Avoid duplicate logic across parallel modules.
3. Run one integration pass for the whole task bundle.

## Command style for bundles

Use this format for multi-task requests:

`Execute bundle: <taskA> -> <taskB> -> <taskC>, mode=strict, no-duplicate-logic`

