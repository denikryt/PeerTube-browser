"""Client user action service for local profile updates and bridge publishing."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from lib.engine_api_client import EngineApiError, resolve_video_seed
from lib.http_utils import resolve_user_id
from lib.time_utils import now_ms
from repositories.users import UsersRepository
from schemas import ServiceResult

from services.bridge_publisher import publish_event


def _default_event_id() -> str:
    """Create the current Client event id shape for bridge events."""
    return f"client-{uuid4()}"


def handle_user_action(
    users: UsersRepository,
    engine_base_url: str,
    publish_mode: str,
    body: dict[str, Any],
    max_likes: int,
    event_id_factory: Callable[[], str] = _default_event_id,
    now_ms_func: Callable[[], int] = now_ms,
) -> ServiceResult:
    """Apply one Client user action and publish the matching Engine interaction event."""
    action = str(body.get("action") or "").strip().lower()
    if action not in {"like", "dislike", "undo_like"}:
        return ServiceResult(400, {"error": "Unsupported action"})

    video_id = body.get("video_id")
    host = body.get("host")
    uuid = body.get("uuid")
    user_id_raw = body.get("user_id")
    if not video_id and not uuid:
        return ServiceResult(400, {"error": "Missing video_id or uuid"})
    user_id = resolve_user_id(str(user_id_raw) if user_id_raw is not None else None)

    try:
        seed = resolve_video_seed(
            engine_base_url,
            str(video_id) if video_id is not None else None,
            str(host) if host is not None else None,
            str(uuid) if uuid is not None else None,
        )
    except EngineApiError as exc:
        return ServiceResult(502, {"error": f"Engine resolve failed: {exc}"})

    if not seed:
        return ServiceResult(404, {"error": "Video not found in Engine"})

    canonical_video_id = str(seed.get("video_id") or "")
    canonical_host = str(seed.get("instance_domain") or "")
    canonical_uuid = str(seed.get("video_uuid") or "")
    if not canonical_video_id or not canonical_host:
        return ServiceResult(502, {"error": "Engine resolve returned incomplete identity"})

    if action == "like":
        users.record_like(
            user_id,
            {
                "video_id": canonical_video_id,
                "video_uuid": canonical_uuid,
                "instance_domain": canonical_host,
            },
            max_likes,
        )
        event_type = "Like"
    else:
        users.remove_like(user_id, canonical_video_id, canonical_host)
        event_type = "UndoLike"

    # The local profile write intentionally happens before bridge publishing; Stage 0
    # characterizes that a bridge failure does not roll back the local like.
    event_payload = {
        "event_id": event_id_factory(),
        "event_type": event_type,
        "actor_id": user_id,
        "object": {
            "video_uuid": canonical_uuid,
            "instance_domain": canonical_host,
            "canonical_url": seed.get("video_url"),
        },
        "published_at": now_ms_func(),
        "source_instance": canonical_host,
        "raw_payload": body,
    }
    bridge_result = publish_event(publish_mode, engine_base_url, event_payload)
    return ServiceResult(
        200 if bridge_result.get("ok") else 502,
        {
            "ok": bridge_result.get("ok", False),
            "bridge_ok": bridge_result.get("ok", False),
            "bridge_error": bridge_result.get("error"),
            "user_id": user_id,
            "updatedAt": now_ms_func(),
        },
    )
