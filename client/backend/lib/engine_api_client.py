"""HTTP client helpers for Client -> Engine read/bridge contracts."""
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EngineApiError(RuntimeError):
    """Engine API request failed."""



def _post_json(url: str, payload: dict[str, Any], timeout: int = 6) -> tuple[int, dict[str, Any]]:
    """Handle post json."""
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method="POST",
        headers={"content-type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            body = response.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            if isinstance(parsed, dict):
                return status, parsed
            return status, {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        parsed: dict[str, Any] = {}
        if body:
            try:
                maybe = json.loads(body)
                if isinstance(maybe, dict):
                    parsed = maybe
            except json.JSONDecodeError:
                parsed = {}
        return int(exc.code), parsed
    except (URLError, TimeoutError) as exc:
        raise EngineApiError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise EngineApiError(str(exc)) from exc


def resolve_video_seed(
    engine_base_url: str,
    video_id: str | None,
    host: str | None,
    uuid: str | None,
) -> dict[str, Any] | None:
    """Resolve canonical video identity in Engine by id/uuid + host."""
    payload: dict[str, Any] = {}
    if video_id:
        payload["video_id"] = video_id
    if host:
        payload["host"] = host
    if uuid:
        payload["uuid"] = uuid
    status, body = _post_json(f"{engine_base_url.rstrip('/')}/internal/videos/resolve", payload)
    if status == 404:
        return None
    if status != 200:
        message = body.get("error") if isinstance(body, dict) else None
        raise EngineApiError(f"Engine resolve failed (HTTP {status}): {message or 'unknown error'}")
    video = body.get("video") if isinstance(body, dict) else None
    if not isinstance(video, dict):
        raise EngineApiError("Engine resolve returned invalid payload")
    return video


def fetch_metadata_for_entries(
    engine_base_url: str,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fetch metadata rows from Engine for canonical video identity entries."""
    if not entries:
        return []
    status, body = _post_json(
        f"{engine_base_url.rstrip('/')}/internal/videos/metadata",
        {"entries": entries},
    )
    if status != 200:
        message = body.get("error") if isinstance(body, dict) else None
        raise EngineApiError(f"Engine metadata failed (HTTP {status}): {message or 'unknown error'}")
    rows = body.get("rows") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise EngineApiError("Engine metadata returned invalid payload")
    return [row for row in rows if isinstance(row, dict)]


def resolve_videos_by_uuid_host(
    engine_base_url: str,
    likes: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Resolve uuid/host likes to canonical Engine video identity entries."""
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in likes:
        uuid = str(entry.get("video_uuid") or "").strip()
        host = str(entry.get("instance_domain") or "").strip()
        if not uuid or not host:
            continue
        dedupe_key = f"{uuid}::{host}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        video = resolve_video_seed(engine_base_url, None, host, uuid)
        if not video:
            continue
        video_id = str(video.get("video_id") or "").strip()
        instance_domain = str(video.get("instance_domain") or "").strip()
        if not video_id or not instance_domain:
            continue
        resolved.append(
            {
                "video_id": video_id,
                "video_uuid": video.get("video_uuid"),
                "instance_domain": instance_domain,
            }
        )
    return resolved
