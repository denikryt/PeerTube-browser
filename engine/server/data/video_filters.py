"""Canonical Engine video-filter semantics shared by browse and search paths.

The module owns the meaning of the four public filter dimensions.  SQL callers
receive bound predicates while the finite recommendation bridge uses the row
matcher; both deliberately apply the same normalization rules.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from data.serving_moderation import ServingVisibility, build_serving_visibility_sql


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


def _json_array_or_empty(expression: str) -> str:
    """Return SQL that exposes only valid JSON arrays to ``json_each``."""
    # ``json_type`` raises on malformed JSON, so keep it behind a nested CASE
    # whose outer branch is evaluated only after ``json_valid`` succeeds.
    return (
        f"CASE WHEN json_valid({expression}) THEN "
        f"CASE WHEN json_type({expression}) = 'array' THEN {expression} ELSE '[]' END "
        "ELSE '[]' END"
    )


def build_video_filter_sql(alias: str, filters: VideoFilters) -> tuple[str, list[object]]:
    """Build AND-composed SQLite predicates for canonical ``videos`` rows.

    ``alias`` is supplied only by trusted query code.  Values always travel as
    bound parameters, including JSON tag membership, so public input never
    becomes SQL syntax.
    """
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
        # json_valid guards dirty crawler metadata.  json_each then receives an
        # empty array rather than malformed JSON, and only textual exact members
        # participate in the filter contract.
        clauses.append(
            f"""
            EXISTS (
              SELECT 1
              FROM json_each({_json_array_or_empty(f'{alias}.tags_json')}) AS tag_item
              WHERE tag_item.type = 'text'
                AND lower(trim(CAST(tag_item.value AS TEXT))) = ?
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


def fetch_video_facets(
    conn: Any,
    *,
    visibility: ServingVisibility | None = None,
    tag_limit: int = 100,
    instance_limit: int = 100,
) -> dict[str, Any]:
    """Aggregate global facets over the service-visible canonical video corpus.

    The data layer owns SQL rendering so API services pass the same policy
    object used by browse/search providers rather than leaking SQL fragments
    across the service/data boundary.
    """
    visibility = visibility or ServingVisibility()
    base, visibility_args = build_serving_visibility_sql("v", visibility)

    language_rows = conn.execute(
        f"""
        SELECT
          CASE WHEN v.language IS NULL OR trim(v.language) = '' THEN ? ELSE lower(trim(v.language)) END AS value,
          CASE
            WHEN v.language IS NULL OR trim(v.language) = '' THEN 'Unknown'
            ELSE COALESCE(NULLIF(trim(MIN(v.language_label)), ''), lower(trim(v.language)))
          END AS label,
          COUNT(*) AS count
        FROM videos v
        WHERE {base}
        GROUP BY value
        ORDER BY count DESC, value ASC
        """,
        [UNKNOWN_LANGUAGE, *visibility_args],
    ).fetchall()

    category_rows = conn.execute(
        f"""
        WITH grouped AS (
          SELECT
            lower(trim(v.category)) AS normalized_value,
            MIN(trim(v.category)) AS value,
            COUNT(*) AS count,
            COUNT(DISTINCT CASE WHEN v.category_id IS NOT NULL AND trim(v.category_id) <> '' THEN trim(v.category_id) END) AS id_count,
            MIN(CASE WHEN v.category_id IS NOT NULL AND trim(v.category_id) <> '' THEN trim(v.category_id) END) AS only_id
          FROM videos v
          WHERE {base}
            AND v.category IS NOT NULL AND trim(v.category) <> ''
          GROUP BY lower(trim(v.category))
        )
        SELECT value, CASE WHEN id_count = 1 THEN only_id ELSE NULL END AS category_id, count
        FROM grouped
        ORDER BY count DESC, lower(value) ASC
        """,
        visibility_args,
    ).fetchall()

    tag_rows = conn.execute(
        f"""
        WITH membership AS (
          SELECT DISTINCT
            v.video_id,
            v.instance_domain,
            lower(trim(CAST(j.value AS TEXT))) AS value
          FROM videos v
          JOIN json_each({_json_array_or_empty('v.tags_json')}) AS j
          WHERE {base}
            AND j.type = 'text'
            AND trim(CAST(j.value AS TEXT)) <> ''
        )
        SELECT value, COUNT(*) AS count
        FROM membership
        GROUP BY value
        ORDER BY count DESC, value ASC
        LIMIT ?
        """,
        [*visibility_args, max(1, int(tag_limit))],
    ).fetchall()

    instance_rows = conn.execute(
        f"""
        SELECT lower(trim(v.instance_domain)) AS value, COUNT(*) AS count
        FROM videos v
        WHERE {base}
          AND trim(v.instance_domain) <> ''
        GROUP BY lower(trim(v.instance_domain))
        ORDER BY count DESC, value ASC
        LIMIT ?
        """,
        [*visibility_args, max(1, int(instance_limit))],
    ).fetchall()

    total = sum(int(row["count"]) for row in language_rows)
    unknown = sum(int(row["count"]) for row in language_rows if row["value"] == UNKNOWN_LANGUAGE)
    known = total - unknown
    return {
        "languages": [dict(row) for row in language_rows],
        "categories": [dict(row) for row in category_rows],
        "tags": [dict(row) for row in tag_rows],
        "instances": [dict(row) for row in instance_rows],
        "coverage": {
            "language": {
                "known": known,
                "unknown": unknown,
                "total": total,
                "ratio": (known / total) if total else 0.0,
            }
        },
        "meta": {"dynamic": False, "tag_limit": tag_limit, "instance_limit": instance_limit},
    }
