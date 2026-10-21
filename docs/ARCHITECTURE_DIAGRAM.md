# Architecture Diagrams

Purpose: show the system structure and its main data and request flows.

## System

```mermaid
flowchart LR
    Browser --> Frontend
    Frontend -->|public HTTP API| Client
    Client -->|profile and likes| ClientDB[(Client DB)]
    Client -->|HTTP| Engine
    Engine --> Canonical[(Canonical DB)]
    Engine --> Similarity[(Similarity cache)]
    Engine --> Random[(Random cache)]
    Engine --> ANN[(FAISS index)]
    PeerTube --> Crawler
    Crawler --> CrawlDB[(Crawler DB)]
    CrawlDB --> Updater
    Updater --> Canonical
    Updater --> Similarity
    Updater --> Random
    Updater --> ANN
```

## Discovery Request

```mermaid
sequenceDiagram
    participant B as Browser
    participant F as Frontend
    participant C as Client
    participant E as Engine
    participant D as Engine data

    B->>F: Open feed or search
    F->>C: Browser-facing request
    C->>E: Provider request
    E->>D: Read canonical and derived data
    D-->>E: Rows and candidates
    E-->>C: Engine result
    C-->>F: Browser response
    F-->>B: Render
```

## User Action

```mermaid
sequenceDiagram
    participant F as Frontend
    participant C as Client
    participant CDB as Client DB
    participant E as Engine
    participant S as Interaction tables

    F->>C: POST /api/user-action
    C->>E: Resolve canonical video identity
    E-->>C: Canonical identity
    C->>CDB: Persist local profile action
    C->>E: POST /internal/events/ingest
    E->>S: Persist event and aggregate signal
    E-->>C: Ingest result
    C-->>F: Action result
```

## Recommendations

```mermaid
flowchart TD
    Request --> Profile{Likes available?}
    Profile -->|yes| Personalized[home or upnext profile]
    Profile -->|no| Guest[guest profile]
    Personalized --> Sources
    Guest --> Sources
    Sources --> Exploit[exploit]
    Sources --> Explore[explore]
    Sources --> Popular[popular]
    Sources --> Random[random]
    Sources --> Fresh[fresh]
    Exploit --> Filters
    Explore --> Filters
    Popular --> Filters
    Random --> Filters
    Fresh --> Filters
    Filters --> Score[score]
    Score --> Mix[mix by profile ratios]
    Mix --> Dedup[deduplicate and apply caps]
    Dedup --> Response
```

## Data Refresh

```mermaid
flowchart LR
    PeerTube --> Crawler
    Crawler --> Staging[(Staging DB)]
    Staging --> Embeddings[Build embeddings]
    Embeddings --> Merge[Merge canonical data]
    Merge --> Prepared[Prepared Discovery and Search]
    Prepared --> StableIDs[Stable index IDs]
    StableIDs --> ANN[FAISS]
    StableIDs --> Random[Random cache]
    ANN --> Similarity[Similarity cache]
    Merge --> Canonical[(Production DB)]
    ANN --> Engine
    Random --> Engine
    Similarity --> Engine
    Canonical --> Engine
```

## Parent Lifecycle and Publication

```mermaid
flowchart LR
    Scope[Frozen host selection] --> Reset[Reset page-zero progress]
    Reset --> Probe[Instance probe]
    Probe --> Channels[Channel enumeration and health]
    Channels --> Eligibility{Fresh ok + done + provenance?}
    Eligibility -->|yes| Children[Counts and video detail]
    Eligibility -->|no| Hold[No child requests]
    Children --> Stage[(Staging DB)]
    Channels --> Stage
    Stage --> Merge[INSERT NULL + JSON1-scoped health UPDATE]
    Merge --> Canonical[(Canonical DB)]
    Merge --> Invalidate[Prepared Discovery invalidation]
```

A confirmed local network outage prevents new work across all active host queues; previously started operations drain before staging closes. The canonical Engine side independently filters videos with explicit parent health errors.
