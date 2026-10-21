"""Client-to-Engine bridge publishing service."""
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def resolve_publish_mode(value: str, default: str = "bridge") -> str:
    """Normalize the Client publish mode to a supported current mode."""
    normalized = value.strip().lower()
    return normalized if normalized in {"bridge", "activitypub"} else default


def publish_to_engine_bridge(engine_ingest_base: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Publish one normalized Client event to Engine bridge ingest."""
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{engine_ingest_base.rstrip('/')}/internal/events/ingest",
        data=data,
        method="POST",
        headers={"content-type": "application/json"},
    )
    try:
        with urlopen(request, timeout=6) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            return {"ok": bool(parsed.get("ok", True)), "response": parsed}
    except HTTPError as exc:
        return {"ok": False, "error": f"engine bridge HTTP {exc.code}"}
    except (URLError, TimeoutError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


def publish_event(
    publish_mode: str, engine_ingest_base: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Publish one Client event using the current configured publish mode."""
    mode = resolve_publish_mode(publish_mode)
    if mode != "bridge":
        return {
            "ok": False,
            "error": "CLIENT_PUBLISH_MODE=activitypub is not implemented yet",
            "mode": mode,
        }
    return publish_to_engine_bridge(engine_ingest_base, payload)
