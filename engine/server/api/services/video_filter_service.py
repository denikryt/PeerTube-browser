"""Engine request parsing for the shared canonical ``VideoFilters`` value."""
from __future__ import annotations

import re
from typing import Any, Iterable

from data.moderation import normalize_host
from data.video_filters import UNKNOWN_LANGUAGE, VideoFilters, fetch_video_facets
from data.serving_moderation import serving_visibility_from_server
from route_results import RouteResult

FILTER_KEYS = ("language", "category", "tag", "instance")
_LANGUAGE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def parse_video_filters(params: dict[str, list[str]]) -> VideoFilters:
    """Parse one strict value per public filter dimension.

    Unknown-but-well-formed values are valid selections and simply match no
    rows.  Blank/repeated values are protocol errors because v1 has no implicit
    OR semantics.
    """
    raw = {key: _single_value(params, key) for key in FILTER_KEYS}

    language = _normalize_lower(raw["language"])
    if language is not None and language != UNKNOWN_LANGUAGE and not _LANGUAGE_RE.fullmatch(language):
        raise ValueError("Invalid language")

    category = _normalize_lower(raw["category"])
    tag = _normalize_lower(raw["tag"])
    if category == UNKNOWN_LANGUAGE or tag == UNKNOWN_LANGUAGE:
        raise ValueError("_unknown is only valid for language")

    instance: str | None = None
    if raw["instance"] is not None:
        if raw["instance"].strip().lower() == UNKNOWN_LANGUAGE:
            raise ValueError("_unknown is only valid for language")
        instance = normalize_host(raw["instance"])
        if not instance:
            raise ValueError("Invalid instance")

    return VideoFilters(language=language, category=category, tag=tag, instance=instance)


def allowed_with_filters(*keys: str) -> set[str]:
    """Return a route allowlist extended with the four shared filter keys."""
    return set(keys).union(FILTER_KEYS)


def _single_value(params: dict[str, list[str]], key: str) -> str | None:
    """Read one non-blank query value while rejecting repeated dimensions."""
    values = params.get(key)
    if values is None:
        return None
    if len(values) != 1:
        raise ValueError(f"Repeated query parameter: {key}")
    value = str(values[0])
    if not value.strip():
        raise ValueError(f"Invalid {key}")
    return value


def _normalize_lower(value: str | None) -> str | None:
    """Normalize case-insensitive public scalar values without inventing data."""
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def handle_internal_video_facets(server: Any) -> RouteResult:
    """Return global facets over the same service-visible corpus as browse/search."""
    visibility = serving_visibility_from_server(server)
    with server.db_lock:
        payload = fetch_video_facets(server.db, visibility=visibility)
    return RouteResult(200, payload)
