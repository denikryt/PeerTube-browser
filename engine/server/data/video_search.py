"""SQLite FTS5 video search index helpers for the Engine runtime.

The Engine owns the FTS schema because search is derived from the Engine-readable
video database. Public identity remains ``video_id`` plus ``instance_domain``;
FTS rowids are only internal doc ids used to join matches back to video rows.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def ensure_video_search_schema(conn: sqlite3.Connection) -> None:
    """Create the explicit doc mapping and lightweight FTS5 table if missing."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_search_docs (
          doc_id INTEGER PRIMARY KEY,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          UNIQUE(video_id, instance_domain)
        )
        """
    )
    # Contentless FTS keeps the artifact small; video identity is intentionally
    # stored in video_search_docs so rowids never escape as API identity.
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS video_search_fts USING fts5(
          title,
          channel_name,
          tags,
          category,
          instance_domain,
          content=''
        )
        """
    )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Return whether a table exists without assuming production schema state."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _tags_text(value: Any) -> str:
    """Normalize PeerTube tags JSON into searchable text without throwing."""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(parsed, list):
        return " ".join(str(item).strip() for item in parsed if str(item).strip())
    if isinstance(parsed, dict):
        return " ".join(str(item).strip() for item in parsed.values() if str(item).strip())
    return str(parsed).strip()


def normalize_fts_query(query: str) -> str:
    """Turn raw user text into conservative FTS prefix terms.

    FTS5 supports a rich query syntax, but browser input should not be parsed as
    syntax. Tokenizing to word terms and appending ``*`` gives simple prefix
    matching while avoiding malformed punctuation-only MATCH expressions.
    """
    terms = [term.lower() for term in TOKEN_RE.findall(query or "") if term.strip()]
    if not terms:
        return ""
    return " ".join(f"{term}*" for term in terms[:8])


def rebuild_video_search_index(conn: sqlite3.Connection) -> dict[str, int]:
    """Rebuild the full lightweight video search index from ``videos`` rows."""
    ensure_video_search_schema(conn)
    with conn:
        # Contentless FTS5 tables cannot be cleared with DELETE on all SQLite
        # builds, so a rebuild drops and recreates the FTS table while preserving
        # the stable public doc mapping contract in video_search_docs.
        conn.execute("DROP TABLE IF EXISTS video_search_fts")
        conn.execute("DELETE FROM video_search_docs")
        ensure_video_search_schema(conn)
        has_channels = _table_exists(conn, "channels")
        channel_select = "COALESCE(c.display_name, '')" if has_channels else "''"
        channel_join = (
            "LEFT JOIN channels c ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain"
            if has_channels
            else ""
        )
        rows = conn.execute(
            f"""
            SELECT
              v.video_id,
              v.instance_domain,
              COALESCE(v.title, '') AS title,
              COALESCE(v.channel_name, '') AS channel_name,
              {channel_select} AS channel_display_name,
              v.tags_json,
              COALESCE(v.category, '') AS category
            FROM videos v
            {channel_join}
            WHERE COALESCE(v.invalid_reason, '') = ''
            ORDER BY v.instance_domain ASC, v.video_id ASC
            """
        ).fetchall()
        count = 0
        for row in rows:
            cursor = conn.execute(
                "INSERT INTO video_search_docs(video_id, instance_domain) VALUES (?, ?)",
                (row["video_id"], row["instance_domain"]),
            )
            doc_id = int(cursor.lastrowid)
            channel_text = f"{row['channel_name'] or ''} {row['channel_display_name'] or ''}".strip()
            conn.execute(
                """
                INSERT INTO video_search_fts(rowid, title, channel_name, tags, category, instance_domain)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    row["title"] or "",
                    channel_text,
                    _tags_text(row["tags_json"]),
                    row["category"] or "",
                    row["instance_domain"] or "",
                ),
            )
            count += 1
    return {"rows": count}


def search_videos(
    conn: sqlite3.Connection,
    *,
    query: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int | None]:
    """Search videos by lightweight indexed fields and return stable video rows."""
    fts_query = normalize_fts_query(query)
    if not fts_query:
        return [], None
    fetch_limit = max(limit, 1) + 1
    safe_offset = max(offset, 0)
    rows = conn.execute(
        """
        WITH matched AS (
          SELECT rowid AS doc_id, bm25(video_search_fts) AS rank
          FROM video_search_fts
          WHERE video_search_fts MATCH ?
          ORDER BY rank ASC
          LIMIT ? OFFSET ?
        )
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
          v.published_at,
          v.video_url,
          v.duration,
          v.thumbnail_url,
          v.embed_path,
          v.preview_path,
          v.views,
          v.likes,
          v.dislikes,
          v.comments_count,
          matched.rank
        FROM matched
        JOIN video_search_docs d ON d.doc_id = matched.doc_id
        JOIN videos v ON v.video_id = d.video_id AND v.instance_domain = d.instance_domain
        LEFT JOIN channels c ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        WHERE COALESCE(v.invalid_reason, '') = ''
        ORDER BY matched.rank ASC,
          COALESCE(v.popularity, 0) DESC,
          COALESCE(v.published_at, 0) DESC,
          v.video_id ASC
        """,
        (fts_query, fetch_limit, safe_offset),
    ).fetchall()
    items = rows[: max(limit, 1)]
    next_offset = safe_offset + len(items) if len(rows) > len(items) else None
    return [
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
            "published_at": row["published_at"],
            "video_url": row["video_url"],
            "duration": row["duration"],
            "thumbnail_url": row["thumbnail_url"],
            "embed_path": row["embed_path"],
            "preview_path": row["preview_path"],
            "views": row["views"],
            "likes": row["likes"],
            "dislikes": row["dislikes"],
            "comments_count": row["comments_count"],
        }
        for row in items
    ], next_offset
