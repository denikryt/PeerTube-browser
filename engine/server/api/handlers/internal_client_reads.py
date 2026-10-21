"""Framework-neutral internal read helpers for Client -> Engine contracts."""
from __future__ import annotations

from typing import Any

from data.embeddings import fetch_seed_embedding
from data.metadata import fetch_metadata_by_ids
from route_results import RouteResult


def _like_key(entry: dict[str, Any]) -> str:
    """Return the current metadata lookup key for one liked video identity."""
    return f"{entry.get('video_id') or ''}::{entry.get('instance_domain') or ''}"


def handle_internal_video_resolve(server: Any, body: dict[str, Any]) -> RouteResult:
    """Resolve canonical video identity by video_id/uuid and optional host."""
    video_id_raw = body.get("video_id")
    host_raw = body.get("host")
    uuid_raw = body.get("uuid")

    video_id = video_id_raw.strip() if isinstance(video_id_raw, str) else None
    host = host_raw.strip() if isinstance(host_raw, str) else None
    uuid = uuid_raw.strip() if isinstance(uuid_raw, str) else None

    if not video_id and not uuid:
        return RouteResult(400, {"error": "Missing video_id or uuid"})

    with server.db_lock:
        seed = fetch_seed_embedding(server.db, video_id, host, uuid)

    if not seed:
        return RouteResult(404, {"error": "Video not found"})

    return RouteResult(
        200,
        {
            "ok": True,
            "video": {
                "video_id": seed.get("video_id"),
                "video_uuid": seed.get("video_uuid"),
                "instance_domain": seed.get("instance_domain"),
                "channel_id": seed.get("channel_id"),
                "title": seed.get("title"),
            },
        },
    )


def handle_internal_videos_metadata(server: Any, body: dict[str, Any]) -> RouteResult:
    """Return metadata rows for canonical video_id and instance_domain entries."""
    raw_entries = body.get("entries") if isinstance(body, dict) else None
    if not isinstance(raw_entries, list):
        return RouteResult(400, {"error": "Missing entries"})

    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        video_id_raw = raw.get("video_id")
        instance_raw = raw.get("instance_domain")
        if not isinstance(video_id_raw, str) or not video_id_raw.strip():
            continue
        if not isinstance(instance_raw, str) or not instance_raw.strip():
            continue
        entry = {
            "video_id": video_id_raw.strip(),
            "instance_domain": instance_raw.strip(),
        }
        key = _like_key(entry)
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)

    if not entries:
        return RouteResult(200, {"ok": True, "count": 0, "rows": []})

    with server.db_lock:
        metadata = fetch_metadata_by_ids(
            server.db,
            entries,
            error_threshold=getattr(server, "video_error_threshold", None),
        )

    rows: list[dict[str, Any]] = []
    for entry in entries:
        row = metadata.get(_like_key(entry))
        if isinstance(row, dict):
            rows.append(row)

    return RouteResult(200, {"ok": True, "count": len(rows), "rows": rows})
