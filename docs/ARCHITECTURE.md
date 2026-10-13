# Architecture

Purpose: define the system components, their responsibilities, and their boundaries.

## Components

| Component | Responsibility |
|---|---|
| Frontend | Render the browser UI and send browser actions to Client. |
| Client | Expose the browser-facing API, persist local profiles and likes, and call Engine over HTTP. |
| Engine | Serve discovery, search, metadata, similarity, and interaction-ingest behavior from Engine-owned data. |
| Crawler | Collect public PeerTube instance, channel, and video data into crawler-owned SQLite data. |
| Updater | Refresh the production dataset and publish the derived artifacts consumed by Engine. |

Updater operation is documented only in `docs/UPDATER.md`.

## Runtime Boundary

The browser-facing request path is:

```text
Browser -> Frontend -> Client -> Engine -> Engine data
```

The data publication path is:

```text
PeerTube -> Crawler -> Updater -> Engine data
```

Frontend never calls Engine directly. Client never imports Engine modules or reads Engine database files. Engine does not own browser profile persistence. Crawler and Updater do not serve browser requests.

## Frontend

Frontend owns page state, rendering, navigation, filtering controls, request cancellation, pagination state, and presentation of errors. It calls only Client browser-facing routes.

Frontend does not own recommendation ranking, canonical video data, user-profile persistence, or Engine routes.

## Client

Client is the public API boundary for the browser. It owns:

- local users and likes;
- browser-facing validation and error responses;
- normalization of user actions;
- discovery and search response envelopes;
- HTTP forwarding to Engine;
- publication of normalized interaction events to Engine.

Client communicates with Engine only through HTTP. Direct imports from Engine and direct access to `engine/server/db/` are forbidden.

## Engine

Engine owns:

- recommendation computation;
- Fresh, Popular, Trending, and Random provider behavior;
- video and channel metadata reads;
- search and video-filter semantics;
- canonical serving eligibility and moderation filtering;
- internal video resolution and metadata contracts;
- interaction-event ingest;
- reads from the canonical dataset, FAISS index, and derived caches.

Engine does not persist Client profiles or browser-owned likes. Request-time ranking uses likes supplied through the Client request context; aggregated interaction signals are stored but are not currently used by discovery ranking.

## Crawler

Crawler owns PeerTube network collection, pagination, retry classification, crawl progress, and writes to the crawler schema. It produces source data; it does not rank results or define browser API behavior.

Generated crawler JavaScript is runtime output and is not source code.

## Data Ownership

| Data | Writer | Reader |
|---|---|---|
| Client users and likes | Client | Client |
| Raw crawl database | Crawler | Crawler and data-build jobs |
| Canonical videos, channels, and instances | Data-build jobs and Updater | Engine |
| Interaction events and aggregate signals | Engine ingest | Engine data layer |
| Prepared tags and facet snapshot | Data-build jobs and Updater | Engine |
| Video embeddings and stable index IDs | Data-build jobs and Updater | Engine and artifact builders |
| FAISS index | Data-build jobs and Updater | Engine |
| Similarity cache | Data-build jobs and Updater | Engine |
| Random cache | Updater and data-build jobs | Engine, read-only |

Runtime must not rebuild production artifacts. Publication of canonical data and derived artifacts is an offline writer responsibility.

## HTTP Ownership

Client owns browser-facing routes, including:

```text
/api/user-profile
/api/user-profile/likes
/api/user-profile/reset
/api/user-action
/api/v1/discovery/*
/api/v1/search/*
/api/v1/video-facets
/api/v1/videos/*
```

Engine owns provider and internal routes, including:

```text
/recommendations
/videos/similar
/videos/{id}/similar
/api/video
/api/channels
/internal/discovery/*
/internal/search/videos
/internal/video-facets
/internal/videos/resolve
/internal/videos/metadata
/internal/events/ingest
```

Legacy browser-facing proxy routes exposed by Client remain Client routes even when their response is supplied by Engine.

## Required Boundaries

- Frontend calls Client only.
- Client calls Engine through HTTP only.
- Client owns browser profile state.
- Engine owns ranking and canonical read behavior.
- Crawler owns its source schema and network collection behavior.
- Updater owns production refresh and artifact publication.
- Component boundaries are verified by `tests/check-frontend-client-gateway.sh` and `tests/check-client-engine-boundary.sh`.
