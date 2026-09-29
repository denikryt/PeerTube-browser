"""Browser-facing video row normalization helpers.

Engine rows may expose an ordered ``thumbnail_urls`` candidate list or the
older singular ``thumbnail_url`` compatibility field. Client API v1 owns the
browser-safe absolute URL contract and deliberately excludes ``preview_path``
from thumbnail fallback semantics.
"""
from __future__ import annotations

import re
from typing import Any

_ABSOLUTE_URL_PREFIXES = ("http://", "https://")
_SCHEME_PREFIXES = ("http://", "https://")
_EXPLICIT_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


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
    # Explicit non-HTTP schemes must not be reinterpreted as PeerTube-relative paths.
    if media.startswith("//") or _EXPLICIT_SCHEME_RE.match(media):
        return None
    host = _normalize_instance_domain(instance_domain)
    if not host:
        return None
    path = media if media.startswith("/") else f"/{media}"
    return f"https://{host}{path}"


def _normalize_thumbnail_urls(value: Any, instance_domain: Any) -> list[str]:
    """Normalize one Engine thumbnail candidate list without changing order.

    Only list values are accepted at this boundary. Invalid entries are
    skipped, relative PeerTube paths are resolved against the instance host,
    and duplicates collapse to their first normalized URL.
    """
    if not isinstance(value, list):
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for item in value:
        url = resolve_absolute_media_url(item, instance_domain)
        if url is None or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _normalize_thumbnail_dimension(value: Any) -> int | None:
    """Keep only positive integer pixel dimensions from the Engine public contract."""
    # ``bool`` is an ``int`` subclass, so exclude it before accepting dimensions.
    return value if type(value) is int and value > 0 else None


def _normalize_thumbnail_candidates(value: Any, instance_domain: Any) -> list[dict[str, str | int | None]]:
    """Normalize ordered candidate objects without exposing unsafe media URLs.

    The Engine array is authoritative when present. URL identity still deduplicates
    candidates, while size metadata stays optional for legacy and incomplete peers.
    """
    if not isinstance(value, list):
        return []
    candidates: list[dict[str, str | int | None]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        url = resolve_absolute_media_url(item.get("url"), instance_domain)
        if url is None or url in seen:
            continue
        seen.add(url)
        candidates.append(
            {
                "url": url,
                "width": _normalize_thumbnail_dimension(item.get("width")),
                "height": _normalize_thumbnail_dimension(item.get("height")),
            }
        )
    return candidates


def normalize_video_row_for_browser(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with one canonical ordered browser thumbnail contract.

    An explicitly present Engine candidate list is authoritative, including an
    empty list. Older Engine rows fall back to the singular thumbnail field.
    Preview fields are preserved but never promoted into thumbnail candidates.
    """
    normalized = dict(row)
    instance_domain = normalized.get("instance_domain") or normalized.get("instanceDomain")

    if isinstance(normalized.get("thumbnail_candidates"), list):
        candidates = _normalize_thumbnail_candidates(
            normalized.get("thumbnail_candidates"), instance_domain
        )
        urls = [str(candidate["url"]) for candidate in candidates]
    elif isinstance(normalized.get("thumbnail_urls"), list):
        urls = _normalize_thumbnail_urls(normalized.get("thumbnail_urls"), instance_domain)
        candidates = [
            {"url": url, "width": None, "height": None}
            for url in urls
        ]
    else:
        legacy = (
            resolve_absolute_media_url(normalized.get("thumbnail_url"), instance_domain)
            or resolve_absolute_media_url(normalized.get("thumbnailUrl"), instance_domain)
        )
        urls = [legacy] if legacy is not None else []
        candidates = [
            {"url": url, "width": None, "height": None}
            for url in urls
        ]

    normalized["thumbnail_candidates"] = candidates
    normalized["thumbnail_urls"] = urls
    normalized["thumbnail_url"] = urls[0] if urls else None
    return normalized


def normalize_video_rows_for_browser(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize a page of video rows without changing row count or ordering."""
    return [normalize_video_row_for_browser(row) for row in rows]
