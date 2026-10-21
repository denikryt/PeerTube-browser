"""Framework-neutral internal bridge ingest helper for interaction events."""
from __future__ import annotations

from typing import Any

from data.interaction_events import ingest_interaction_event
from route_results import RouteResult


def handle_internal_events_ingest(server: Any, body: dict[str, Any]) -> RouteResult:
    """Ingest one or more normalized interaction events idempotently."""
    events: list[dict[str, Any]]
    if isinstance(body.get("events"), list):
        events = [item for item in body["events"] if isinstance(item, dict)]
    else:
        events = [body] if isinstance(body, dict) else []

    if not events:
        return RouteResult(400, {"error": "Missing events"})

    ingested = 0
    duplicates = 0
    results: list[dict[str, Any]] = []
    try:
        with server.db_lock:
            for event in events:
                result = ingest_interaction_event(server.db, event)
                results.append(result)
                if result.get("duplicate"):
                    duplicates += 1
                else:
                    ingested += 1
    except ValueError as exc:
        return RouteResult(400, {"error": str(exc)})
    except Exception as exc:  # pragma: no cover
        return RouteResult(500, {"error": str(exc)})

    return RouteResult(
        200,
        {
            "ok": True,
            "count": len(results),
            "ingested": ingested,
            "duplicates": duplicates,
            "results": results,
        },
    )
