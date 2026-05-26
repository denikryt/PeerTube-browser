"""Channel query parsing for the Engine API channel route.

The service preserves the existing ``/api/channels`` parsing semantics while
moving route-specific parameter normalization out of the stdlib HTTP handler.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from data.channels import fetch_channels

try:
    from engine.server.api.services.recommendation_service import (
        _parse_int,
        _parse_non_negative_int,
    )
except ModuleNotFoundError:  # pragma: no cover - direct server.py execution path
    from services.recommendation_service import _parse_int, _parse_non_negative_int


@dataclass(frozen=True)
class ChannelQuery:
    """Normalized channel-listing query values used by ``fetch_channels``."""

    limit: int
    offset: int
    query: str
    instance: str
    min_followers: int
    min_videos: int
    max_videos: int | None
    sort: str
    direction: str


def parse_channel_query(params: dict[str, list[str]]) -> ChannelQuery:
    """Parse ``/api/channels`` query params with the current fallback semantics."""
    limit = _parse_int(params.get("limit", [None])[0])
    if limit <= 0:
        limit = 100
    limit = min(limit, 500)
    return ChannelQuery(
        limit=limit,
        offset=_parse_int(params.get("offset", [None])[0]),
        query=params.get("q", [""])[0] or "",
        instance=params.get("instance", [""])[0] or "",
        min_followers=_parse_int(params.get("minFollowers", [None])[0]),
        min_videos=_parse_int(params.get("minVideos", [None])[0]),
        max_videos=_parse_non_negative_int(params.get("maxVideos", [None])[0]),
        sort=params.get("sort", ["followers"])[0] or "followers",
        direction=params.get("dir", ["desc"])[0] or "desc",
    )


def fetch_channel_rows(server: Any, query: ChannelQuery) -> tuple[list[dict[str, Any]], int]:
    """Fetch channel rows under the server DB lock using existing data access."""
    with server.db_lock:
        return fetch_channels(
            server.db,
            limit=query.limit,
            offset=query.offset,
            query=query.query,
            instance=query.instance,
            min_followers=query.min_followers,
            min_videos=query.min_videos,
            max_videos=query.max_videos,
            sort=query.sort,
            direction=query.direction,
        )
