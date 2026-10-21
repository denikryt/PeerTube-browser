"""Provide metadata runtime helpers."""

from __future__ import annotations

import sqlite3
from typing import Any

from recommendations.keys import like_key
from data.video_thumbnails import apply_thumbnail_api_fields


# These fetchers are three identity lookups over one canonical runtime row shape.
# Keep the projection single-sourced so new metadata cannot silently appear in only
# one ANN/random/similarity resolution path.
_METADATA_SELECT = """
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
  v.last_checked_at,
  e.embedding_dim,
  e.model_name
"""


def _metadata_row(row: sqlite3.Row, *, lookup_field: str | None = None) -> dict[str, Any]:
    """Return the canonical metadata payload, excluding an internal lookup key.

    Query-specific identity columns such as ``rowid`` and ``index_id`` are used
    only to key the returned mapping.  Every other selected column belongs to the
    shared canonical metadata row and is copied without coercion.
    """
    projected = {key: row[key] for key in row.keys() if key != lookup_field}
    return apply_thumbnail_api_fields(projected)


def fetch_metadata(
    conn: sqlite3.Connection,
    rowids: list[int],
    error_threshold: int | None = None,
) -> dict[int, dict[str, Any]]:
    """Fetch video metadata for embedding rowids."""
    if not rowids:
        return {}
    result: dict[int, dict[str, Any]] = {}
    for batch in _chunk(rowids, 900):
        placeholders = ",".join(["?"] * len(batch))
        error_clause = ""
        params: list[Any] = list(batch)
        if error_threshold is not None and error_threshold > 0:
            error_clause = "AND (v.error_count IS NULL OR v.error_count < ?)"
            params.append(error_threshold)
        query = conn.execute(
            f"""
            SELECT
              e.rowid AS rowid,
              {_METADATA_SELECT}
            FROM video_embeddings e
            JOIN videos v
              ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
            LEFT JOIN channels c
              ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
            WHERE e.rowid IN ({placeholders})
              {error_clause}
            """,
            params,
        )
        for row in query:
            result[int(row["rowid"])] = _metadata_row(row, lookup_field="rowid")
    return result


def fetch_metadata_by_index_ids(
    conn: sqlite3.Connection,
    index_ids: list[int],
    error_threshold: int | None = None,
) -> dict[int, dict[str, Any]]:
    """Fetch video metadata for stable `video_index_ids.index_id` values.

    ANN and random-cache artifacts store numeric index ids because FAISS and the
    cache table need compact integers. This helper is the only runtime bridge
    from those internal ids back to canonical video metadata.
    """
    if not index_ids:
        return {}
    result: dict[int, dict[str, Any]] = {}
    for batch in _chunk(index_ids, 900):
        placeholders = ",".join(["?"] * len(batch))
        error_clause = ""
        params: list[Any] = list(batch)
        if error_threshold is not None and error_threshold > 0:
            error_clause = "AND (v.error_count IS NULL OR v.error_count < ?)"
            params.append(error_threshold)
        rows = conn.execute(
            f"""
            SELECT
              vii.index_id,
              {_METADATA_SELECT}
            FROM video_index_ids vii
            JOIN video_embeddings e
              ON e.video_id = vii.video_id AND e.instance_domain = vii.instance_domain
            JOIN videos v
              ON v.video_id = vii.video_id AND v.instance_domain = vii.instance_domain
            LEFT JOIN channels c
              ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
            WHERE vii.index_id IN ({placeholders})
              AND vii.is_active = 1
              {error_clause}
            """,
            params,
        ).fetchall()
        for row in rows:
            result[int(row["index_id"])] = _metadata_row(row, lookup_field="index_id")
    return result


def _chunk(values: list[Any], size: int) -> list[list[Any]]:
    """Handle chunk."""
    return [values[index : index + size] for index in range(0, len(values), size)]


def fetch_metadata_by_ids(
    conn: sqlite3.Connection,
    entries: list[dict[str, Any]],
    error_threshold: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch video metadata for (video_id, instance_domain) pairs."""
    if not entries:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for batch in _chunk(entries, 450):
        conditions = " OR ".join(
            ["(v.video_id = ? AND v.instance_domain = ?)"] * len(batch)
        )
        params: list[Any] = []
        for entry in batch:
            params.append(entry.get("video_id"))
            params.append(entry.get("instance_domain") or "")
        error_clause = ""
        if error_threshold is not None and error_threshold > 0:
            error_clause = "AND (v.error_count IS NULL OR v.error_count < ?)"
            params.append(error_threshold)
        rows = conn.execute(
            f"""
            SELECT
              {_METADATA_SELECT}
            FROM video_embeddings e
            JOIN videos v
              ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
            LEFT JOIN channels c
              ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
            WHERE {conditions}
              {error_clause}
            """,
            params,
        ).fetchall()
        for row in rows:
            result[like_key(row)] = _metadata_row(row)
    return result
