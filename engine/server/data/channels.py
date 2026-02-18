"""Provide channels runtime helpers."""

from __future__ import annotations

import sqlite3
from typing import Any


SORT_EXPRESSIONS = {
    "name": "LOWER(COALESCE(channel_name, ''))",
    "instance": "LOWER(COALESCE(instance_domain, ''))",
    "videos": "COALESCE(videos_count, 0)",
    "followers": "COALESCE(followers_count, 0)",
    "checked": "COALESCE(health_checked_at, 0)",
}
DEFAULT_SORT = "followers"
DEFAULT_SORT_DIR = "desc"
ALLOWED_SORT_DIRS = {"asc", "desc"}


def ensure_channels_indexes(conn: sqlite3.Connection) -> None:
    """Create indexes used by /api/channels filtering and ordering."""
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'channels' LIMIT 1"
    ).fetchone()
    if not table_exists:
        return
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_channels_followers_videos_name
          ON channels (followers_count DESC, videos_count DESC, channel_name ASC);
        CREATE INDEX IF NOT EXISTS idx_channels_videos
          ON channels (videos_count DESC);
        CREATE INDEX IF NOT EXISTS idx_channels_name
          ON channels (channel_name);
        CREATE INDEX IF NOT EXISTS idx_channels_instance
          ON channels (instance_domain);
        """
    )


def fetch_channels(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    query: str = "",
    instance: str = "",
    min_followers: int = 0,
    min_videos: int = 0,
    max_videos: int | None = None,
    sort: str = DEFAULT_SORT,
    direction: str = DEFAULT_SORT_DIR,
) -> tuple[list[dict[str, Any]], int]:
    """Return filtered channel rows and full filtered count."""
    sort_expr = SORT_EXPRESSIONS.get(sort, SORT_EXPRESSIONS[DEFAULT_SORT])
    sort_dir = direction.lower() if direction else DEFAULT_SORT_DIR
    if sort_dir not in ALLOWED_SORT_DIRS:
        sort_dir = DEFAULT_SORT_DIR

    where: list[str] = []
    params: list[Any] = []

    term = query.strip().lower()
    if term:
        like = f"%{term}%"
        where.append(
            """
            (
              LOWER(COALESCE(display_name, channel_name, channel_id, '')) LIKE ?
              OR LOWER(COALESCE(instance_domain, '')) LIKE ?
            )
            """
        )
        params.extend([like, like])

    instance_term = instance.strip().lower()
    if instance_term:
        where.append("LOWER(COALESCE(instance_domain, '')) LIKE ?")
        params.append(f"%{instance_term}%")

    where.append("COALESCE(followers_count, 0) >= ?")
    params.append(max(min_followers, 0))
    where.append("COALESCE(videos_count, 0) >= ?")
    params.append(max(min_videos, 0))

    if max_videos is not None:
        where.append("COALESCE(videos_count, 0) <= ?")
        params.append(max(max_videos, 0))

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    total = int(conn.execute(f"SELECT COUNT(*) FROM channels {where_sql}", params).fetchone()[0])

    sql = """
        SELECT
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
        FROM channels
    """
    sql += f"""
        {where_sql}
        ORDER BY
          {sort_expr} {sort_dir.upper()},
          COALESCE(followers_count, 0) DESC,
          COALESCE(videos_count, 0) DESC,
          channel_name ASC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(sql, [*params, max(limit, 1), max(offset, 0)]).fetchall()
    return [
        {
            "channel_id": row["channel_id"],
            "channel_name": row["channel_name"],
            "display_name": row["display_name"],
            "instance_domain": row["instance_domain"],
            "videos_count": row["videos_count"],
            "followers_count": row["followers_count"],
            "avatar_url": row["avatar_url"],
            "health_status": row["health_status"],
            "health_checked_at": row["health_checked_at"],
            "health_error": row["health_error"],
            "channel_url": row["channel_url"],
            "last_error": row["last_error"],
            "last_error_at": row["last_error_at"],
            "last_error_source": row["last_error_source"],
        }
        for row in rows
    ], total
