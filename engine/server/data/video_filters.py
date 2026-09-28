"""Canonical Engine video-filter semantics shared by browse and search paths.

The module owns the meaning of the four public filter dimensions.  SQL callers
receive bound predicates while the finite recommendation bridge uses the row
matcher; both deliberately apply the same normalization rules.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

UNKNOWN_LANGUAGE = "_unknown"


@dataclass(frozen=True)
class VideoFilters:
    """Immutable request-scoped canonical video filter selection."""

    language: str | None = None
    category: str | None = None
    tag: str | None = None
    instance: str | None = None

    def canonical_key(self) -> tuple[str | None, str | None, str | None, str | None]:
        """Return the stable identity used to bind cursors to one selection."""
        return (self.language, self.category, self.tag, self.instance)

    def as_public_dict(self) -> dict[str, str | None]:
        """Return stable response metadata without inventing absent values."""
        return {
            "language": self.language,
            "category": self.category,
            "tag": self.tag,
            "instance": self.instance,
        }


def build_video_filter_sql(
    alias: str, filters: VideoFilters, *, schema: str = "main"
) -> tuple[str, list[object]]:
    """Build AND-composed SQLite predicates for canonical ``videos`` rows.

    ``alias`` is supplied only by trusted query code.  Values always travel as
    bound parameters, including JSON tag membership, so public input never
    becomes SQL syntax.
    """
    if schema not in {"main", "canonical"}:
        raise ValueError("Unsupported video filter schema")

    clauses: list[str] = []
    params: list[object] = []

    language_expr = f"NULLIF(lower(trim({alias}.language)), '')"
    if filters.language == UNKNOWN_LANGUAGE:
        # ``IS ?`` with a bound NULL preserves unknown-language semantics and
        # lets SQLite use the matching expression index, unlike literal
        # ``IS NULL`` on the supported SQLite planner.
        clauses.append(f"{language_expr} IS ?")
        params.append(None)
    elif filters.language is not None:
        clauses.append(f"{language_expr} = ?")
        params.append(filters.language)

    if filters.category is not None:
        clauses.append(f"lower(trim({alias}.category)) = ?")
        params.append(filters.category)

    if filters.tag is not None:
        # Runtime tag selection uses the updater-prepared normalized relation.
        # ``schema`` is validated above before interpolation so Random can point
        # at its read-only ``canonical`` attachment without exposing SQL syntax.
        clauses.append(
            f"""
            EXISTS (
              SELECT 1
              FROM {schema}.video_tags AS vt
              WHERE vt.tag = ?
                AND vt.video_id = {alias}.video_id
                AND vt.instance_domain = {alias}.instance_domain
            )
            """.strip()
        )
        params.append(filters.tag)

    if filters.instance is not None:
        clauses.append(f"lower(trim({alias}.instance_domain)) = ?")
        params.append(filters.instance)

    if not clauses:
        return "", []
    return " AND " + " AND ".join(f"({clause})" for clause in clauses), params


def matches_video_filters(row: Mapping[str, object], filters: VideoFilters) -> bool:
    """Evaluate ``VideoFilters`` against one fully resolved canonical row."""
    language = _normalized_text(row.get("language"))
    if filters.language == UNKNOWN_LANGUAGE:
        if language is not None:
            return False
    elif filters.language is not None and language != filters.language:
        return False

    category = _normalized_text(row.get("category"))
    if filters.category is not None and category != filters.category:
        return False

    if filters.tag is not None and filters.tag not in _normalized_tags(row.get("tags_json")):
        return False

    instance = _normalized_text(row.get("instance_domain"))
    if filters.instance is not None and instance != filters.instance:
        return False
    return True


def _normalized_text(value: object) -> str | None:
    """Normalize nullable scalar metadata for case-insensitive exact matching."""
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _normalized_tags(value: object) -> set[str]:
    """Return exact normalized textual JSON-array members, ignoring dirty data."""
    if value is None:
        return set()
    try:
        parsed: Any = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()
    if not isinstance(parsed, list):
        return set()
    result: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            continue
        normalized = item.strip().lower()
        if normalized:
            result.add(normalized)
    return result
