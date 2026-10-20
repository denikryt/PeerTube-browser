# How It Works

Purpose: explain the internal behavior of the running system.

## Frontend

The Vue frontend exposes these routes:

```text
/                         discovery
/categories               discovery filtered by category
/tags                     discovery filtered by tag
/search                   video and channel search
/channels                 channel list
/video/:host/:id          video detail
/about                    project description
```

Home state is represented by the selected provider and optional `language`, `category`, `tag`, and `instance` filters. Search adds `q` to the same video-filter contract. URL query parameters reconstruct the selected state.

Frontend API calls use the Client base from `VITE_CLIENT_API_BASE`. Feed and search state own request generations, continuation cursors, duplicate guards, retry state, and stale-response rejection. The frontend renders Engine ordering without re-ranking rows.

Browser-local likes use the `localLikes:v1` key with `{video_uuid, instance_domain}` entries. Home is cached across video-detail Back navigation; Search is not. Continuation errors retain the current rows and cursor until explicit retry. A stale Random generation restarts that selection from its first page.

Video cards receive ordered thumbnail candidates from Client. The frontend tries one candidate at a time, spaces requests to the same origin, advances on image error, and finally uses the local default thumbnail. Preview images are not promoted into this candidate set.

## Client Request Processing

Client exposes the public browser API and separates three operations:

1. Profile and user actions use the Client users database.
2. Discovery, search, video, and channel reads are forwarded to Engine.
3. Normalized user events are published to Engine ingest.

Client validates browser input, limits forwarded fields, preserves allowed upstream status, body, and content type, and returns controlled gateway errors. It does not read Engine SQLite files.

Client and Engine use explicit permissive CORS responses and return `204` for preflight requests. Rate limits use a `client_ip:path` key. Request bodies are parsed manually so invalid JSON and request-size errors retain the project response contract instead of FastAPI/Pydantic defaults.

### Profiles and Likes

Client stores users and likes in `client/backend/db/users.db`. A like action resolves the canonical video identity through Engine, updates Client-owned profile state, and then publishes a normalized event to `/internal/events/ingest`.

Profile reset and unlike actions affect the Client database. Engine interaction ingest is a separate event record; it is not the source of browser profile state.

### Discovery API

Client exposes browser-facing Discovery routes under `/api/v1/`:

```text
/api/v1/discovery/recommendations
/api/v1/discovery/fresh
/api/v1/discovery/popular
/api/v1/discovery/trending
/api/v1/discovery/random
/api/v1/search/videos
/api/v1/search/channels
/api/v1/video-facets
/api/v1/videos/{video_ref}
/api/v1/videos/{video_ref}/similar
```

Client owns public validation, cursor envelopes, user-like lookup, and browser error shapes. Engine owns filter semantics, ordering, eligibility, and canonical metadata.

Fresh, Popular, and Trending use Engine keyset cursors. Random uses a generation-bound cursor over its persisted order. Recommendations are a finite computation and return a terminal Client pagination envelope.

Replacing the Random generation invalidates old Random cursors with `stale_cursor`. Missing or incompatible Random data returns `random_provider_unavailable`; runtime does not invent an unstable fallback pagination order.

## Engine Startup

Engine opens the canonical database, applies Engine runtime schema and read-index bootstrap, opens the similarity cache, and loads the FAISS index. It validates that the FAISS dimension matches stored embeddings.

Random is optional at startup. Engine opens `random-cache.db` and the canonical database read-only for Random. A missing or incompatible Random artifact disables only that provider. Engine does not rebuild or hot-reload Random.

Engine cannot serve recommendations without canonical embeddings and a compatible FAISS index.

`ENGINE_INGEST_MODE=bridge` enables `/internal/events/ingest`. Other modes keep the route present but return `501`.

## Engine Reads

Engine reads canonical videos, channels, instances, embeddings, moderation state, prepared discovery data, and search data from `whitelist.db`.

Serving requires `invalid_reason IS NULL`; diagnostic fields do not hide videos. Instance and channel moderation are applied independently before result limits and direct-video network requests.

Direct `/api/video` resolves the stored host and UUID, then requests PeerTube detail over HTTPS without following redirects. Matching data overlays the response; a direct 404/410 returns request-only 404, while other failures use cached fields. The request never writes Engine data; existing-row availability remains Updater-owned.

## Discovery Providers

Fresh orders eligible videos by publication time. Popular and Trending use persisted popularity. Random reads the updater-built order and resolves each stable index ID against current canonical metadata, which removes stale or newly ineligible rows.

All video discovery and video search use the same Engine-owned filters:

```text
language
category
tag
instance
```

Tag filtering reads normalized `video_tags`. Facets read the singleton `video_facets_snapshot`. Engine never falls back to scanning tag JSON or aggregating the full corpus during a request.

## Recommendations

Recommendation configuration is defined in `engine/server/api/recommendations/config.py`. The active profiles are:

```text
home
guest_home
upnext
guest_upnext
```

The guest profile is selected when no likes are available.

### Inputs

Embeddings are built from:

```text
title
description
tags
category
channel name
```

The default embedding model is `all-MiniLM-L6-v2`. FAISS provides approximate nearest-neighbor search. The similarity cache stores precomputed candidates per seed video. The Random cache stores ordered stable `video_index_ids.index_id` values without duplicating mutable video metadata.

### Candidate Layers

| Layer | Candidate source | Main condition |
|---|---|---|
| `exploit` | ANN or cached similarity from likes | similarity at or above `exploit_min` |
| `explore` | Random pool scored against likes | similarity inside the configured range |
| `popular` | persisted popular videos | pool size and author/instance caps |
| `random` | persisted Random order or DB fallback | optional below-explore threshold |
| `fresh` | latest eligible videos | pool size and author/instance caps |

`exploit` and `explore` require likes. Guest profiles use Popular, Random, and Fresh.

### Gathering, Scoring, and Mixing

Each enabled layer receives a gathering limit based on `batch_size`, `overfetch_factor`, and its `gather_ratio`. Ratios are normalized across active layers.

Candidates receive a unified score:

```text
score = similarity_weight * similarity
      + freshness_weight * freshness
      + popularity_weight * popularity
      + layer_weight
```

Final quotas use each layer's `mix_ratio`. Missing capacity follows the profile's configured mixing order. Final processing removes duplicates and already-liked videos and applies configured caps. The response is already ordered for the frontend.

The Engine recommendation response contains `generatedAt`, `total`, `count`, `seed`, and `rows`. Optional debug output is attached without changing the video rows. Recommendation configuration is checked-in Python configuration; there is no external YAML or JSON config loader.

## Data Stores

### Client Database

`client/backend/db/users.db` contains `users` and `likes`. Client schema setup is owned by `client/backend/db/bootstrap.py` and its migrations.

### Crawler Database

`engine/crawler/data/crawl.db` uses `engine/crawler/schema.sql`. Its core tables are:

```text
instances
channels
videos
instance_crawl_progress
channel_crawl_progress
video_crawl_progress
```

Progress rows make crawler pagination resumable. Successful channel video counts are persisted immediately. Video progress stores the next page offset after each fetched page.

### Canonical Engine Database

`engine/server/db/whitelist.db` contains canonical instances, channels, videos, embeddings, interaction tables, moderation state, stable index IDs, prepared tags and facets, Search data, and Engine read indexes.

Important prepared structures are:

```text
video_tags                  normalized tag membership
video_facets_snapshot       singleton prepared facets and readiness marker
video_index_ids             stable numeric IDs used by FAISS and Random
interaction_raw_events      idempotent normalized events
interaction_signals         aggregate interaction state
instance_denylist           instance moderation
channel_moderation          channel moderation
```

### Derived Artifacts

```text
whitelist-video-embeddings.faiss       ANN index
whitelist-video-embeddings.faiss.json  ANN generation metadata
similarity-cache.db                    cached similar-video candidates
random-cache.db                        persisted Random order
```

Stable index mappings are retained when inactive but excluded from new artifacts. Similarity cache rows use video identity rather than FAISS numeric IDs.

## Crawler Behavior

Crawler discovers instances, collects channels, persists channel video counts, and fetches video detail. Existing identities are skipped while pagination continues, so later pages can still add new videos.

Network retries are bounded. Timeouts, `408`, `425`, `429`, `5xx`, and transient connection resets are retryable. Permanent client errors, invalid JSON, certificate failures, and terminal network errors fail immediately. Persisted errors include a category such as `[timeout]`, `[http_502]`, or `[tls]`.

Per-host concurrency and delay apply across instance, channel, count, video, metadata, and thumbnail requests.

Thumbnail candidate state distinguishes three cases:

- SQL `NULL`: no authoritative detail projection;
- JSON array: authoritative ordered candidates;
- `[]`: authoritative absence of usable candidates.

The first candidate mirrors into the singular thumbnail fields. Preview images are not card-thumbnail candidates.

Canonical availability and crawler diagnostics are separate. Direct detail `404` and `410` can establish `not_found` and `gone` for newly discovered identities. Other failures update diagnostics without establishing canonical absence.

## Parent Health and Child Admission

Crawler parent state is distinct from canonical video availability. Parent health uses the `instances` and `channels` tables; the channel listing has its own `channel_crawl_progress` status. A newly selected host starts at page zero with current per-host provenance, then undergoes fresh instance probe, channel enumeration, and unresolved channel health checks. Channel enumeration reaches `done` only when the remote end is validated and the local channel budget did not discard eligible entries; a truncated result is not completed.

Counts, new-video ingest, and existing-video detail sweeps require a current `ok` instance, a current `ok` channel, confirmed `done` and matching per-host provenance. An old `done` does not authorize new child requests. A confirmed local `NoNetworkError` stops scheduling new work across hosts; remote-host errors remain local to that host. Already-started operations drain before SQLite closes.

The canonical Engine reads filter videos with explicit parent `health_status='error'` in both SQL and already materialized recommendation results. An unset/unknown parent health is not itself proof of permanent absence. Video `invalid_reason` remains the canonical availability filter; diagnostics alone do not tombstone a video.

## Data Ownership and Publication

- Client user/profile schema: `client/backend/db/bootstrap.py` and migrations. Only Client writes users/likes.
- Crawler source schema: `engine/crawler/schema.sql`. Crawler owns ingestion, health observations, and pagination progress in staging or crawl DB.
- Canonical database: `engine/server/db/whitelist.db`. Updater/data-build jobs publish canonical video/parent metadata and derived snapshots; Engine owns its runtime/interaction schema via `engine/server/db/bootstrap.py` and `engine/server/db/migrations/`.
- Derived artifacts: `video_facets_snapshot`, `video_index_ids`, `whitelist-video-embeddings.faiss` and `.json`, `similarity-cache.db`, and `random-cache.db`. Their rebuilds are offline; Engine reads them and never constructs replacements during a request.

Updater merges new parent metadata with `INSERT` health fields set to `NULL`, then publishes only current run's parent observations using a JSON1-scoped `UPDATE` in the same transaction. Existing parent metadata is not rewritten by this health publication. Changes affecting serving visibility invalidate Prepared Discovery atomically; a failed merge rolls back the entire publication.

## Recommendation Configuration

`engine/server/api/recommendations/config.py` owns profiles (`home`, `guest_home`, `upnext`, `guest_upnext`), generators (`exploit`, `explore`, `fresh`, `random`, `popular`) and weights. There is no external YAML/JSON recommendation configuration loader.

- `batch_size × overfetch_factor × gather_ratio` sets each layer's candidate gathering budget, with active ratios normalized. A source's own search limit or pool size can further restrict returned candidates.
- `mix_ratio` sets final layer quota; `mixing.order` determines fallback when a layer is short.
- `max_per_author` and `max_per_instance` constrain generator pools; final mixing deduplicates identities and removes already-liked videos.
- `exploit_min` and `explore.similarity_min/max` filter similarity-based layers; `scoring.weights` and `scoring.layer_weights` determine final order.
- The similarity cache is keyed by canonical video identity; FAISS and Random use persistent `video_index_ids.index_id`, not the mutable SQLite rowid.

For exact runtime parameter names and default values, inspect the checked-in configuration; descriptions here do not replace validation of that configuration.
