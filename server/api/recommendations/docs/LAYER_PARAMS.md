# Recommendation Layer Params (explore / exploit / fresh / random / popular)

This document explains which parameters influence candidate volume and final
output per layer. Config source: `server/api/server_config.py` (RECOMMENDATION_PIPELINE).

Profiles:
- `home` / `upnext` — primary modes.
- `guest_home` / `guest_upnext` — auto-selected when there are no likes.

## Common Parameters (All Layers)

### Candidate Gathering (gather)
- `batch_size` — response size.
- `overfetch_factor` — how much raw pool to gather relative to batch size.
- `generators.<layer>.gather_ratio` — layer share during candidate collection.
- `generators.<layer>.requires_likes` — layer participates only if the user has likes.

Gather limit formula:
`gather_limit = batch_size * overfetch_factor * gather_ratio`
If some layers are disabled (for example, no likes), `gather_ratio` is normalized
across active layers. If the total `gather_ratio` is 0, limits are split evenly.

### Final Output (mix)
- `generators.<layer>.mix_ratio` — layer share in the final batch.
- `mixing.order` — fallback order when a layer is empty (e.g. `explore -> exploit -> popular -> random -> fresh`).

If a layer is empty/disabled, `mix_ratio` is normalized across active layers.
If the total `mix_ratio` is 0, output quotas are split evenly.

### Constraints and Filters
- `generators.<layer>.max_per_author` and `generators.<layer>.max_per_instance` are applied inside each layer
  while building its candidate pool (exploit/explore/fresh/random/popular).
- Like dedup: already liked videos are removed at the final mix step.
- `soft_caps` (min/max per layer, if set) are applied after mixing.

### Scoring (Order Within a Layer)
- `scoring.weights.similarity`
- `scoring.weights.freshness`
- `scoring.weights.popularity`
- `scoring.layer_weights.<layer>`
- `similarity_score` may be computed for exploit/explore/fresh/random/popular and participates in scoring.

## exploit Layer

**Source:** ANN or cached similarity from user likes.

### Layer Params
- `generators.exploit.gather_ratio`
- `generators.exploit.mix_ratio`
- `generators.exploit.pool_size` — how many top-K to ask from the source (pool limit).
- `generators.exploit.exploit_min` — similarity threshold (>=).
- `generators.exploit.shuffle` — shuffle candidates before scoring.
- `generators.exploit.requires_likes`
- `generators.exploit.max_per_instance`
- `generators.exploit.max_per_author`

### Source Params (Hard Limits)
- `DEFAULT_SIMILAR_PER_LIKE` — how many similar items per like.
- `DEFAULT_SIMILARITY_SEARCH_LIMIT` — ANN upper bound.
- `DEFAULT_SIMILARITY_MAX_PER_AUTHOR` — author cap before mixing.
- `DEFAULT_SIMILARITY_EXCLUDE_SOURCE_AUTHOR`
- `VIDEO_ERROR_THRESHOLD`
- `DEFAULT_SIMILAR_FROM_LIKES_SOURCE` (cache-optimized vs ann)
- `DEFAULT_SIMILARITY_REQUIRE_FULL_CACHE` — treat partial cache as miss.
- `DEFAULT_SIMILARITY_ALLOW_ANN_ON_CACHE_MISS` — allow ANN fallback per like when cache misses.

Important: if the source returns fewer candidates, `pool_size` will not expand the pool.

## explore Layer

**Source:** random cache (or random from DB if cache is empty) + similarity to likes.

### Layer Params
- `generators.explore.gather_ratio`
- `generators.explore.mix_ratio`
- `generators.explore.pool_size` — random pool size before filtering.
- `generators.explore.similarity_min` / `similarity_max` — similarity range.
- `generators.explore.shuffle`
- `generators.explore.requires_likes`
- `generators.explore.max_per_instance`
- `generators.explore.max_per_author`

Behavior: take `pool_size` from the random pool, compute similarity to likes,
filter by range, then randomly sample to `limit`.

If there are no likes, the layer returns empty (fallback goes to random/popular via `mixing.order`).

## fresh Layer

**Source:** latest videos from DB.

### Layer Params
- `generators.fresh.gather_ratio`
- `generators.fresh.mix_ratio`
- `generators.fresh.shuffle`
- `generators.fresh.pool_size`
- `generators.fresh.max_per_instance`
- `generators.fresh.max_per_author`

### Source Params
- `DEFAULT_FRESH_POOL_SIZE` (0 -> uses `DEFAULT_SIMILAR_PER_LIKE`)
- `VIDEO_ERROR_THRESHOLD`

If likes exist, `similarity_score` is computed against liked vectors.
If there are no likes, a random sample is taken from the recent pool.

## random Layer

**Source:** random cache (or random from DB if cache is empty).

### Layer Params
- `generators.random.gather_ratio`
- `generators.random.mix_ratio`
- `generators.random.below_explore_min` — if true, filter by `similarity < explore_min`.
- `generators.random.explore_min`
- `generators.random.shuffle`
- `generators.random.max_per_instance` — cap per instance inside the random pool (0 disables).
- `generators.random.max_per_author` — cap per channel inside the random pool (0 disables).

Behavior: take the random pool; if `below_explore_min` is enabled and there are likes,
keep only candidates below the threshold (by similarity to likes). Then apply instance/channel caps.

### Random Cache Params (Global)
- `DEFAULT_RANDOM_CACHE_SIZE` — final number of candidates in the cache.
- `DEFAULT_RANDOM_CACHE_REFRESH` — rebuild cache on startup.
- `DEFAULT_RANDOM_CACHE_FILTERED_MODE` — when true, cache is built with instance/channel filters.
- `DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE` — cap per instance during cache build (0 disables).
- `DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR` — cap per channel during cache build (0 disables).

In filtered mode, `DEFAULT_RANDOM_CACHE_SIZE` refers to the already filtered cache size.

## popular Layer

**Source:** top videos by likes/views.

### Layer Params
- `generators.popular.gather_ratio`
- `generators.popular.mix_ratio`
- `generators.popular.shuffle`
- `generators.popular.pool_size`
- `generators.popular.max_per_instance`
- `generators.popular.max_per_author`

Behavior: with likes, the pool is re-ranked by similarity; otherwise it is returned as-is
(popularity with a soft freshness bonus).
