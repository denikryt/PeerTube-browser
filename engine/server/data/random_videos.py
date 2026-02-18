"""Provide random videos runtime helpers."""

from __future__ import annotations

import sqlite3
from typing import Any

from data.metadata import fetch_metadata
from data.random_cache import fetch_random_rowids


def fetch_random_rows(
    conn: sqlite3.Connection, limit: int, error_threshold: int | None = None
) -> list[dict[str, Any]]:
    """Return random video rows for fallback."""
    error_clause = ""
    params: list[Any] = [limit]
    if error_threshold is not None and error_threshold > 0:
        error_clause = "WHERE (v.error_count IS NULL OR v.error_count < ?)"
        params = [error_threshold, limit]
    query = conn.execute(
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
          (v.likes + COALESCE(sig.likes_count, 0) - COALESCE(sig.undo_likes_count, 0)) AS likes,
          v.dislikes,
          v.comments_count,
          v.nsfw,
          v.preview_path,
          v.popularity,
          v.last_checked_at,
          e.embedding_dim,
          e.model_name
        FROM video_embeddings e
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        LEFT JOIN interaction_signals sig
          ON sig.video_uuid = v.video_uuid AND sig.instance_domain = v.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        {error_clause}
        ORDER BY RANDOM()
        LIMIT ?
        """,
        params,
    )
    rows = []
    for row in query:
        rows.append(
            {
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
        )
    return rows


def fetch_recent_videos(
    conn: sqlite3.Connection, limit: int, error_threshold: int | None = None
) -> list[dict[str, Any]]:
    """Return most recently published videos."""
    error_clause = ""
    params: list[Any] = [limit]
    if error_threshold is not None and error_threshold > 0:
        error_clause = "WHERE (v.error_count IS NULL OR v.error_count < ?)"
        params = [error_threshold, limit]
    query = conn.execute(
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
        {error_clause}
        ORDER BY v.published_at DESC, v.video_id DESC
        LIMIT ?
        """,
        params,
    )
    rows = []
    for row in query:
        rows.append(
            {
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
        )
    return rows


def fetch_popular_videos(
    conn: sqlite3.Connection, limit: int, error_threshold: int | None = None
) -> list[dict[str, Any]]:
    """Return most popular videos by likes/views."""
    error_clause = ""
    params: list[Any] = [limit, limit]
    if error_threshold is not None and error_threshold > 0:
        error_clause = "WHERE (v.error_count IS NULL OR v.error_count < ?)"
        params = [error_threshold, limit, limit]
    query = conn.execute(
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
          v.popularity,
          COALESCE(sig.signal_score, 0) AS interaction_signal_score,
          v.last_checked_at,
          e.embedding_dim,
          e.model_name
        FROM (
          SELECT
            v.video_id,
            v.instance_domain
          FROM videos v
          LEFT JOIN interaction_signals sig
            ON sig.video_uuid = v.video_uuid AND sig.instance_domain = v.instance_domain
          {error_clause}
          ORDER BY
            (v.popularity + COALESCE(sig.signal_score, 0)) DESC,
            (v.likes + COALESCE(sig.likes_count, 0) - COALESCE(sig.undo_likes_count, 0)) DESC,
            v.views DESC,
            v.published_at DESC,
            v.video_id DESC
          LIMIT ?
        ) AS popular_ids
        JOIN video_embeddings e
          ON e.video_id = popular_ids.video_id AND e.instance_domain = popular_ids.instance_domain
        JOIN videos v
          ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
        LEFT JOIN interaction_signals sig
          ON sig.video_uuid = v.video_uuid AND sig.instance_domain = v.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        LIMIT ?
        """,
        params,
    )
    rows = []
    for row in query:
        rows.append(
            {
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
                "popularity": row["popularity"],
                "interaction_signal_score": row["interaction_signal_score"],
                "last_checked_at": row["last_checked_at"],
                "embedding_dim": row["embedding_dim"],
                "model_name": row["model_name"],
            }
        )
    return rows


def fetch_random_rows_from_cache(
    server: Any, limit: int, error_threshold: int | None = None
) -> list[dict[str, Any]]:
    """Return random videos using the precomputed rowid cache."""
    if server.random_cache_db is None or limit <= 0:
        return []
    with server.random_cache_lock:
        rowids = fetch_random_rowids(server.random_cache_db, limit)
    if not rowids:
        return []
    with server.db_lock:
        metadata = fetch_metadata(server.db, rowids, error_threshold=error_threshold)
    rows: list[dict[str, Any]] = []
    for rowid in rowids:
        meta = metadata.get(rowid)
        if not meta:
            continue
        rows.append(meta)
    return rows
