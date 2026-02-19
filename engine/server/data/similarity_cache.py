"""Provide similarity cache runtime helpers."""

from __future__ import annotations

import sqlite3
from typing import Any


SIMILARITY_ITEM_COLUMNS = [
    "source_video_id",
    "source_instance_domain",
    "similar_video_id",
    "similar_instance_domain",
    "score",
    "rank",
]


def ensure_similarity_schema(conn: sqlite3.Connection) -> None:
    """Create similarity cache tables if missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS similarity_sources (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          computed_at INTEGER NOT NULL,
          PRIMARY KEY (video_id, instance_domain)
        );
        CREATE TABLE IF NOT EXISTS similarity_items (
          source_video_id TEXT NOT NULL,
          source_instance_domain TEXT NOT NULL,
          similar_video_id TEXT NOT NULL,
          similar_instance_domain TEXT NOT NULL,
          score REAL,
          rank INTEGER NOT NULL,
          PRIMARY KEY (
            source_video_id,
            source_instance_domain,
            similar_video_id,
            similar_instance_domain
          )
        );
        CREATE INDEX IF NOT EXISTS similarity_source_rank_idx
          ON similarity_items (source_video_id, source_instance_domain, rank);
        """
    )


def fetch_cached_similarities(
    conn: sqlite3.Connection | None, source: dict[str, Any], limit: int
) -> list[dict[str, Any]]:
    """Fetch cached similar items for a source video."""
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT similar_video_id, similar_instance_domain, score, rank
            FROM similarity_items
            WHERE source_video_id = ? AND source_instance_domain = ?
            ORDER BY rank ASC
            LIMIT ?
            """,
            (source.get("video_id"), source.get("instance_domain") or "", limit),
        ).fetchall()
        return [
            {
                "video_id": row["similar_video_id"],
                "instance_domain": row["similar_instance_domain"],
                "score": row["score"],
                "rank": row["rank"],
            }
            for row in rows
        ]
    except sqlite3.Error:
        return []


def has_cached_similarities(conn: sqlite3.Connection, source: dict[str, Any]) -> bool:
    """Return True if the source video already has cached similars."""
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM similarity_items
            WHERE source_video_id = ? AND source_instance_domain = ?
            LIMIT 1
            """,
            (source.get("video_id"), source.get("instance_domain") or ""),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def store_similarity_cache(
    conn: sqlite3.Connection,
    source: dict[str, Any],
    items: list[dict[str, Any]],
    computed_at: int,
) -> None:
    """Persist similar items for a source video."""
    conn.execute(
        """
        INSERT INTO similarity_sources (video_id, instance_domain, computed_at)
        VALUES (?, ?, ?)
        ON CONFLICT(video_id, instance_domain)
        DO UPDATE SET computed_at = excluded.computed_at
        """,
        (source.get("video_id"), source.get("instance_domain") or "", computed_at),
    )
    conn.execute(
        """
        DELETE FROM similarity_items
        WHERE source_video_id = ? AND source_instance_domain = ?
        """,
        (source.get("video_id"), source.get("instance_domain") or ""),
    )
    values = [
        (
            source.get("video_id"),
            source.get("instance_domain") or "",
            item.get("video_id"),
            item.get("instance_domain") or "",
            item.get("score"),
            item.get("rank"),
        )
        for item in items
    ]
    placeholders = ", ".join(["?"] * len(SIMILARITY_ITEM_COLUMNS))
    conn.executemany(
        f"""
        INSERT INTO similarity_items (
          {", ".join(SIMILARITY_ITEM_COLUMNS)}
        )
        VALUES ({placeholders})
        """,
        values,
    )
    conn.commit()
