from __future__ import annotations

import sqlite3
from typing import Any


SIMILARITY_ITEM_METADATA_COLUMNS = [
    ("similar_video_uuid", "TEXT"),
    ("similar_video_numeric_id", "INTEGER"),
    ("similar_channel_id", "TEXT"),
    ("similar_channel_name", "TEXT"),
    ("similar_channel_url", "TEXT"),
    ("similar_channel_avatar_url", "TEXT"),
    ("similar_account_name", "TEXT"),
    ("similar_account_url", "TEXT"),
    ("similar_title", "TEXT"),
    ("similar_description", "TEXT"),
    ("similar_tags_json", "TEXT"),
    ("similar_category", "TEXT"),
    ("similar_published_at", "INTEGER"),
    ("similar_video_url", "TEXT"),
    ("similar_duration", "REAL"),
    ("similar_thumbnail_url", "TEXT"),
    ("similar_embed_path", "TEXT"),
    ("similar_views", "INTEGER"),
    ("similar_likes", "INTEGER"),
    ("similar_dislikes", "INTEGER"),
    ("similar_comments_count", "INTEGER"),
    ("similar_nsfw", "INTEGER"),
    ("similar_preview_path", "TEXT"),
    ("similar_last_checked_at", "INTEGER"),
]

SIMILARITY_ITEM_METADATA_FIELDS = [
    "video_uuid",
    "video_numeric_id",
    "channel_id",
    "channel_name",
    "channel_url",
    "channel_avatar_url",
    "account_name",
    "account_url",
    "title",
    "description",
    "tags_json",
    "category",
    "published_at",
    "video_url",
    "duration",
    "thumbnail_url",
    "embed_path",
    "views",
    "likes",
    "dislikes",
    "comments_count",
    "nsfw",
    "preview_path",
    "last_checked_at",
]

SIMILARITY_ITEM_COLUMNS = [
    "source_video_id",
    "source_instance_domain",
    "similar_video_id",
    "similar_instance_domain",
    "score",
    "rank",
    "similar_video_uuid",
    "similar_video_numeric_id",
    "similar_channel_id",
    "similar_channel_name",
    "similar_channel_url",
    "similar_channel_avatar_url",
    "similar_account_name",
    "similar_account_url",
    "similar_title",
    "similar_description",
    "similar_tags_json",
    "similar_category",
    "similar_published_at",
    "similar_video_url",
    "similar_duration",
    "similar_thumbnail_url",
    "similar_embed_path",
    "similar_views",
    "similar_likes",
    "similar_dislikes",
    "similar_comments_count",
    "similar_nsfw",
    "similar_preview_path",
    "similar_last_checked_at",
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
          similar_video_uuid TEXT,
          similar_video_numeric_id INTEGER,
          similar_channel_id TEXT,
          similar_channel_name TEXT,
          similar_channel_url TEXT,
          similar_channel_avatar_url TEXT,
          similar_account_name TEXT,
          similar_account_url TEXT,
          similar_title TEXT,
          similar_description TEXT,
          similar_tags_json TEXT,
          similar_category TEXT,
          similar_published_at INTEGER,
          similar_video_url TEXT,
          similar_duration REAL,
          similar_thumbnail_url TEXT,
          similar_embed_path TEXT,
          similar_views INTEGER,
          similar_likes INTEGER,
          similar_dislikes INTEGER,
          similar_comments_count INTEGER,
          similar_nsfw INTEGER,
          similar_preview_path TEXT,
          similar_last_checked_at INTEGER,
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
    _ensure_similarity_item_columns(conn)


def _ensure_similarity_item_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(similarity_items)").fetchall()
    }
    for column, column_type in SIMILARITY_ITEM_METADATA_COLUMNS:
        if column in existing:
            continue
        conn.execute(f"ALTER TABLE similarity_items ADD COLUMN {column} {column_type}")


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


def fetch_cached_similarities_batch(
    conn: sqlite3.Connection, sources: list[dict[str, Any]], per_source_limit: int
) -> list[dict[str, Any]]:
    """Fetch cached similars with metadata for multiple sources."""
    if not sources:
        return []
    conditions = " OR ".join(
        ["(source_video_id = ? AND source_instance_domain = ?)"] * len(sources)
    )
    params: list[Any] = []
    for source in sources:
        params.append(source.get("video_id"))
        params.append(source.get("instance_domain") or "")
    params.append(per_source_limit)

    rows = conn.execute(
        f"""
        SELECT
          source_video_id,
          source_instance_domain,
          similar_video_id AS video_id,
          similar_instance_domain AS instance_domain,
          similar_video_uuid AS video_uuid,
          similar_video_numeric_id AS video_numeric_id,
          similar_channel_id AS channel_id,
          similar_channel_name AS channel_name,
          similar_channel_url AS channel_url,
          similar_channel_avatar_url AS channel_avatar_url,
          similar_account_name AS account_name,
          similar_account_url AS account_url,
          similar_title AS title,
          similar_description AS description,
          similar_tags_json AS tags_json,
          similar_category AS category,
          similar_published_at AS published_at,
          similar_video_url AS video_url,
          similar_duration AS duration,
          similar_thumbnail_url AS thumbnail_url,
          similar_embed_path AS embed_path,
          similar_views AS views,
          similar_likes AS likes,
          similar_dislikes AS dislikes,
          similar_comments_count AS comments_count,
          similar_nsfw AS nsfw,
          similar_preview_path AS preview_path,
          similar_last_checked_at AS last_checked_at,
          score,
          rank
        FROM similarity_items
        WHERE ({conditions})
          AND rank <= ?
        ORDER BY source_video_id, source_instance_domain, rank
        """,
        params,
    ).fetchall()
    return [
        {
            "video_id": row["video_id"],
            "video_uuid": row["video_uuid"],
            "video_numeric_id": row["video_numeric_id"],
            "instance_domain": row["instance_domain"],
            "channel_id": row["channel_id"],
            "channel_name": row["channel_name"],
            "channel_url": row["channel_url"],
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
            "score": row["score"],
            "rank": row["rank"],
        }
        for row in rows
    ]


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
            item.get("video_uuid"),
            item.get("video_numeric_id"),
            item.get("channel_id"),
            item.get("channel_name"),
            item.get("channel_url"),
            item.get("channel_avatar_url"),
            item.get("account_name"),
            item.get("account_url"),
            item.get("title"),
            item.get("description"),
            item.get("tags_json"),
            item.get("category"),
            item.get("published_at"),
            item.get("video_url"),
            item.get("duration"),
            item.get("thumbnail_url"),
            item.get("embed_path"),
            item.get("views"),
            item.get("likes"),
            item.get("dislikes"),
            item.get("comments_count"),
            item.get("nsfw"),
            item.get("preview_path"),
            item.get("last_checked_at"),
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


def extract_similarity_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Return metadata fields used in similarity cache rows."""
    return {field: meta.get(field) for field in SIMILARITY_ITEM_METADATA_FIELDS}
