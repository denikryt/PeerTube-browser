"""Internal bridge ingest handler for normalized interaction events."""
from __future__ import annotations

from typing import Any

from data.interaction_events import ingest_interaction_event
from http_utils import read_json_body, respond_json


def handle_internal_events_ingest(handler: Any, server: Any) -> bool:
    """Accept bridge events and ingest them idempotently into Engine DB."""
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True

    events: list[dict[str, Any]]
    if isinstance(body.get("events"), list):
        events = [item for item in body["events"] if isinstance(item, dict)]
    else:
        events = [body] if isinstance(body, dict) else []

    if not events:
        respond_json(handler, 400, {"error": "Missing events"})
        return True

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
        respond_json(handler, 400, {"error": str(exc)})
        return True
    except Exception as exc:  # pragma: no cover
        respond_json(handler, 500, {"error": str(exc)})
        return True

    respond_json(
        handler,
        200,
        {
            "ok": True,
            "count": len(results),
            "ingested": ingested,
            "duplicates": duplicates,
            "results": results,
        },
    )
    return True
