# Recommendation Compatibility

## Purpose

This document records compatibility decisions made while clarifying the recommendation pipeline internals. These decisions preserve current Engine/Frontend behavior while ownership of configuration and internal boundary types becomes easier to understand.

## `server_config.py` re-exports recommendation config

Decision:
`engine/server/api/recommendations/config.py` owns `RECOMMENDATION_PIPELINE`, `DEFAULT_POPULAR_POOL_SIZE`, `DEFAULT_FRESH_POOL_SIZE`, and recommendation config validation. `engine/server/api/server_config.py` still re-exports those names.

Reason:
Existing startup code, tests, and operational assumptions import recommendation defaults from `server_config.py`. Moving ownership without re-exports would be a breaking import change unrelated to recommendation behavior.

Implementation action:
Keep compatibility imports in `server_config.py` and compute `BATCH_SIZE` from the moved pipeline exactly as before.

Tests:
`tests/recommendations/test_config_validation.py` compares the legacy `server_config.RECOMMENDATION_PIPELINE` import to the new recommendation-domain import.

Removal condition, if any:
The re-export can be removed only after all imports and docs use `recommendations/config.py` directly and a dedicated compatibility-removal plan covers startup and deployment impact.

## Validation uses raw config for runtime execution

Decision:
Stage 5 validates the checked-in Python config but continues to pass the raw dictionary into `MixingRecommendationStrategy` and generator code.

Reason:
The mixer and generators currently rely on dictionary fallback behavior. Executing from typed validation objects could change missing-field defaults, profile inheritance, generator order, or truthiness behavior.

Implementation action:
Call `validate_recommendation_config(config)` before strategy construction, then pass the original raw `config` into the existing strategy constructor.

Tests:
`tests/recommendations/test_config_validation.py` validates defaults and rejects malformed config. Existing recommendation characterization tests continue to protect scoring, filtering, mixing, and profile behavior.

Removal condition, if any:
Typed runtime execution can replace raw dictionaries only in a later stage that covers generator/mixer behavior with before-and-after characterization tests.

## `RecommendationResult.to_response()` preserves response shape

Decision:
`RecommendationResult` is an internal adapter object whose `to_response()` method emits the existing primitive Engine response fields: `generatedAt`, `total`, `count`, `seed`, and `rows`.

Reason:
The public recommendation response is consumed by frontend and Client gateway behavior. Stage 5 may clarify service boundaries but must not introduce public schemas or response-shape changes.

Implementation action:
Use `RecommendationResult` only at the response assembly boundary and pass the existing embedding total explicitly where route behavior currently reports `server.embeddings_count`.

Tests:
`tests/recommendations/test_types_characterization.py` covers default row-count totals and explicit existing embedding totals. Engine route tests continue to cover route-level response behavior.

Removal condition, if any:
No removal is planned. Any public response redesign requires a separate behavior-change plan.

## Debug metadata public shape remains unchanged

Decision:
Debug metadata remains externally compatible. Stage 5 does not change `attach_debug_info()` output keys.

Reason:
Debug output is a diagnostics contract used to inspect recommendation behavior. Changing it during internal cleanup would hide recommendation regressions.

Implementation action:
Keep debug source rows dictionary-based in Stage 5 and continue adapting them through `recommendations/debug.py`.

Tests:
`tests/recommendations/test_types_characterization.py` asserts representative public debug keys still map from current source dictionaries.

Removal condition, if any:
Internal debug storage can change only when a later plan preserves or explicitly migrates the public debug block.

## External YAML/JSON recommendation config is deferred

Decision:
Stage 5 does not add `engine/server/config/recommendations.default.yaml`, JSON schema files, or runtime file loading.

Reason:
External files would add packaging, lookup-path, deployment, and startup failure modes. The current goal is a Python-level validation boundary, not a config delivery system.

Implementation action:
Keep checked-in config in Python and document external config loading as future work.

Tests:
The absence of file loading is covered indirectly by fast tests and by keeping `server.py` startup behavior unchanged.

Removal condition, if any:
External config files can be introduced only after a dedicated dependency/config-loading plan defines lookup paths, defaults, deployment packaging, and fallback behavior.
