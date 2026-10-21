# Project Architecture Overview

This diagram shows the main runtime components, data owners, and update paths in PeerTube Browser. It is a high-level map of the whole project, not a detailed recommendation pipeline diagram.

For recommendation internals, see:

```text
engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md
```

## System overview

```mermaid
flowchart LR
    Browser["Browser / User"] --> Frontend["Frontend<br/>Vite / TypeScript UI"]

    Frontend -->|"HTTP<br/>public browser API"| Client["Client Backend<br/>FastAPI gateway"]

    Client -->|"read/write profile state"| ClientDB[("Client DB<br/>users / likes")]
    Client -->|"HTTP read proxy<br/>recommendations / video / channels"| Engine["Engine API<br/>FastAPI"]
    Client -->|"HTTP internal event ingest<br/>likes / user actions"| Engine

    Engine -->|"read video/channel metadata"| EngineDB[("Engine Dataset<br/>videos / channels / instances")]
    Engine -->|"read/write interaction events"| Signals[("Interaction Events<br/>raw events / signals")]
    Engine -->|"read similarity/random caches"| Caches[("Derived Caches<br/>similarity / random")]
    Engine --> Recs["Recommendation Pipeline"]

    Recs -->|"candidate sources"| EngineDB
    Recs -->|"similarity candidates"| Caches
    Recs -->|"profile and interaction signals"| Signals

    Crawler["PeerTube Crawler<br/>TypeScript"] -->|"crawl PeerTube APIs"| PeerTube["PeerTube Instances"]
    Crawler -->|"write raw crawl data"| CrawlerDB[("Crawler SQLite DB")]

    Jobs["Updater / Data Jobs<br/>Python orchestration"] -->|"run crawler build steps"| Crawler
    Jobs -->|"merge/build/update"| EngineDB
    Jobs -->|"build embeddings / ANN / caches"| Caches

    Engine -->|"JSON rows"| Client
    Client -->|"JSON rows + profile state"| Frontend
```

## Main responsibilities

### Frontend

The frontend owns browser UI behavior.

It is responsible for:

```text
rendering video feeds
rendering video pages
rendering channel pages
sending user actions to the Client backend
storing only browser-local UI state where needed
calling the Client backend, not the Engine directly
```

The frontend must not call Engine internal routes directly. The expected runtime path is:

```text
Frontend -> Client Backend -> Engine API
```

### Client Backend

The Client backend is the browser-facing API gateway.

It is responsible for:

```text
public API routes used by the frontend
local user profile state
local likes state
normalizing browser user actions
proxying read requests to the Engine API
publishing normalized interaction events to the Engine
```

It owns the Client DB:

```text
users
likes
```

It must not:

```text
read Engine SQLite databases directly
import Engine internals
compute recommendations
crawl PeerTube data
own Engine datasets or caches
```

### Engine API

The Engine API owns read-side product behavior.

It is responsible for:

```text
recommendation routes
video metadata routes
channel routes
internal video resolve/metadata routes
internal interaction event ingest
reading Engine datasets and derived caches
serving stable frontend-facing rows
```

It owns or reads:

```text
video/channel/instance datasets
interaction raw events
interaction signals
similarity caches
random caches
recommendation candidate sources
```

It must not:

```text
own frontend UI state
own Client user profile persistence
crawl PeerTube directly during request handling
change crawler schema ownership
```

### Recommendation Pipeline

The recommendation pipeline is part of the Engine API.

At a high level:

```mermaid
flowchart TD
    Request["Recommendation Request<br/>mode / user_id / likes / limit"] --> Context["Request Context<br/>profile / likes / debug flags"]

    Context --> Sources["Candidate Sources"]
    Sources --> Similar["Similar / ANN / cache candidates"]
    Sources --> Popular["Popular candidates"]
    Sources --> Random["Random candidates"]
    Sources --> Fresh["Fresh candidates"]

    Similar --> Candidates["Candidate Set"]
    Popular --> Candidates
    Random --> Candidates
    Fresh --> Candidates

    Candidates --> Filters["Filtering<br/>dedup / hidden / caps / moderation"]
    Filters --> Scoring["Scoring<br/>similarity / freshness / popularity / layer weights"]
    Scoring --> Mixing["Mixing<br/>exploit / explore / fallback"]
    Mixing --> Rows["Stable Video Rows"]
    Rows --> Response["Recommendation Response"]
```

Detailed recommendation behavior belongs in:

```text
engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md
engine/server/api/recommendations/docs/OVERVIEW.md
engine/server/api/recommendations/docs/LAYER_PARAMS.md
```

### Crawler

The crawler owns PeerTube collection behavior.

It is responsible for:

```text
discovering instances
checking instance health
collecting channels
collecting videos
collecting tags/comments where supported
writing crawler-owned SQLite data
```

The crawler is TypeScript-based and uses:

```text
engine/crawler/src/*
engine/crawler/schema.sql
```

The crawler schema is owned by the crawler. Engine runtime migrations do not replace crawler schema ownership.

### Updater / Data Jobs

Updater jobs orchestrate offline data work.

They are responsible for:

```text
running crawler stages
building staging data
merging staging data into production datasets
building embeddings
building ANN indexes
precomputing similarity caches
recomputing popularity
handling updater locks and service restarts
```

The updater is operational orchestration. It should not own request-time API behavior.

### Databases and caches

The project has several separate data ownership areas:

```text
Client DB
  owner: Client backend
  purpose: users and local likes

Crawler DB
  owner: TypeScript crawler
  purpose: raw PeerTube crawl output

Engine dataset
  owner: Engine data/build process
  purpose: videos, channels, instances used by Engine API

Interaction tables
  owner: Engine API
  purpose: raw events and aggregate interaction signals

Derived caches
  owner: Engine jobs / Engine data layer
  purpose: similarity candidates, random feed cache, ANN-related outputs
```

## Request flows

### User opens the feed

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant C as Client Backend
    participant E as Engine API
    participant R as Recommendation Pipeline
    participant D as Engine Dataset/Caches

    U->>F: Open feed
    F->>C: POST /recommendations
    C->>E: POST /recommendations
    E->>R: Build recommendation response
    R->>D: Read candidates, metadata, caches, signals
    D-->>R: Candidate rows
    R-->>E: Ranked rows
    E-->>C: Recommendation response
    C-->>F: Recommendation response
    F-->>U: Render feed
```

### User likes a video

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant C as Client Backend
    participant DB as Client DB
    participant E as Engine API
    participant S as Interaction Signals

    U->>F: Click Like
    F->>C: POST /api/user-action
    C->>E: POST /internal/videos/resolve
    E-->>C: Canonical video identity
    C->>DB: Store local like
    C->>E: POST /internal/events/ingest
    E->>S: Store raw event and update signals
    E-->>C: Ingest result
    C-->>F: User action result
    F-->>U: Update like state
```

### Data update flow

```mermaid
flowchart LR
    PeerTube["PeerTube Instances"] --> Crawler["Crawler"]
    Crawler --> CrawlerDB[("Crawler DB")]

    Updater["Updater Worker"] --> Crawler
    Updater --> Merge["Merge staging data"]
    Merge --> EngineDB[("Engine Dataset")]

    Updater --> Embeddings["Build embeddings"]
    Embeddings --> ANN["Build ANN index"]
    ANN --> Similarity["Precompute similarity cache"]

    Similarity --> Caches[("Derived Caches")]
    EngineDB --> Engine["Engine API"]
    Caches --> Engine
```

## Dependency boundaries

These boundaries are intentional:

```text
Frontend may call Client backend HTTP routes.
Frontend must not call Engine internals directly.

Client backend may call Engine over HTTP.
Client backend must not import Engine modules or read Engine DB files directly.

Engine API may read Engine datasets, caches, and interaction tables.
Engine API must not own Client user profile persistence.

Crawler writes crawler-owned data.
Crawler does not serve frontend requests.

Updater/jobs orchestrate offline data-building work.
Updater/jobs do not own request-time API contracts.

Recommendation services are Engine-internal.
Recommendation services should remain framework-neutral where possible.
```

## What this diagram does not show

This overview intentionally does not show every module, function, or class.

It does not replace:

```text
engine/server/api/recommendations/docs/PIPELINE_DIAGRAM.md
docs/SCHEMA_OWNERSHIP.md
docs/FRAMEWORK_COMPATIBILITY.md
docs/UPDATER_COMPATIBILITY.md
docs/CRAWLER_COMPATIBILITY.md
docs/FRONTEND_COMPATIBILITY.md
```

Use this file as the high-level system map. Use the focused documents for detailed behavior and compatibility rules.
