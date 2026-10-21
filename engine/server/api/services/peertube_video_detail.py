"""Observe one PeerTube video without changing canonical Engine state.

A request uses only the stored origin and UUID. Redirects are deliberately not
followed: a 404 at a redirected resource cannot establish video absence.
"""

from __future__ import annotations

import json
import logging
from http.client import HTTPException
from dataclasses import dataclass
from typing import Any, Literal
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


@dataclass(frozen=True)
class VideoDetailResult:
    """One request-scoped observation, never authority to publish availability."""

    kind: Literal["available", "not_found", "gone", "unknown"]
    detail: dict[str, Any] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        """Reject contradictory observations at the closest result boundary."""
        if self.kind not in {"available", "not_found", "gone", "unknown"}:
            raise ValueError("Invalid video-detail result kind")
        if (self.kind == "available") != (self.detail is not None):
            raise ValueError("Only available video detail may carry a projection")
        if self.kind == "unknown" and not self.error:
            raise ValueError("Unknown video detail must carry a reason")
        if self.kind != "unknown" and self.error is not None:
            raise ValueError("Only unknown video detail may carry an error")


class _NoRedirectHandler(HTTPRedirectHandler):
    """Prevent following any redirect, including one on the same HTTPS origin."""

    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        """Leave 3xx at the initiating resource for safe unknown classification."""
        return None


def _valid_origin(host: str) -> bool:
    """Ensure a stored host is a single HTTPS authority, never a URL or path."""
    if not isinstance(host, str) or not host or host != host.strip():
        return False
    try:
        parsed = urlsplit(f"https://{host}")
        return (
            parsed.netloc == host
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.port != 0
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def _request_json(opener: Any, url: str) -> tuple[int, Any]:
    """Fetch JSON once with an 8-second timeout and no HTTP redirect follow."""
    req = Request(url, headers={"Accept": "application/json"})
    try:
        with opener.open(req, timeout=8) as response:
            if response.status != 200:
                return response.status, None
            return 200, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # The opener never follows redirects, so any 404/410 is from this URL.
        return exc.code, None


def _text(*values: Any) -> str | None:
    """Select the first nonblank string from optional remote fields."""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _number(*values: Any) -> int | None:
    """Normalize numeric counts, excluding booleans and unrecognized objects."""
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and abs(value) != float('inf') and value == value:
            return int(value)
        if isinstance(value, str) and value.isdigit():
            # Unicode digit classifications and oversized numbers need not be
            # convertible by int(); optional counters never invalidate detail.
            try:
                return int(value)
            except ValueError:
                continue
    return None


def _avatar(host: str, source: dict[str, Any]) -> str:
    """Resolve existing PeerTube avatar fields for response use only."""
    avatar = source.get("avatar")
    if not isinstance(avatar, dict):
        return ""
    value = _text(avatar.get("url"), avatar.get("path"))
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("/"):
        return f"https://{host}{value}"
    return ""


def _project_detail(host: str, detail: dict[str, Any], opener: Any) -> dict[str, Any]:
    """Extract only the fields consumed by the public video response."""
    account = detail.get("account")
    account = account if isinstance(account, dict) else {}
    channel = detail.get("channel")
    channel = channel if isinstance(channel, dict) else {}
    channel_slug = _text(channel.get("name"))
    channel_display = _text(channel.get("displayName"), channel.get("display_name"))
    channel_followers = _number(
        channel.get("followersCount"), channel.get("followers_count"), channel.get("followers")
    )
    if channel_slug and (channel_display is None or channel_followers is None):
        try:
            status, supplement = _request_json(
                opener, f"https://{host}/api/v1/video-channels/{quote(channel_slug, safe='')}"
            )
            if status == 200 and isinstance(supplement, dict):
                channel_display = channel_display or _text(
                    supplement.get("displayName"), supplement.get("display_name")
                )
                if channel_followers is None:
                    channel_followers = _number(
                        supplement.get("followersCount"), supplement.get("followers_count"),
                        supplement.get("followers")
                    )
        except (OSError, HTTPException, ValueError):
            # HTTPException includes incomplete/invalid HTTP responses; network
            # and enrichment failures cannot change primary video availability.
            pass
    return {
        "title": _text(detail.get("name"), detail.get("title")),
        "description": _text(detail.get("description")),
        "views": _number(detail.get("views"), detail.get("viewsCount"), detail.get("views_count")),
        "likes": _number(detail.get("likes"), detail.get("likesCount"), detail.get("likes_count")),
        "dislikes": _number(detail.get("dislikes"), detail.get("dislikesCount"), detail.get("dislikes_count")),
        "channel_slug": channel_slug,
        "channel_display": channel_display,
        "channel_followers": channel_followers,
        "account_avatar_url": _avatar(host, account) or _avatar(host, detail),
    }


def fetch_peertube_video_detail(host: str, video_uuid: str) -> VideoDetailResult:
    """Classify the stored PeerTube video identity without any persistent writes.

    Only a direct 404/410 at the original video-detail endpoint establishes
    request-scoped absence. Redirects, invalid identity and transport errors
    preserve the cached Engine response by returning ``unknown``.
    """
    if not _valid_origin(host) or not isinstance(video_uuid, str) or not video_uuid.strip():
        return VideoDetailResult("unknown", error="invalid stored video identity")
    opener = build_opener(_NoRedirectHandler())
    url = f"https://{host}/api/v1/videos/{quote(video_uuid, safe='')}"
    try:
        status, detail = _request_json(opener, url)
    except (OSError, HTTPException, ValueError):
        # OSError includes timeouts and URL errors; HTTPException covers broken
        # HTTP response framing that would otherwise escape as a server error.
        logging.info("[video] detail request failed for stored video identity")
        return VideoDetailResult("unknown", error="video detail request failed")
    if status == 404:
        return VideoDetailResult("not_found")
    if status == 410:
        return VideoDetailResult("gone")
    if status != 200:
        return VideoDetailResult("unknown", error="video detail unexpected HTTP status")
    if not isinstance(detail, dict) or not isinstance(detail.get("uuid"), str) or detail["uuid"] != video_uuid:
        return VideoDetailResult("unknown", error="video detail identity mismatch")
    return VideoDetailResult("available", detail=_project_detail(host, detail, opener))
