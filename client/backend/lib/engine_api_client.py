"""HTTP client helpers for Client -> Engine read/bridge contracts."""
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_ENGINE_TIMEOUT_SECONDS = 6
RECOMMENDATIONS_ENGINE_TIMEOUT_SECONDS = 20


class EngineApiError(RuntimeError):
    """Engine API request failed, preserving HTTP status/body when available."""

    def __init__(self, message: str, *, status: int | None = None, body: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body or {}

    @property
    def code(self) -> str | None:
        """Return an Engine machine-readable error code when one was supplied."""
        value = self.body.get("code")
        return str(value) if isinstance(value, str) and value else None


def _http_error(operation: str, status: int, body: dict[str, Any]) -> EngineApiError:
    """Build a structured Engine HTTP error without conflating it with transport failure."""
    message = body.get("error") if isinstance(body, dict) else None
    return EngineApiError(
        f"Engine {operation} failed (HTTP {status}): {message or 'unknown error'}",
        status=status,
        body=body,
    )



def _post_json(
    url: str,
    payload: dict[str, Any],
    timeout: int = DEFAULT_ENGINE_TIMEOUT_SECONDS,
) -> tuple[int, dict[str, Any]]:
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



def _get_json(
    url: str,
    query: dict[str, Any] | None = None,
    timeout: int = DEFAULT_ENGINE_TIMEOUT_SECONDS,
) -> tuple[int, dict[str, Any]]:
    """Handle get json."""
    if query:
        encoded = urlencode({key: value for key, value in query.items() if value is not None})
        if encoded:
            url = f"{url}?{encoded}"
    request = Request(url, method="GET", headers={"accept": "application/json"})
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


def fetch_engine_video(
    engine_base_url: str,
    video_id_or_uuid: str,
    host: str,
) -> tuple[int, dict[str, Any]]:
    """Fetch one Engine video metadata payload by id/uuid and host."""
    return _get_json(
        f"{engine_base_url.rstrip('/')}/api/video",
        {"id": video_id_or_uuid, "host": host},
    )


def fetch_engine_similar(
    engine_base_url: str,
    video_id_or_uuid: str,
    host: str,
    limit: int,
    debug: bool = False,
) -> dict[str, Any]:
    """Fetch Engine similar rows using existing path-id route."""
    query: dict[str, Any] = {"host": host, "limit": limit}
    if debug:
        query["debug"] = "1"
    status, body = _get_json(
        f"{engine_base_url.rstrip('/')}/videos/{video_id_or_uuid}/similar",
        query,
    )
    if status != 200:
        raise EngineApiError(f"Engine similar failed (HTTP {status}): {body.get('error') or 'unknown error'}")
    return body


def fetch_engine_recommendations(
    engine_base_url: str,
    likes: list[dict[str, str]],
    user_id: str,
    limit: int,
    debug: bool = False,
    filters: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch the finite Engine home recommendation batch with optional video filters."""
    query: dict[str, Any] = {"limit": str(limit), "user_id": user_id, **(filters or {})}
    if debug:
        query["debug"] = "1"
    url = f"{engine_base_url.rstrip('/')}/recommendations?{urlencode(query)}"
    status, body = _post_json(
        url,
        {"likes": likes, "user_id": user_id, "mode": "home"},
        timeout=RECOMMENDATIONS_ENGINE_TIMEOUT_SECONDS,
    )
    if status != 200:
        raise _http_error("recommendations", status, body)
    return body


def fetch_engine_discovery(
    engine_base_url: str,
    source: str,
    limit: int,
    provider_cursor: str | None,
    filters: dict[str, str],
) -> dict[str, Any]:
    """Fetch one Engine-owned paged Discovery provider page."""
    if source not in {"fresh", "popular", "random"}:
        raise ValueError("Unsupported discovery source")
    query: dict[str, Any] = {"limit": limit, **filters}
    if provider_cursor:
        query["cursor"] = provider_cursor
    status, body = _get_json(
        f"{engine_base_url.rstrip('/')}/internal/discovery/{source}", query
    )
    if status != 200:
        raise _http_error(f"discovery {source}", status, body)
    return body


def fetch_engine_video_search(
    engine_base_url: str,
    query: str,
    limit: int,
    offset: int,
    filters: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch Engine internal video search provider rows over HTTP."""
    request_query: dict[str, Any] = {"q": query, "limit": limit, "cursor": str(offset), **(filters or {})}
    status, body = _get_json(
        f"{engine_base_url.rstrip('/')}/internal/search/videos",
        request_query,
    )
    if status != 200:
        raise _http_error("video search", status, body)
    return body


def fetch_engine_video_facets(engine_base_url: str) -> dict[str, Any]:
    """Fetch global service-visible video facets from Engine."""
    status, body = _get_json(f"{engine_base_url.rstrip('/')}/internal/video-facets")
    if status != 200:
        raise _http_error("video facets", status, body)
    return body


def fetch_engine_channel_search(
    engine_base_url: str,
    query: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Fetch Engine channel search rows through the existing channel route."""
    status, body = _get_json(
        f"{engine_base_url.rstrip('/')}/api/channels",
        {"q": query, "limit": limit, "offset": offset},
    )
    if status != 200:
        raise _http_error("channel search", status, body)
    return body
