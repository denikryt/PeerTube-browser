"""Normalize persisted thumbnail candidate state into Engine API fields.

Crawler-owned storage distinguishes SQL ``NULL`` from authoritative JSON arrays
of normalized candidate objects. This module is the single Engine boundary that
interprets that state. It never queries SQLite and never promotes preview fields.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse


def _legacy_thumbnail_urls(value: object) -> list[str]:
    """Return the singular compatibility thumbnail as a one-item list when usable."""
    if not isinstance(value, str):
        return []
    text = value.strip()
    return [text] if text else []


def _valid_positive_dimension(value: object) -> int | None:
    """Return one safe public dimension or ``None`` for unknown candidate metadata."""
    # ``bool`` is an ``int`` subclass, but it is not a meaningful pixel dimension.
    return value if type(value) is int and value > 0 else None


def _authoritative_http_candidates(value: list[object]) -> list[dict[str, str | int | None]]:
    """Extract valid candidate objects while preserving crawler order and URL uniqueness."""
    candidates: list[dict[str, str | int | None]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        raw_url = item.get("url")
        if not isinstance(raw_url, str):
            continue
        text = raw_url.strip()
        if not text or text in seen:
            continue
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        seen.add(text)
        candidates.append(
            {
                "url": text,
                "width": _valid_positive_dimension(item.get("width")),
                "height": _valid_positive_dimension(item.get("height")),
            }
        )
    return candidates


def thumbnail_candidates_from_storage(
    candidates_json: object,
    legacy_thumbnail_url: object,
) -> list[dict[str, str | int | None]]:
    """Decode crawler storage into browser candidates with optional image dimensions.

    A parsed array is authoritative, including ``[]``. SQL ``NULL`` and malformed
    storage retain the legacy singular compatibility URL as one dimension-unknown
    candidate, so older PeerTube detail shapes remain usable by the browser.
    """
    def legacy_candidates() -> list[dict[str, str | int | None]]:
        return [
            {"url": url, "width": None, "height": None}
            for url in _legacy_thumbnail_urls(legacy_thumbnail_url)
        ]

    if candidates_json is None or not isinstance(candidates_json, str):
        return legacy_candidates()
    try:
        parsed = json.loads(candidates_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return legacy_candidates()
    if isinstance(parsed, list):
        return _authoritative_http_candidates(parsed)
    return legacy_candidates()


def thumbnail_urls_from_storage(
    candidates_json: object,
    legacy_thumbnail_url: object,
) -> list[str]:
    """Decode persisted candidate state into the ordered public URL list.

    SQL ``NULL`` is the intentional legacy/unavailable state. A successfully
    parsed top-level array is authoritative even if some members are corrupt.
    Parse failures and non-array top-level values fail soft to the singular
    legacy field instead of failing the whole video response.
    """
    return [
        str(candidate["url"])
        for candidate in thumbnail_candidates_from_storage(candidates_json, legacy_thumbnail_url)
    ]


def apply_thumbnail_api_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Return a row with public thumbnail fields and without storage JSON.

    This copy-at-boundary helper keeps route projections consistent: all Engine
    providers expose full ``thumbnail_candidates``, the compatible URL-only list,
    and a singular first-candidate mirror while the crawler storage document
    remains internal.
    """
    normalized = dict(row)
    candidates = thumbnail_candidates_from_storage(
        normalized.pop("thumbnail_candidates_json", None),
        normalized.get("thumbnail_url"),
    )
    urls = [str(candidate["url"]) for candidate in candidates]
    normalized["thumbnail_candidates"] = candidates
    normalized["thumbnail_urls"] = urls
    normalized["thumbnail_url"] = urls[0] if urls else None
    return normalized
