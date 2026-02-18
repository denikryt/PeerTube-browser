"""Internal read endpoints for Client -> Engine API-only contract."""
from __future__ import annotations

from typing import Any

from data.embeddings import fetch_seed_embedding
from data.metadata import fetch_metadata_by_ids
from http_utils import read_json_body, respond_json


def _like_key(entry: dict[str, Any]) -> str:
    """Handle like key."""
    return f"{entry.get('video_id') or ''}::{entry.get('instance_domain') or ''}"


def handle_internal_video_resolve(handler: Any, server: Any) -> bool:
    """Resolve canonical video identity by video_id/uuid (+ optional host)."""
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True

    video_id_raw = body.get("video_id")
    host_raw = body.get("host")
    uuid_raw = body.get("uuid")

    video_id = video_id_raw.strip() if isinstance(video_id_raw, str) else None
    host = host_raw.strip() if isinstance(host_raw, str) else None
    uuid = uuid_raw.strip() if isinstance(uuid_raw, str) else None

    if not video_id and not uuid:
        respond_json(handler, 400, {"error": "Missing video_id or uuid"})
        return True

    with server.db_lock:
        seed = fetch_seed_embedding(server.db, video_id, host, uuid)

    if not seed:
        respond_json(handler, 404, {"error": "Video not found"})
        return True

    respond_json(
        handler,
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
    return True


def handle_internal_videos_metadata(handler: Any, server: Any) -> bool:
    """Return metadata rows for canonical (video_id, instance_domain) entries."""
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True

    raw_entries = body.get("entries") if isinstance(body, dict) else None
    if not isinstance(raw_entries, list):
        respond_json(handler, 400, {"error": "Missing entries"})
        return True

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
        respond_json(handler, 200, {"ok": True, "count": 0, "rows": []})
        return True

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

    respond_json(handler, 200, {"ok": True, "count": len(rows), "rows": rows})
    return True
