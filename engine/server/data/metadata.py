"""Provide metadata runtime helpers."""

from __future__ import annotations

import sqlite3
from typing import Any

from recommendations.keys import like_key


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
              v.published_at,
              v.video_url,
              v.duration,
              v.thumbnail_url,
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
            result[int(row["rowid"])] = {
                "video_id": row["video_id"],
                "video_uuid": row["video_uuid"],
                "video_numeric_id": row["video_numeric_id"],
                "instance_domain": row["instance_domain"],
                "channel_id": row["channel_id"],
                "channel_name": row["channel_name"],
                "channel_url": row["channel_url"],
                "channel_display_name": row["channel_display_name"],
                "channel_avatar_url": row["channel_avatar_url"],
                "account_name": row["account_name"],
                "account_url": row["account_url"],
                "title": row["title"],
                "description": row["description"],
                "tags_json": row["tags_json"],
                "category": row["category"],
                "published_at": row["published_at"],
                "video_url": row["video_url"],
                "duration": row["duration"],
                "thumbnail_url": row["thumbnail_url"],
                "embed_path": row["embed_path"],
                "views": row["views"],
                "likes": row["likes"],
                "dislikes": row["dislikes"],
                "comments_count": row["comments_count"],
                "nsfw": row["nsfw"],
                "preview_path": row["preview_path"],
                "last_checked_at": row["last_checked_at"],
                "embedding_dim": row["embedding_dim"],
                "model_name": row["model_name"],
            }
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
              v.published_at,
              v.video_url,
              v.duration,
              v.thumbnail_url,
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
            result[like_key(row)] = {
                "video_id": row["video_id"],
                "video_uuid": row["video_uuid"],
                "video_numeric_id": row["video_numeric_id"],
                "instance_domain": row["instance_domain"],
                "channel_id": row["channel_id"],
                "channel_name": row["channel_name"],
                "channel_url": row["channel_url"],
                "channel_display_name": row["channel_display_name"],
                "channel_avatar_url": row["channel_avatar_url"],
                "account_name": row["account_name"],
                "account_url": row["account_url"],
                "title": row["title"],
                "description": row["description"],
                "tags_json": row["tags_json"],
                "category": row["category"],
                "published_at": row["published_at"],
                "video_url": row["video_url"],
                "duration": row["duration"],
                "thumbnail_url": row["thumbnail_url"],
                "embed_path": row["embed_path"],
                "views": row["views"],
                "likes": row["likes"],
                "dislikes": row["dislikes"],
                "comments_count": row["comments_count"],
                "nsfw": row["nsfw"],
                "preview_path": row["preview_path"],
                "last_checked_at": row["last_checked_at"],
                "embedding_dim": row["embedding_dim"],
                "model_name": row["model_name"],
            }
    return result
