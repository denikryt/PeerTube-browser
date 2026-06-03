"""Browser-facing video row normalization helpers.

The Engine and crawler intentionally expose both ``thumbnail_url`` and
``preview_path`` because they come from different PeerTube source fields.
Client API v1 still owes browsers one directly usable card-image URL, so this
module preserves source fields while writing the best absolute image URL to
``thumbnail_url`` in public video rows.
"""
from __future__ import annotations

from typing import Any

_ABSOLUTE_URL_PREFIXES = ("http://", "https://")
_SCHEME_PREFIXES = ("http://", "https://")


def _clean_string(value: Any) -> str | None:
    """Return a non-empty stripped string or ``None`` for unusable inputs."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_instance_domain(instance_domain: Any) -> str | None:
    """Normalize an instance host for joining relative PeerTube asset paths."""
    host = _clean_string(instance_domain)
    if not host:
        return None
    for prefix in _SCHEME_PREFIXES:
        if host.lower().startswith(prefix):
            host = host[len(prefix) :]
            break
    return host.strip("/") or None


def resolve_absolute_media_url(value: Any, instance_domain: Any) -> str | None:
    """Resolve a video media field into an absolute browser-safe URL.

    ``thumbnail_url`` is usually already absolute, but PeerTube preview fields
    are often relative paths. Protocol-relative URLs are deliberately rejected
    so the Client v1 API does not emit scheme-ambiguous browser URLs.
    """
    media = _clean_string(value)
    if not media:
        return None
    lowered = media.lower()
    if lowered.startswith(_ABSOLUTE_URL_PREFIXES):
        return media
    if media.startswith("//") or "://" in media:
        return None
    host = _normalize_instance_domain(instance_domain)
    if not host:
        return None
    path = media if media.startswith("/") else f"/{media}"
    return f"https://{host}{path}"


def normalize_video_row_for_browser(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of one video row with canonical browser ``thumbnail_url``.

    The source row is never mutated. ``preview_path`` remains unchanged as a
    source/compatibility field, while ``thumbnail_url`` becomes the best
    absolute card image URL the browser can use directly.
    """
    normalized = dict(row)
    instance_domain = normalized.get("instance_domain") or normalized.get("instanceDomain")

    # PeerTube rows may have a missing thumbnail but a relative preview poster;
    # Client v1 owns this browser-facing fallback instead of leaking it into Vue.
    thumbnail = (
        resolve_absolute_media_url(normalized.get("thumbnail_url"), instance_domain)
        or resolve_absolute_media_url(normalized.get("thumbnailUrl"), instance_domain)
        or resolve_absolute_media_url(normalized.get("preview_path"), instance_domain)
        or resolve_absolute_media_url(normalized.get("previewPath"), instance_domain)
    )
    normalized["thumbnail_url"] = thumbnail
    return normalized


def normalize_video_rows_for_browser(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize a page of video rows without changing row count or ordering."""
    return [normalize_video_row_for_browser(row) for row in rows]
