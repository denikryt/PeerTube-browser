"""Client public-protocol parsing for shared video filter query parameters.

The Client owns only cardinality, blank-value rejection and cursor identity.
Semantic normalization and matching remain Engine responsibilities.
"""
from __future__ import annotations

from dataclasses import dataclass

FILTER_KEYS = ("language", "category", "tag", "instance")


@dataclass(frozen=True)
class PublicVideoFilters:
    """Raw trimmed public filter selection used for forwarding and cursor binding."""

    language: str | None = None
    category: str | None = None
    tag: str | None = None
    instance: str | None = None

    def as_query(self) -> dict[str, str]:
        """Return only selected values for Engine forwarding."""
        return {key: value for key, value in self.as_dict().items() if value is not None}

    def as_dict(self) -> dict[str, str | None]:
        """Return the stable public response representation."""
        return {key: getattr(self, key) for key in FILTER_KEYS}

    def cursor_key(self) -> list[str | None]:
        """Return a stable ordered binding representation for public cursors."""
        return [getattr(self, key) for key in FILTER_KEYS]


def parse_public_video_filters(params: dict[str, list[str]]) -> PublicVideoFilters:
    """Require at most one non-blank raw value for each filter dimension."""
    values: dict[str, str | None] = {}
    for key in FILTER_KEYS:
        raw_values = params.get(key)
        if raw_values is None:
            values[key] = None
            continue
        if len(raw_values) != 1:
            raise ValueError(f"Repeated query parameter: {key}")
        value = str(raw_values[0]).strip()
        if not value:
            raise ValueError(f"Invalid {key}")
        values[key] = value
    return PublicVideoFilters(**values)
