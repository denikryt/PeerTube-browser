# Architecture

## Purpose

This document defines the current PeerTube Browser component boundaries and the runtime data flow that must remain stable during refactoring.

## Runtime Flow

```text
crawler -> SQLite datasets/indexes/caches -> Engine API -> Client backend -> Frontend
```

The crawler and update jobs build local datasets and derived artifacts. The Engine API reads those artifacts and serves metadata, recommendations, and internal ingest endpoints. The Client backend is the browser-facing gateway and owns local user/profile state. The frontend renders UI and talks to the Client backend.

## Component Ownership

### Frontend

The frontend owns page state, rendering, UI interactions, and calls to the Client backend. It must not call Engine internal or read APIs directly.

### Client Backend

The Client backend owns browser-facing profile and write behavior, local user data, Client API error shaping, and HTTP gateway calls to Engine. It must not import Engine modules or read Engine database files directly.

### Engine API

The Engine API owns recommendation behavior, video/channel metadata reads, internal Client-to-Engine contracts, interaction ingest, and Engine-readable data access. It must not own Client local user profile persistence.

### Crawler and Jobs

The crawler and data-build jobs own PeerTube data collection, dataset updates, derived artifacts, and schema production for Engine consumption. Generated crawler JavaScript is a build output, not source code.

## Forbidden Coupling

- Frontend code must not bypass the Client backend to call Engine directly.
- Client backend code must not import Engine internals or read Engine DB files directly.
- Engine code must not own browser profile state.
- Crawler build outputs must not be committed as source files.

## Refactoring Rule

Structural refactoring should preserve these boundaries until a later plan explicitly changes them with tests and documentation updates.
