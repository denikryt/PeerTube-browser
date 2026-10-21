# Stage 5: Clarify Recommendation Pipeline Internals

## Problem / Goal

Stage 5 clarifies the recommendation pipeline internals without changing recommendation behavior. The current Stage 4 state has already split Engine HTTP routing from route/service orchestration, but the recommendation domain still relies on loosely shaped dictionaries, a large `RECOMMENDATION_PIPELINE` literal in `engine/server/api/server_config.py`, and helper functions whose responsibilities are partly implicit.

The goal is to make recommendation behavior easier to read, validate, and tune while preserving current output ordering, response fields, profile selection, debug metadata, candidate source behavior, and default configuration values.

Current recommendation flow after Stage 4:

```text
Engine route adapters
  -> engine/server/api/services/recommendation_service.py
      -> engine/server/api/recommendations/builder.py
          -> candidates/* generators
          -> sources/* similar-from-likes sources
          -> mixer.MixingRecommendationStrategy
              -> profile resolution
              -> generator fetch limits
              -> scoring
              -> layer mixing
              -> dedup / caps / soft caps
      -> stable response rows / optional debug attachment
```

Current pain points found in the real codebase:

- `engine/server/api/server_config.py` still owns the large recommendation pipeline dictionary even though recommendation-specific configuration is a recommendation-domain concern.
- `RECOMMENDATION_PIPELINE` currently has no validation boundary; malformed ratios, unknown generator names, negative limits, or invalid profile references would fail later or change behavior silently.
- Recommendation request, candidate, scoring, and result shapes are passed as plain dictionaries across service and mixer boundaries.
- Debug metadata is still written directly onto candidate dictionaries and then mapped into response debug blocks by `recommendations/debug.py`.
- Recommendation docs still point at `engine/server/api/server_config.py` as the config source.
- Stage 0 tests cover current scoring/filtering/mixing/profile behavior, but Stage 5 needs stronger tests around config validation and typed boundary objects before moving configuration ownership.

Stage 5 is not a recommendation quality redesign. It must preserve the existing pipeline semantics and make the current behavior explicit.

## Expected Behavior

After Stage 5:

- `RECOMMENDATION_PIPELINE` still has the same effective default values and profile names:
  - `home`
  - `guest_home`
  - `upnext`
  - `guest_upnext`
- Current generator names remain compatible:
  - `random`
  - `popular`
  - `explore`
  - `exploit`
  - `fresh`
- The server still builds the recommendation strategy during startup using the same runtime defaults and the same generator implementation classes.
- `/recommendations`, `/videos/similar`, and `/videos/{id}/similar` keep their current response shape, ordering behavior, debug behavior, body-size validation, likes validation, profile resolution, and error behavior.
- `BATCH_SIZE` remains equal to the current home profile batch size.
- `DEFAULT_POPULAR_POOL_SIZE` and `DEFAULT_FRESH_POOL_SIZE` keep their current numeric values and are still available to startup imports.
- Recommendation code can be read in this order:

```text
request route/service
  -> typed request/context boundary objects
  -> validated recommendation config
  -> candidate generator builder
  -> candidate generation
  -> scoring
  -> mixing
  -> response adapter
```

Concrete preserved examples:

```python
from engine.server.api.server_config import RECOMMENDATION_PIPELINE, BATCH_SIZE

assert RECOMMENDATION_PIPELINE["default_profile"] == "home"
assert BATCH_SIZE == RECOMMENDATION_PIPELINE["profiles"]["home"]["batch_size"]
```

This compatibility import path must continue to work in Stage 5, even if the source of the dictionary moves to `engine/server/api/recommendations/config.py`.

```json
{
  "mode": "home",
  "likes": [{"uuid": "uuid-1", "host": "example.org"}],
  "debug": false
}
```

A recommendation request with client-provided likes must still resolve likes through the current Engine video identity path and return the current `generatedAt`, `total`, `count`, `seed`, and `rows` fields.

```json
{"debug": true}
```

Debug output must remain externally compatible. Stage 5 may introduce internal debug metadata helpers or typed debug containers only if `recommendations/debug.py` still emits the same public debug block shape.

## Architecture

Stage 5 owns only the recommendation domain internals and recommendation-domain configuration boundary.

### Stage 5 responsibility

```text
engine/server/api/recommendations/config.py
  owns recommendation defaults, config cloning, and validation helpers

engine/server/api/recommendations/types.py
  owns internal dataclasses / typed aliases for request, context, candidates, scores, and result boundaries

engine/server/api/recommendations/builder.py
  continues to build generator strategy from validated config

engine/server/api/recommendations/mixer.py
  continues to execute current generator limit, scoring, layer schedule, fallback, dedup, and soft-cap behavior

engine/server/api/recommendations/scoring.py
  continues to compute current score/debug fields

engine/server/api/recommendations/debug.py
  continues to adapt internal debug details to the existing public response debug shape

engine/server/api/services/recommendation_service.py
  may use typed request/context/result objects at the service boundary, but remains responsible for route-service orchestration and response assembly
```

### Explicitly out of scope

Stage 5 must not:

- change Engine route modules or HTTP paths beyond narrow imports to the clarified recommendation internals;
- change `SimilarHandler` request lifecycle, rate limiting, logging, CORS, or dispatch behavior;
- move Engine startup, FAISS/index loading, DB connection setup, random cache setup, or CLI behavior;
- change SQL, schema, migration ownership, or data access query semantics;
- change candidate generator algorithms, similarity source algorithms, random/recent/popular data retrieval, or ANN/cache policy behavior;
- change frontend, Client backend, crawler, updater jobs, installer scripts, or deployment behavior;
- introduce external YAML/JSON config loading in Stage 5;
- introduce Pydantic/OpenAPI schemas or public API schema redesign;
- introduce recommendation quality changes such as new weights, new profiles, new generators, or new ranking formulas.

### Remaining ownership after Stage 5

After Stage 5, these responsibilities intentionally remain outside Stage 5 and are not gaps:

```text
Engine route/service ownership:
  remains in Stage 4 route/service modules.

DB schema and migration ownership:
  remains for Stage 6.

Crawler/data-build ownership:
  remains for Stage 7.

Frontend rendering and state:
  remains for Stage 8.

Updater/deployment behavior:
  remains for Stage 9.

FastAPI/framework migration:
  remains for Stage 10 or another dedicated framework plan.

External YAML/JSON recommendation config loading:
  deferred until after Python-level config validation is stable.
```

## Touched Files

```text
AGENTS.md
Makefile
docs/DEVELOPMENT.md
docs/TESTING.md
docs/ENGINE_API_COMPATIBILITY.md
engine/server/api/server.py
engine/server/api/server_config.py
engine/server/api/services/recommendation_service.py
engine/server/api/recommendations/__init__.py
engine/server/api/recommendations/builder.py
engine/server/api/recommendations/debug.py
engine/server/api/recommendations/filters.py
engine/server/api/recommendations/mixer.py
engine/server/api/recommendations/profile.py
engine/server/api/recommendations/scoring.py
engine/server/api/recommendations/docs/OVERVIEW.md
engine/server/api/recommendations/docs/LAYER_PARAMS.md
engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md
tests/engine_api/test_recommendations_request_contract.py
tests/engine_api/test_similar_route_characterization.py
tests/recommendations/test_scoring_characterization.py
tests/recommendations/test_filters_characterization.py
tests/recommendations/test_mixer_characterization.py
tests/recommendations/test_profile_characterization.py
```

Stage 5 should edit only the subset needed for the implementation. `engine/server/api/server.py` should only need import-path compatibility adjustments if `server_config.py` re-exports are not enough; changing startup behavior is out of scope.

## New Files

```text
plans/07_stage_5_recommendation_pipeline_internals.md
docs/RECOMMENDATION_COMPATIBILITY.md
engine/server/api/recommendations/config.py
engine/server/api/recommendations/types.py
tests/recommendations/test_config_validation.py
tests/recommendations/test_types_characterization.py
```

Optional only if implementation becomes clearer without behavior change:

```text
engine/server/api/recommendations/validation.py
```

Do not create these files in Stage 5:

```text
engine/server/config/recommendations.default.yaml
engine/server/config/recommendations.schema.json
```

Those external config files are intentionally deferred. Stage 5 creates a Python validation boundary first.

## Implementation Steps

### 1. Confirm baseline before touching recommendation internals

Run:

```bash
make test
make lint
python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit
```

Expected current behavior:

- `make test` passes.
- `make lint` passes.
- legacy recommendation likes-limit unittest passes after Stage 4 service split.

Do not treat `python3 engine/server/api/server.py --help` as a required Stage 5 check because FAISS remains a known startup prerequisite and Stage 5 must not change that.

### 2. Add config validation tests before moving config ownership

Add `tests/recommendations/test_config_validation.py`.

Required tests:

#### 2.1 Default config validation passes and preserves current values

```python
from recommendations.config import RECOMMENDATION_PIPELINE, validate_recommendation_config

validated = validate_recommendation_config(RECOMMENDATION_PIPELINE)
assert validated.default_profile == "home"
assert set(validated.profiles) >= {"home", "guest_home", "upnext", "guest_upnext"}
assert validated.profiles["home"].batch_size == 48
assert validated.profiles["home"].generators["exploit"].mix_ratio == 0.5
```

#### 2.2 Legacy server_config import compatibility remains

```python
from server_config import RECOMMENDATION_PIPELINE as legacy_pipeline
from recommendations.config import RECOMMENDATION_PIPELINE as domain_pipeline

assert legacy_pipeline == domain_pipeline
```

#### 2.3 Unknown default profile is rejected

Input:

```python
{"default_profile": "missing", "profiles": {"home": {"batch_size": 48, "generators": {}}}}
```

Expected validation error contains:

```text
default_profile
missing
```

#### 2.4 Unknown mixing order generator is rejected

Input profile:

```python
{
  "batch_size": 10,
  "generators": {"random": {"enabled": True, "mix_ratio": 1.0}},
  "mixing": {"order": ["random", "missing"]}
}
```

Expected validation error contains:

```text
mixing.order
missing
```

#### 2.5 Negative numeric limits are rejected

Examples:

```python
{"batch_size": -1}
{"generators": {"random": {"pool_size": -1}}}
{"generators": {"random": {"max_per_author": -1}}}
```

Expected validation error names the offending path.

#### 2.6 Bad ratios are rejected

Examples:

```python
{"generators": {"random": {"gather_ratio": -0.1}}}
{"generators": {"random": {"mix_ratio": -0.1}}}
```

Expected validation error names `gather_ratio` or `mix_ratio`.

#### 2.7 Unknown generator names are rejected except for documented current generator names

Allowed generator names:

```text
random
popular
explore
exploit
fresh
```

Input with `"mystery": {"enabled": True}` must fail with an error containing `mystery`.

### 3. Add typed-boundary characterization tests

Add `tests/recommendations/test_types_characterization.py`.

Required tests:

#### 3.1 RecommendationRequest preserves route/service fields without public schema changes

Create a dataclass or typed object that can represent the current service request boundary:

```python
RecommendationRequest(
    path="/recommendations",
    method="POST",
    params={},
    body={"likes": [{"uuid": "uuid-1", "host": "example.org"}], "mode": "home"},
    user_id="local-user",
    limit=48,
    mode="home",
    debug=False,
    refresh=False,
)
```

Assert that the object is internal-only and can convert to primitive values used by the current service path without altering request semantics.

#### 3.2 RecommendationResult preserves response adapter fields

Create a result object for:

```python
RecommendationResult(
    rows=[{"video_id": "v1", "title": "Example"}],
    seed={"mode": "home"},
    generated_at=123,
)
```

Assert adapter output includes the same current top-level fields expected by Engine route tests:

```text
generatedAt
total
count
seed
rows
```

#### 3.3 Candidate debug metadata remains separate internally but adaptable externally

If Stage 5 introduces a typed debug object, assert that `recommendations/debug.py` still emits the current public debug keys. If Stage 5 does not introduce a debug type, add a characterization test documenting that debug still flows through candidate dictionaries and is deferred.

### 4. Move recommendation config ownership to `recommendations/config.py`

Create `engine/server/api/recommendations/config.py`.

Required contents:

- `DEFAULT_POPULAR_POOL_SIZE = 5000`
- `DEFAULT_FRESH_POOL_SIZE = 5000`
- `ALLOWED_GENERATORS = {"random", "popular", "explore", "exploit", "fresh"}`
- `RECOMMENDATION_PIPELINE` copied from the current `server_config.py` with identical values.
- `RecommendationConfigError(ValueError)`.
- `validate_recommendation_config(config: Mapping[str, Any]) -> ValidatedRecommendationConfig`.
- `clone_recommendation_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]`.

The validator must return internal dataclasses from `recommendations/types.py`, not mutate the input dictionary.

Minimum validated dataclasses:

```python
@dataclass(frozen=True)
class ValidatedGeneratorConfig:
    name: str
    enabled: bool
    gather_ratio: float
    mix_ratio: float
    raw: Mapping[str, Any]

@dataclass(frozen=True)
class ValidatedProfileConfig:
    name: str
    batch_size: int | None
    overfetch_factor: float
    generators: Mapping[str, ValidatedGeneratorConfig]
    mixing_order: tuple[str, ...]
    raw: Mapping[str, Any]

@dataclass(frozen=True)
class ValidatedRecommendationConfig:
    default_profile: str | None
    profiles: Mapping[str, ValidatedProfileConfig]
    raw: Mapping[str, Any]
```

Validation rules:

- `profiles`, when present, must be a mapping.
- `default_profile`, when present, must exist in `profiles`.
- profile config must be a mapping.
- `batch_size`, when present, must be an integer >= 0.
- `overfetch_factor`, when present, must be numeric >= 0.
- `generators` or legacy `layers`, when present, must be a mapping.
- every generator name must be one of `ALLOWED_GENERATORS`.
- generator config must be a mapping.
- `enabled`, when present, must be bool-like only if already accepted by current code; if current code treats any truthy value as enabled, Stage 5 must not reject existing default values but may reject obviously invalid container values.
- `gather_ratio` and `mix_ratio`, when present, must be numeric >= 0.
- numeric limits such as `pool_size`, `max_per_instance`, `max_per_author`, `similarity_min`, `similarity_max`, `exploit_min`, and `explore_min`, when present, must be numeric and non-negative.
- `mixing.order`, when present, must list only configured generators.
- `scoring.weights`, when present, must contain non-negative numeric values.
- `scoring.layer_weights`, when present, must reference allowed generator names and contain numeric values.
- `soft_caps.max` and `soft_caps.min`, when present, must reference configured generators and contain non-negative integer values.

Validation action on startup:

- `server_config.py` should call validation at import time for the default config or expose a validated constant so malformed checked-in defaults fail fast.
- This is a behavior-preserving startup safety check; it must pass with the existing default config.

### 5. Preserve legacy import compatibility through `server_config.py`

Update `engine/server/api/server_config.py` so that:

```python
from recommendations.config import (
    DEFAULT_FRESH_POOL_SIZE,
    DEFAULT_POPULAR_POOL_SIZE,
    RECOMMENDATION_PIPELINE,
    validate_recommendation_config,
)
```

or equivalent fallback imports work both when imported as a package and when server files are executed directly from `engine/server/api`.

`server_config.py` must continue to export:

```text
DEFAULT_POPULAR_POOL_SIZE
DEFAULT_FRESH_POOL_SIZE
RECOMMENDATION_PIPELINE
BATCH_SIZE
```

`BATCH_SIZE` must still be computed as:

```python
BATCH_SIZE = RECOMMENDATION_PIPELINE["profiles"]["home"]["batch_size"]
```

No other non-recommendation constants in `server_config.py` should move in Stage 5.

### 6. Introduce internal recommendation boundary types without changing external payloads

Create `engine/server/api/recommendations/types.py`.

Required public internal types:

```python
@dataclass(frozen=True)
class RecommendationRequest:
    path: str
    method: str
    params: Mapping[str, list[str]]
    body: Mapping[str, Any] | None
    user_id: str
    limit: int
    mode: str | None
    debug: bool
    refresh: bool

@dataclass(frozen=True)
class RecommendationContext:
    request_id: str
    user_id: str
    mode: str | None
    client_likes: tuple[Mapping[str, Any], ...]
    resolved_likes: tuple[Mapping[str, Any], ...]

@dataclass(frozen=True)
class RecommendationResult:
    rows: tuple[Mapping[str, Any], ...]
    seed: Mapping[str, Any] | None
    generated_at: int

    def to_response(self) -> dict[str, Any]:
        ...
```

`to_response()` must preserve the current route response shape:

```python
{
    "generatedAt": generated_at,
    "total": len(rows),
    "count": len(rows),
    "seed": seed,
    "rows": list(rows),
}
```

These are internal service/recommendation boundary types only. They must not be exposed as public API schemas, Pydantic models, or OpenAPI contracts in Stage 5.

Candidate-related types may be introduced only if they wrap current dictionaries without forcing generator rewrites. Acceptable:

```python
CandidateRow = dict[str, Any]
LayerName = Literal["random", "popular", "explore", "exploit", "fresh"]
```

Do not rewrite all generator functions to consume dataclasses in Stage 5. That would be a behavior-risking redesign.

### 7. Apply validation in builder or strategy construction without changing strategy behavior

In `engine/server/api/recommendations/builder.py`, validate the config before building the strategy:

```python
from recommendations.config import validate_recommendation_config

validate_recommendation_config(config)
```

The returned typed validation object may be used for checks, but `MixingRecommendationStrategy` should continue to receive the original raw dictionary in Stage 5 so current dictionary lookups and fallback behavior remain unchanged.

This deliberately separates validation from behavior execution:

```text
validated config -> prove config is sane
raw config -> preserve existing runtime behavior
```

Do not change generator order, ratio math, soft-cap logic, scoring formula, or fallback behavior in Stage 5.

### 8. Use typed result objects only at safe response-adapter boundaries

In `engine/server/api/services/recommendation_service.py`, use `RecommendationResult` only where the service already assembles the response dictionary. Do not push typed objects into generator/mixer internals unless the change is mechanically local and covered by existing tests.

Acceptable example:

```python
result = RecommendationResult(rows=tuple(stable_rows), seed=seed, generated_at=now_ms())
respond_json(handler, result.to_response())
```

Unacceptable in Stage 5:

```text
rewrite candidate generators to return Candidate dataclasses
rewrite mixer schedules around new object models
change debug metadata storage and output shape
```

### 9. Keep debug metadata externally compatible

If Stage 5 separates debug metadata internally, `recommendations/debug.py` must still accept the current source-row shape or an adapter that produces the same public debug block.

Required action:

- Run existing debug-mode route tests.
- Add or extend a recommendation debug test only if the implementation moves debug fields.
- Document the compatibility decision in `docs/RECOMMENDATION_COMPATIBILITY.md`.

### 10. Update recommendation docs

Update:

```text
engine/server/api/recommendations/docs/OVERVIEW.md
engine/server/api/recommendations/docs/LAYER_PARAMS.md
engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md
```

Required documentation changes:

- config source becomes `engine/server/api/recommendations/config.py`, not `engine/server/api/server_config.py`;
- `server_config.py` remains a compatibility re-export and non-recommendation runtime defaults module;
- validation is Python-level in Stage 5;
- external YAML/JSON config loading is intentionally deferred;
- route response shape and generator behavior are unchanged.

Create `docs/RECOMMENDATION_COMPATIBILITY.md`.

Each compatibility entry must include:

```text
Decision:
Reason:
Implementation action:
Tests:
Removal condition, if any:
```

Required entries:

- `server_config.py` re-exports recommendation config for compatibility.
- Python-level config validation is added but raw config remains the runtime execution input.
- `RecommendationResult.to_response()` preserves `generatedAt`, `total`, `count`, `seed`, `rows`.
- Debug metadata public shape remains unchanged.
- External YAML/JSON recommendation config is deferred.

### 11. Update tooling lint surface only if new files require it

Stage 2 currently keeps `make lint` intentionally narrow. If Stage 5 adds new recommendation config/types modules and tests, update `Makefile` lint target only for these new maintained files and their direct tests.

Do not expand lint to the whole legacy recommendation package in Stage 5.

### 12. Non-negotiable implementation constraints

#### Config movement

Constraint: Moving `RECOMMENDATION_PIPELINE` must not break legacy imports from `server_config.py`.

Required action: Keep `server_config.py` re-exports and add a compatibility test comparing `server_config.RECOMMENDATION_PIPELINE` to `recommendations.config.RECOMMENDATION_PIPELINE`.

#### Validation

Constraint: Validation must not alter default config values or runtime execution semantics.

Required action: Validate checked-in config but pass the raw dictionary into `MixingRecommendationStrategy` and existing generators.

#### External config files

Constraint: YAML/JSON external config loading is out of scope.

Required action: Do not create external config files; document the deferral in `docs/RECOMMENDATION_COMPATIBILITY.md` and recommendation docs.

#### Candidate dataclasses

Constraint: Generator and mixer behavior must not be rewritten around dataclass candidates in Stage 5.

Required action: Use typed aliases or boundary dataclasses only; keep generator input/output as dictionaries unless a local adapter preserves exact values and tests remain green.

#### Debug metadata

Constraint: Public debug response shape must not change.

Required action: Keep `attach_debug_info()` output keys identical; if internal debug storage changes, adapt it back before response assembly and test the output keys.

#### Scoring/mixing behavior

Constraint: No score formula, ratio math, layer schedule, fallback order, soft caps, dedup keys, or candidate ordering may change.

Required action: Run Stage 0 recommendation characterization tests and add config/type tests only. If a desired cleanup would change these behaviors, leave it for a later behavior-change plan.

#### Route behavior

Constraint: `/recommendations`, `/videos/similar`, and `/videos/{id}/similar` response and error behavior must not change.

Required action: Run Engine route characterization tests after config/type changes and keep route/service call signatures compatible.

#### Data access

Constraint: Stage 5 must not edit SQL, DB schema, migrations, or Engine data repository behavior.

Required action: Keep all `engine/server/data/*` changes out of Stage 5. If validation needs schema assumptions, document them instead of changing data access.

#### Startup behavior

Constraint: Stage 5 must not change FAISS/index loading or server startup lifecycle.

Required action: Limit startup changes to imports/re-exports and config validation that passes for the default config. Do not isolate FAISS imports in Stage 5.

## Tests

Run before and after implementation:

```bash
make test
make lint
python3 -m unittest engine.server.api.tests.test_recommendations_likes_limit
```

Required new tests:

```bash
python3 -m pytest tests/recommendations/test_config_validation.py tests/recommendations/test_types_characterization.py -q
```

Required existing recommendation tests:

```bash
python3 -m pytest tests/recommendations -q
```

Required route/service regression coverage:

```bash
python3 -m pytest tests/engine_api/test_recommendations_request_contract.py tests/engine_api/test_similar_route_characterization.py -q
```

Full fast suite:

```bash
make test
```

Lint:

```bash
make lint
```

Expected prerequisite-sensitive behavior:

```bash
python3 engine/server/api/server.py --help
```

may still fail with the known FAISS prerequisite. Stage 5 must not try to fix that.

## Documentation Maintenance

Update only documentation whose responsibility covers recommendation internals or development commands:

```text
docs/RECOMMENDATION_COMPATIBILITY.md
engine/server/api/recommendations/docs/OVERVIEW.md
engine/server/api/recommendations/docs/LAYER_PARAMS.md
engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md
docs/DEVELOPMENT.md
docs/TESTING.md
```

`docs/ENGINE_API_COMPATIBILITY.md` should be updated only if Stage 5 changes route-level compatibility decisions. The expected Stage 5 path should not require changing it because route behavior should remain unchanged.

Do not update deployment, data-build, crawler, frontend, or Client docs unless implementation unexpectedly touches those areas; if such a touch is needed, it is outside this Stage 5 plan.

## Regression and Blind-Spot Analysis

### Config source move could break imports

Risk: `engine/server/api/server.py`, tests, or docs may still import `RECOMMENDATION_PIPELINE` from `server_config.py`.

Action: Keep `server_config.py` compatibility re-export and add a test that legacy and new imports refer to equal config dictionaries.

### Validation could reject current defaults

Risk: The validator may accidentally reject the checked-in config because some current fields are optional, absent in `upnext`, or use generator-specific names.

Action: Write the default-config validation test first; implement validation against current defaults and allow profile-specific partial config where current code allows fallback behavior.

### Validation could alter runtime behavior

Risk: Converting to typed config and then executing from typed objects could change fallback/default dictionary semantics.

Action: Use validation for safety only and continue passing the raw dictionary to `MixingRecommendationStrategy` in Stage 5.

### Type objects could become public schemas accidentally

Risk: `RecommendationRequest` or `RecommendationResult` could be treated as public HTTP schemas and cause response-shape changes.

Action: Keep types under `recommendations/types.py`, document them as internal, and use `RecommendationResult.to_response()` to emit the existing primitive dictionary shape.

### Debug metadata separation could break diagnostics

Risk: Moving debug details out of candidate dicts could remove keys expected by debug-mode tests.

Action: Do not change debug storage unless a test covers the exact public debug keys. If changed internally, adapt back through `attach_debug_info()` before response output.

### External config temptation could create packaging risk

Risk: Introducing YAML/JSON config files would require new file lookup paths and deployment packaging behavior.

Action: Do not add external config files in Stage 5. Document external config as deferred.

### Recommendation docs could become stale

Risk: Docs may still point at `server_config.py` as the config source after the move.

Action: Update recommendation docs to point at `recommendations/config.py` and describe `server_config.py` as compatibility re-export.

### Stage 5 could accidentally become a recommendation redesign

Risk: While clarifying internals, implementation might change formulas, ratios, layer ordering, generator caps, or fallback behavior.

Action: Do not edit generator algorithms or scoring formulas except for import/type boundary changes; run existing Stage 0 recommendation characterization tests.

### Startup validation could add side effects

Risk: Import-time validation could make imports slower or change startup failure mode unexpectedly.

Action: Validate only the checked-in in-memory dictionary using pure Python checks. Do not read files, initialize DBs, load FAISS, or access environment variables from `recommendations/config.py`.

## Generic vs Project-Specific Behavior

Generic behavior:

- Validating checked-in config before runtime execution is a generic safe-refactor practice.
- Internal dataclasses can clarify boundaries without becoming public HTTP schemas.
- Compatibility re-exports are a common way to move ownership without breaking imports.

Project-specific behavior:

- The generator names `random`, `popular`, `explore`, `exploit`, and `fresh` are PeerTube Browser product behavior, not a generic recommendation protocol.
- The profile names `home`, `guest_home`, `upnext`, and `guest_upnext` are project-specific modes used by this Engine API.
- The public recommendation response shape with `generatedAt`, `total`, `count`, `seed`, and `rows` is a project-specific Engine/Frontend contract.
- Client-provided likes and bridge-ingested interaction signals are part of this project's local Client->Engine recommendation contract.

## Open Questions

None for the current Stage 5 scope.
