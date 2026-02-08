# Home Recommendations — How the Feed Is Built (Detailed)

Short version: the server prepares data (embeddings/index/cache), gathers candidates
from `explore/exploit/popular/random/fresh`, assigns a unified `score`, then mixes
layers by ratios with a fallback order and applies final post-filters (dedup + soft
caps) before returning a batch to the client.

## 1) Requests and Modes
- **Home**: the home mdpage calls `/api/similar` without a seed video.
  The server enables the recommendation strategy and uses the `home` profile.
- **Up Next**: `/api/similar` with a seed video (id/uuid/vector).
  The server uses the `upnext` profile and reorders similar items via local scoring.

Profiles live in `RECOMMENDATION_PIPELINE` (see `server/api/server_config.py`).
If the user has no likes, the profile auto-switches to `guest` (guest_home/guest_upnext),
where only `random/popular/fresh` are active.

### Likes Source (Temporary No-Auth Mode)
- By default the server can accept likes from client JSON (e.g. localStorage).
- If the JSON is empty or has no likes, `likes=no` and the guest profile is used.
- If this mode is disabled, likes are read from `users.db`.

## 2) Data Preparation: Embeddings, Index, Cache
1. **Video embeddings**
   Built offline from video text: title, description, tags, category, channel name, comments_count.
   Text is turned into a vector (SentenceTransformer), normalized, and stored in `video_embeddings`.
2. **ANN index**
   Built from embeddings for fast similarity search.
3. **Similarity cache**
   Stores similar lists per seed video (video_id + score + rank).
   Used as a fast candidate source and can refresh when needed.
   If the cache lacks `score`, it is treated as stale and recomputed (refresh).
   Cache reads can require a full list (`DEFAULT_SIMILARITY_REQUIRE_FULL_CACHE`);
   partial lists are treated as a miss. For exploit, ANN fallback on miss is
   controlled by `DEFAULT_SIMILARITY_ALLOW_ANN_ON_CACHE_MISS`.
4. **Random cache**
   Holds a prebuilt list of rowids for quick random pools.
   Can run in **raw** mode (no filters) or **filtered** mode.
   In filtered mode, `max_per_instance` and `max_per_author` are applied during cache build.
   In filtered mode, cache size equals `DEFAULT_RANDOM_CACHE_SIZE` after filtering.

## 3) Candidate Sources (Generators)
The pipeline uses five layers. Likes are a mechanism inside a layer, not a separate source.
In guest profiles (no likes), only `random/popular/fresh` are active.

- **exploit** — “most similar”.
  Source: ANN or cached similarity from user likes.
  Filter: `similarity >= exploit_min` (fixed threshold).
  Caps: `max_per_author/max_per_instance` are applied inside the layer.
  Ranking: by `similarity_score`.
  Selection: random sample from the filtered pool up to the layer limit.
  Requires likes: if there are no likes, the layer is disabled.
  If there are no likes, the layer is empty (fallback goes to random/popular).
  Cache notes: cache-optimized source reads per-like cache; if the cache is
  partial/empty, ANN fallback happens only when
  `DEFAULT_SIMILARITY_ALLOW_ANN_ON_CACHE_MISS` is enabled.

- **explore** — “moderately similar”.
  Source: random cache (or random from DB if cache is empty).
  Filter: `similarity_min <= similarity < similarity_max` vs user likes.
  Caps: `max_per_author/max_per_instance` are applied inside the layer.
  Ranking: by `similarity_score`.
  Selection: random sample from the filtered pool up to the layer limit.
  Requires likes: if there are no likes, the layer is disabled.
  If there are no likes, the layer is empty (fallback goes to random/popular).

- **popular** — “popular videos”.
  Source: top by likes/views with a soft freshness bonus.
  Pool is limited by `pool_size`.
  Caps: `max_per_author/max_per_instance` are applied inside the layer.
  If likes exist, it is re-ranked by similarity.
  Selection: random sample from the pool after sorting.

- **random** — “random videos”.
  Source: random cache (or random from DB).
  Caps: `max_per_instance/max_per_author` are applied inside the layer.
  Optional: keep only items below `explore_min`.
  Selection: random sample from the pool.

- **fresh** — “recent videos”.
  Source: latest videos from DB.
  Pool is limited by `pool_size`.
  Caps: `max_per_author/max_per_instance` are applied inside the layer.
  If likes exist, similarity to likes influences `similarity_score`.
  Selection: random sample from the pool after sorting.

## 4) How Many Candidates to Fetch (Fetch Limits)
- `gather_ratio` (collection) and `mix_ratio` (output) are set per profile in `RECOMMENDATION_PIPELINE`.
- Candidate fetch limits are computed from batch size and multiplied by `overfetch_factor`.
- These are pool-building limits, not final output counts.

### What “Pools” Are and How They Are Built
A pool is a layer-local candidate list built before mixing.
Each layer builds its own pool from its own source:
- **exploit pool**: ANN or cache from likes, filtered by `similarity >= exploit_min`, then caps.
- **explore pool**: random cache or DB, filtered by `similarity_min <= similarity < similarity_max`, then caps.
- **random pool**: random cache; optionally filtered by `similarity < explore_min`, then caps.
- **popular pool**: top by likes/views; if likes exist, re-ranked by similarity; then caps.
- **fresh pool**: latest videos; if likes exist, `similarity_score` is set; then caps.

Important: pool limits only affect candidate gathering.
Candidates are later scored and mixed by layer ratios to form the final batch.

## 5) Unified Scoring
Each candidate gets a unified `score` based on:
- **similarity** (when available; from ANN/cache or `similarity_score` for fresh).
- **freshness** (decay based on `published_at`, half-life is configured).
- **popularity** (log-normalized function of views/likes).
- **layer bonus** (optional source weights).

Formula:
`score = w_sim * similarity + w_fresh * freshness + w_pop * popularity + layer_bonus`

The final `score` is stored in the row and used for ordering.

## 6) Layer Mixing (mix_ratio + fallback)
- Final output is built by `mix_ratio` per layer, not by a shared exploit/explore bucket.
- If some layers are disabled/empty (e.g. no likes -> explore/exploit), `gather_ratio` and `mix_ratio`
  are normalized across active layers so the batch stays filled.
- If a layer cannot fill its quota, fallback follows: `explore -> exploit -> popular -> random -> fresh`.
- Within each layer, candidates are ordered by `score`, then mixed by a layer schedule.

## 7) Post-Filters
After mixing, post-processing applies:
- **Dedup**: remove already liked videos and duplicates across layers.
- **Soft caps**: optional per-layer min/max constraints.

The result is a mixed batch with controlled diversification.

## 8) What the Client Receives
- The client receives a ready-to-render list of videos (batch), already ordered/mixed on the server.
- The frontend does not re-sort recommendations; it renders as-is.
- The response includes `seed` with the mode (`home` or `upnext`).
