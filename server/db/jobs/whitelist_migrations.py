from __future__ import annotations

import sqlite3


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?;",
        (table,),
    ).fetchone()
    return bool(row)


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def migrate_instances_schema(conn: sqlite3.Connection, table_name: str) -> None:
    if not _table_exists(conn, table_name):
        return
    columns = _columns(conn, table_name)
    deprecated = {
        "status",
        "invalid_reason",
        "invalid_at",
        "last_success_at",
        "consecutive_failures",
        "last_processed_at",
        "error_count",
    }
    needs_rebuild = (
        any(col in deprecated for col in columns)
        or "health_status" not in columns
        or "health_checked_at" not in columns
        or "health_error" not in columns
        or "last_error" not in columns
        or "last_error_at" not in columns
        or "last_error_source" not in columns
    )
    if not needs_rebuild:
        return
    has_status = "status" in columns
    has_health_status = "health_status" in columns
    has_health_checked_at = "health_checked_at" in columns
    has_health_error = "health_error" in columns
    has_invalid_reason = "invalid_reason" in columns
    has_invalid_at = "invalid_at" in columns
    has_last_error = "last_error" in columns
    has_last_error_at = "last_error_at" in columns
    has_last_error_source = "last_error_source" in columns
    health_status_expr = (
        "health_status"
        if has_health_status
        else "CASE status WHEN 'done' THEN 'ok' WHEN 'error' THEN 'error' ELSE 'unknown' END"
        if has_status
        else "NULL"
    )
    health_checked_at_expr = (
        "health_checked_at"
        if has_health_checked_at
        else "invalid_at"
        if has_invalid_at
        else "NULL"
    )
    health_error_expr = (
        "health_error"
        if has_health_error
        else "invalid_reason"
        if has_invalid_reason
        else "NULL"
    )
    last_error_expr = "last_error" if has_last_error else "NULL"
    last_error_at_expr = "last_error_at" if has_last_error_at else "NULL"
    last_error_source_expr = "last_error_source" if has_last_error_source else "NULL"
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name}_new (
          host TEXT PRIMARY KEY,
          health_status TEXT,
          health_checked_at INTEGER,
          health_error TEXT,
          last_error TEXT,
          last_error_at INTEGER,
          last_error_source TEXT
        );
        INSERT INTO {table_name}_new (
          host,
          health_status,
          health_checked_at,
          health_error,
          last_error,
          last_error_at,
          last_error_source
        )
        SELECT
          host,
          {health_status_expr},
          {health_checked_at_expr},
          {health_error_expr},
          {last_error_expr},
          {last_error_at_expr},
          {last_error_source_expr}
        FROM {table_name};
        DROP TABLE {table_name};
        ALTER TABLE {table_name}_new RENAME TO {table_name};
        """
    )


def migrate_channels_schema(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "channels"):
        return
    columns = _columns(conn, "channels")
    deprecated = {"last_checked_at", "videos_count_error", "videos_count_error_at"}
    needs_rebuild = (
        any(col in deprecated for col in columns)
        or "health_status" not in columns
        or "health_checked_at" not in columns
        or "health_error" not in columns
        or "last_error" not in columns
        or "last_error_at" not in columns
        or "last_error_source" not in columns
    )
    if not needs_rebuild:
        return
    has_health_status = "health_status" in columns
    has_health_checked_at = "health_checked_at" in columns
    has_health_error = "health_error" in columns
    has_last_error = "last_error" in columns
    has_last_error_at = "last_error_at" in columns
    has_last_error_source = "last_error_source" in columns
    has_last_checked_at = "last_checked_at" in columns
    has_videos_count_error = "videos_count_error" in columns
    has_videos_count_error_at = "videos_count_error_at" in columns
    health_status_expr = "health_status" if has_health_status else "NULL"
    health_checked_at_expr = (
        "health_checked_at"
        if has_health_checked_at
        else "last_checked_at"
        if has_last_checked_at
        else "NULL"
    )
    health_error_expr = "health_error" if has_health_error else "NULL"
    last_error_expr = (
        "last_error"
        if has_last_error
        else "videos_count_error"
        if has_videos_count_error
        else "NULL"
    )
    last_error_at_expr = (
        "last_error_at"
        if has_last_error_at
        else "videos_count_error_at"
        if has_videos_count_error_at
        else "NULL"
    )
    last_error_source_expr = (
        "last_error_source"
        if has_last_error_source
        else "CASE WHEN videos_count_error IS NOT NULL THEN 'videos_count' END"
        if has_videos_count_error
        else "NULL"
    )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS channels_new (
          channel_id TEXT NOT NULL,
          channel_name TEXT,
          display_name TEXT,
          instance_domain TEXT NOT NULL,
          videos_count INTEGER,
          followers_count INTEGER,
          avatar_url TEXT,
          health_status TEXT,
          health_checked_at INTEGER,
          health_error TEXT,
          channel_url TEXT,
          last_error TEXT,
          last_error_at INTEGER,
          last_error_source TEXT,
          PRIMARY KEY (channel_id, instance_domain)
        );
        """
    )
    conn.executescript(
        f"""
        INSERT INTO channels_new (
          channel_id,
          channel_name,
          display_name,
          instance_domain,
          videos_count,
          followers_count,
          avatar_url,
          health_status,
          health_checked_at,
          health_error,
          channel_url,
          last_error,
          last_error_at,
          last_error_source
        )
        SELECT
          channel_id,
          channel_name,
          display_name,
          instance_domain,
          videos_count,
          followers_count,
          avatar_url,
          {health_status_expr},
          {health_checked_at_expr},
          {health_error_expr},
          channel_url,
          {last_error_expr},
          {last_error_at_expr},
          {last_error_source_expr}
        FROM channels;
        DROP TABLE channels;
        ALTER TABLE channels_new RENAME TO channels;
        """
    )


def migrate_videos_schema(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "videos"):
        return
    columns = _columns(conn, "videos")
    needs_rebuild = (
        "last_error" not in columns
        or "last_error_at" not in columns
        or "error_count" not in columns
    )
    if not needs_rebuild:
        return
    has_last_error = "last_error" in columns
    has_last_error_at = "last_error_at" in columns
    has_error_count = "error_count" in columns
    has_invalid_reason = "invalid_reason" in columns
    has_invalid_at = "invalid_at" in columns
    last_error_expr = "last_error" if has_last_error else "NULL"
    last_error_at_expr = "last_error_at" if has_last_error_at else "NULL"
    error_count_expr = "error_count" if has_error_count else "0"
    invalid_reason_expr = "invalid_reason" if has_invalid_reason else "NULL"
    invalid_at_expr = "invalid_at" if has_invalid_at else "NULL"
    conn.executescript(
        f"""
        DROP TABLE IF EXISTS video_embeddings;
        CREATE TABLE IF NOT EXISTS videos_new (
          video_id TEXT NOT NULL,
          video_uuid TEXT,
          video_numeric_id INTEGER,
          instance_domain TEXT NOT NULL,
          channel_id TEXT,
          channel_name TEXT,
          channel_url TEXT,
          account_name TEXT,
          account_url TEXT,
          title TEXT,
          description TEXT,
          tags_json TEXT,
          category TEXT,
          published_at INTEGER,
          video_url TEXT,
          duration INTEGER,
          thumbnail_url TEXT,
          embed_path TEXT,
          views INTEGER,
          likes INTEGER,
          dislikes INTEGER,
          comments_count INTEGER,
          nsfw INTEGER,
          preview_path TEXT,
          popularity REAL NOT NULL DEFAULT 0,
          last_checked_at INTEGER NOT NULL,
          last_error TEXT,
          last_error_at INTEGER,
          error_count INTEGER NOT NULL DEFAULT 0,
          invalid_reason TEXT,
          invalid_at INTEGER,
          PRIMARY KEY (video_id, instance_domain)
        );
        INSERT INTO videos_new (
          video_id,
          video_uuid,
          video_numeric_id,
          instance_domain,
          channel_id,
          channel_name,
          channel_url,
          account_name,
          account_url,
          title,
          description,
          tags_json,
          category,
          published_at,
          video_url,
          duration,
          thumbnail_url,
          embed_path,
          views,
          likes,
          dislikes,
          comments_count,
          nsfw,
          preview_path,
          popularity,
          last_checked_at,
          last_error,
          last_error_at,
          error_count,
          invalid_reason,
          invalid_at
        )
        SELECT
          video_id,
          video_uuid,
          video_numeric_id,
          instance_domain,
          channel_id,
          channel_name,
          channel_url,
          account_name,
          account_url,
          title,
          description,
          tags_json,
          category,
          published_at,
          video_url,
          duration,
          thumbnail_url,
          embed_path,
          views,
          likes,
          dislikes,
          comments_count,
          nsfw,
          preview_path,
          COALESCE(popularity, 0),
          last_checked_at,
          {last_error_expr},
          {last_error_at_expr},
          {error_count_expr},
          {invalid_reason_expr},
          {invalid_at_expr}
        FROM videos;
        DROP TABLE videos;
        ALTER TABLE videos_new RENAME TO videos;
        """
    )


def migrate_whitelist_schema(conn: sqlite3.Connection, table_name: str) -> None:
    migrate_instances_schema(conn, table_name)
    migrate_channels_schema(conn)
    migrate_videos_schema(conn)
