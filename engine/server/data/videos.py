from __future__ import annotations

import sqlite3


def ensure_video_indexes(conn: sqlite3.Connection) -> None:
    """Create indexes to speed up seed lookups and embedding joins."""
    videos_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'videos' LIMIT 1"
    ).fetchone()
    embeddings_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'video_embeddings' LIMIT 1"
    ).fetchone()
    if not videos_exists and not embeddings_exists:
        return
    if videos_exists:
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_videos_uuid_instance
              ON videos (video_uuid, instance_domain);
            CREATE INDEX IF NOT EXISTS idx_videos_id_instance
              ON videos (video_id, instance_domain);
            """
        )
    if embeddings_exists:
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_video_embeddings_id_instance
              ON video_embeddings (video_id, instance_domain);
            """
        )
