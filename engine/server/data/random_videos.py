"""SQLite row providers for random, fresh, and popular video feeds.

Legacy recommendation fallback helpers remain available, while cursor-paged
Discovery uses explicit provider queries whose filtering and serving eligibility
happen before ``LIMIT``.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Sequence

from data.metadata import fetch_metadata_by_index_ids
from data.random_cache import fetch_random_index_ids
from data.serving_moderation import ServingVisibility, build_serving_visibility_sql
from data.video_filters import VideoFilters, build_video_filter_sql
from data.video_thumbnails import apply_thumbnail_api_fields

# Fresh/Trending read canonical videos directly; legacy embedding-backed helpers
# retain the embedding columns in their projection where they still need them.
_VIDEO_BASE_SELECT = """
  v.video_id,
  v.video_uuid,
  v.video_numeric_id,
  v.instance_domain,
  v.channel_id,
  v.channel_name,
  v.channel_url,
  c.display_name AS channel_display_name,
  c.avatar_url AS channel_avatar_url,
  v.account_name,
  v.account_url,
  v.title,
  v.description,
  v.tags_json,
  v.category,
  v.category_id,
  v.language,
  v.language_label,
  v.published_at,
  v.video_url,
  v.duration,
  v.thumbnail_url,
  v.thumbnail_candidates_json,
  v.embed_path,
  v.views,
  v.likes,
  v.dislikes,
  v.comments_count,
  v.nsfw,
  v.preview_path,
  v.popularity,
  v.last_checked_at
"""

_VIDEO_SELECT = _VIDEO_BASE_SELECT + ",\n  e.embedding_dim,\n  e.model_name"

_ROW_FIELDS = (
    "video_id",
    "video_uuid",
    "video_numeric_id",
    "instance_domain",
    "channel_id",
    "channel_name",
    "channel_url",
    "channel_display_name",
    "channel_avatar_url",
    "account_name",
    "account_url",
    "title",
    "description",
    "tags_json",
    "category",
    "category_id",
    "language",
    "language_label",
    "published_at",
    "video_url",
    "duration",
    "thumbnail_url",
    "thumbnail_candidates_json",
    "embed_path",
    "views",
    "likes",
    "dislikes",
    "comments_count",
    "nsfw",
    "preview_path",
    "popularity",
    "last_checked_at",
    "embedding_dim",
    "model_name",
)

FRESH_ORDER = (
    ("published_is_null", "ASC"),
    ("published_sort", "DESC"),
    ("instance_domain", "ASC"),
    ("video_id", "ASC"),
)
POPULAR_ORDER = (
    ("popularity", "DESC"),
    ("instance_domain", "ASC"),
    ("video_id", "ASC"),
)


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Project one SQLite row and publish the shared Engine thumbnail contract."""
    projected = {field: row[field] for field in _ROW_FIELDS if field in row.keys()}
    return apply_thumbnail_api_fields(projected)


def _build_seek_predicate(
    order: Sequence[tuple[str, str]], after: dict[str, Any] | None
) -> tuple[str, list[object]]:
    """Build a lexicographic seek predicate from one declared mixed-direction order."""
    if after is None:
        return "", []
    alternatives: list[str] = []
    params: list[object] = []
    for index, (field, direction) in enumerate(order):
        if field not in after or after[field] is None:
            raise ValueError("Invalid provider cursor")
        terms: list[str] = []
        local: list[object] = []
        for previous, _ in order[:index]:
            terms.append(f"{previous} = ?")
            local.append(after[previous])
        operator = ">" if direction == "ASC" else "<"
        terms.append(f"{field} {operator} ?")
        local.append(after[field])
        alternatives.append("(" + " AND ".join(terms) + ")")
        params.extend(local)
    return " AND (" + " OR ".join(alternatives) + ")", params


def _order_sql(order: Sequence[tuple[str, str]]) -> str:
    """Render the exact SQL ORDER BY owned by the same cursor key declaration."""
    return ", ".join(f"{field} {direction}" for field, direction in order)


def _cursor_values(row: sqlite3.Row, order: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """Extract the already-projected non-null sort keys for cursor serialization."""
    return {field: row[field] for field, _ in order}


def fetch_fresh_page(
    conn: sqlite3.Connection,
    *,
    limit_plus_one: int,
    filters: VideoFilters,
    visibility: ServingVisibility,
    after: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return one ordered Fresh provider window after filtering and visibility."""
    filter_sql, filter_params = build_video_filter_sql("v", filters)
    visibility_sql, visibility_params = build_serving_visibility_sql("v", visibility)
    seek_sql, seek_params = _build_seek_predicate(FRESH_ORDER, after)
    rows = conn.execute(
        f"""
        WITH eligible AS (
          SELECT
            {_VIDEO_BASE_SELECT},
            CASE WHEN v.published_at IS NULL THEN 1 ELSE 0 END AS published_is_null,
            COALESCE(v.published_at, 0) AS published_sort
          FROM videos v
          LEFT JOIN channels c
            ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
          WHERE {visibility_sql}
            {filter_sql}
        )
        SELECT *
        FROM eligible
        WHERE 1=1 {seek_sql}
        ORDER BY {_order_sql(FRESH_ORDER)}
        LIMIT ?
        """,
        [*visibility_params, *filter_params, *seek_params, max(limit_plus_one, 1)],
    ).fetchall()
    return [
        {**_row_dict(row), "_cursor": _cursor_values(row, FRESH_ORDER)}
        for row in rows
    ]


def fetch_popular_page(
    conn: sqlite3.Connection,
    *,
    limit_plus_one: int,
    filters: VideoFilters,
    visibility: ServingVisibility,
    after: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return one Trending window ordered only by persisted canonical popularity."""
    filter_sql, filter_params = build_video_filter_sql("v", filters)
    visibility_sql, visibility_params = build_serving_visibility_sql("v", visibility)
    seek_sql, seek_params = _build_seek_predicate(POPULAR_ORDER, after)
    rows = conn.execute(
        f"""
        WITH eligible AS (
          SELECT
            {_VIDEO_BASE_SELECT}
          FROM videos v
          LEFT JOIN channels c
            ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
          WHERE {visibility_sql}
            {filter_sql}
        )
        SELECT *
        FROM eligible
        WHERE 1=1 {seek_sql}
        ORDER BY {_order_sql(POPULAR_ORDER)}
        LIMIT ?
        """,
        [*visibility_params, *filter_params, *seek_params, max(limit_plus_one, 1)],
    ).fetchall()
    return [
        {**_row_dict(row), "_cursor": _cursor_values(row, POPULAR_ORDER)}
        for row in rows
    ]


def fetch_random_provider_range(
    conn: sqlite3.Connection,
    *,
    start_position: int,
    end_position_exclusive: int | None,
    limit: int,
    filters: VideoFilters,
    visibility: ServingVisibility,
) -> list[dict[str, Any]]:
    """Read one visible Random order range through the read-only attached canonical DB."""
    if limit <= 0:
        return []
    filter_sql, filter_params = build_video_filter_sql("v", filters, schema="canonical")
    visibility_sql, visibility_params = build_serving_visibility_sql(
        "v", visibility, schema="canonical"
    )
    range_sql = "r.position >= ?"
    range_params: list[object] = [start_position]
    if end_position_exclusive is not None:
        range_sql += " AND r.position < ?"
        range_params.append(end_position_exclusive)
    rows = conn.execute(
        f"""
        SELECT
          r.position,
          {_VIDEO_SELECT}
        FROM main.random_index_ids AS r
        JOIN canonical.video_index_ids AS vii
          ON vii.index_id = r.index_id AND vii.is_active = 1
        JOIN canonical.video_embeddings AS e
          ON e.video_id = vii.video_id AND e.instance_domain = vii.instance_domain
        JOIN canonical.videos AS v
          ON v.video_id = vii.video_id AND v.instance_domain = vii.instance_domain
        LEFT JOIN canonical.channels AS c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        WHERE {range_sql}
          AND {visibility_sql}
          {filter_sql}
        ORDER BY r.position ASC
        LIMIT ?
        """,
        [*range_params, *visibility_params, *filter_params, limit],
    ).fetchall()
    return [{**_row_dict(row), "_position": int(row["position"])} for row in rows]


def fetch_random_rows(
    conn: sqlite3.Connection, limit: int, error_threshold: int | None = None
) -> list[dict[str, Any]]:
    """Return random video rows for the legacy recommendation fallback."""
    error_clause = ""
    params: list[Any] = [limit]
    if error_threshold is not None and error_threshold > 0:
        error_clause = "WHERE (v.error_count IS NULL OR v.error_count < ?)"
        params = [error_threshold, limit]
    query = conn.execute(
        f"""
        SELECT {_VIDEO_SELECT}
        FROM video_embeddings e
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        {error_clause}
        ORDER BY RANDOM()
        LIMIT ?
        """,
        params,
    )
    return [_row_dict(row) for row in query]


def fetch_recent_videos(
    conn: sqlite3.Connection, limit: int, error_threshold: int | None = None
) -> list[dict[str, Any]]:
    """Return most recently published videos for legacy recommendation sources."""
    error_clause = ""
    params: list[Any] = [limit]
    if error_threshold is not None and error_threshold > 0:
        error_clause = "WHERE (v.error_count IS NULL OR v.error_count < ?)"
        params = [error_threshold, limit]
    rows = conn.execute(
        f"""
        SELECT {_VIDEO_SELECT}
        FROM video_embeddings e
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        {error_clause}
        ORDER BY v.published_at DESC, v.video_id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_row_dict(row) for row in rows]


def fetch_popular_videos(
    conn: sqlite3.Connection, limit: int, error_threshold: int | None = None
) -> list[dict[str, Any]]:
    """Return most popular legacy candidates while preserving the historical top-N cut."""
    error_clause = ""
    params: list[Any] = [limit, limit]
    if error_threshold is not None and error_threshold > 0:
        error_clause = "WHERE (v.error_count IS NULL OR v.error_count < ?)"
        params = [error_threshold, limit, limit]
    rows = conn.execute(
        f"""
        SELECT {_VIDEO_SELECT}
        FROM (
          SELECT v.video_id, v.instance_domain
          FROM videos v
          {error_clause}
          ORDER BY
            v.popularity DESC,
            v.likes DESC,
            v.views DESC,
            v.published_at DESC,
            v.video_id DESC
          LIMIT ?
        ) AS popular_ids
        JOIN video_embeddings e
          ON e.video_id = popular_ids.video_id AND e.instance_domain = popular_ids.instance_domain
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        -- Preserve the legacy fallback contract: embedding eligibility may
        -- underfill the canonical top-N window instead of backfilling it.
        ORDER BY
          v.popularity DESC,
          v.likes DESC,
          v.views DESC,
          v.published_at DESC,
          v.video_id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_row_dict(row) for row in rows]


def fetch_random_rows_from_cache(
    server: Any, limit: int, error_threshold: int | None = None
) -> list[dict[str, Any]]:
    """Return finite random recommendation fallback rows from the persisted cache."""
    if server.random_cache_db is None or limit <= 0:
        return []
    with server.random_cache_lock:
        index_ids = fetch_random_index_ids(server.random_cache_db, limit)
    if not index_ids:
        return []
    with server.db_lock:
        metadata = fetch_metadata_by_index_ids(server.db, index_ids, error_threshold=error_threshold)
    rows: list[dict[str, Any]] = []
    for index_id in index_ids:
        meta = metadata.get(index_id)
        if meta:
            rows.append(meta)
    return rows
