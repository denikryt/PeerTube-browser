from __future__ import annotations

import sqlite3
from typing import Any

from data.time import now_ms


def ensure_user_schema(conn: sqlite3.Connection) -> None:
    """Create users/likes tables if missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          user_id TEXT PRIMARY KEY,
          username TEXT,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS likes (
          user_id TEXT NOT NULL,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          video_uuid TEXT,
          updated_at INTEGER NOT NULL,
          PRIMARY KEY (user_id, video_id, instance_domain)
        );
        CREATE INDEX IF NOT EXISTS likes_user_updated_idx
          ON likes (user_id, updated_at DESC);
        """
    )


def get_or_create_user(conn: sqlite3.Connection, user_id: str) -> None:
    """Insert a user row if it does not exist."""
    now = now_ms()
    row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        return
    conn.execute(
        "INSERT INTO users (user_id, username, created_at) VALUES (?, ?, ?)",
        (user_id, user_id, now),
    )
    conn.commit()


def record_like(
    conn: sqlite3.Connection,
    user_id: str,
    action: str,
    video: dict[str, Any],
    max_likes: int,
) -> None:
    """Record a like with recency tracking."""
    if action != "like":
        raise ValueError("Unsupported action")
    get_or_create_user(conn, user_id)
    video_id = str(video.get("video_id") or "")
    instance_domain = str(video.get("instance_domain") or "")
    video_uuid = video.get("video_uuid")
    now = now_ms()
    conn.execute(
        """
        INSERT INTO likes (user_id, video_id, instance_domain, video_uuid, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, video_id, instance_domain)
        DO UPDATE SET video_uuid = excluded.video_uuid, updated_at = excluded.updated_at
        """,
        (user_id, video_id, instance_domain, video_uuid, now),
    )
    if max_likes > 0:
        conn.execute(
            """
            DELETE FROM likes
            WHERE user_id = ?
            AND rowid NOT IN (
              SELECT rowid FROM likes
              WHERE user_id = ?
              ORDER BY updated_at DESC
              LIMIT ?
            )
            """,
            (user_id, user_id, max_likes),
        )
    conn.commit()


def fetch_recent_likes(
    conn: sqlite3.Connection, user_id: str, limit: int
) -> list[dict[str, Any]]:
    """Return recent likes for a user, newest first."""
    if limit <= 0:
        limit = -1
    rows = conn.execute(
        """
        SELECT video_id, video_uuid, instance_domain, updated_at
        FROM likes
        WHERE user_id = ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [
        {
            "video_id": row["video_id"],
            "video_uuid": row["video_uuid"],
            "instance_domain": row["instance_domain"] or None,
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def clear_likes(conn: sqlite3.Connection, user_id: str) -> None:
    """Remove all likes for a user."""
    conn.execute("DELETE FROM likes WHERE user_id = ?", (user_id,))
    conn.commit()
