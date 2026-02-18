"""Provide random cache runtime helpers."""

from __future__ import annotations

import logging
import random
import sqlite3
from pathlib import Path


def connect_random_cache_db(path: Path) -> sqlite3.Connection:
    """Handle connect random cache db."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_random_cache_schema(conn: sqlite3.Connection) -> None:
    """Handle ensure random cache schema."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS random_rowids (
          position INTEGER PRIMARY KEY,
          video_rowid INTEGER NOT NULL
        );
        """
    )


def populate_random_cache(
    src_db: sqlite3.Connection,
    cache_db: sqlite3.Connection,
    size: int,
    refresh: bool = False,
    filtered_mode: bool = False,
    max_per_instance: int = 0,
    max_per_author: int = 0,
) -> int:
    """Handle populate random cache."""
    if size <= 0:
        return 0
    ensure_random_cache_schema(cache_db)
    existing = cache_db.execute("SELECT COUNT(*) FROM random_rowids").fetchone()
    if not refresh and existing and int(existing[0]) >= size:
        return int(existing[0])
    cache_db.execute("DELETE FROM random_rowids")
    total_row = src_db.execute(
        "SELECT COUNT(*) AS total, MIN(rowid) AS min_id, MAX(rowid) AS max_id "
        "FROM video_embeddings"
    ).fetchone()
    if not total_row:
        cache_db.commit()
        return 0
    total = int(total_row["total"] or 0)
    if total == 0:
        cache_db.commit()
        return 0
    min_id = int(total_row["min_id"])
    max_id = int(total_row["max_id"])
    target = min(size, total)
    start_id = random.randint(min_id, max_id)
    if not filtered_mode or (max_per_instance <= 0 and max_per_author <= 0):
        rows = src_db.execute(
            "SELECT rowid FROM video_embeddings WHERE rowid >= ? ORDER BY rowid LIMIT ?",
            (start_id, target),
        ).fetchall()
        if len(rows) < target:
            rows += src_db.execute(
                "SELECT rowid FROM video_embeddings WHERE rowid < ? ORDER BY rowid LIMIT ?",
                (start_id, target - len(rows)),
            ).fetchall()
        random.shuffle(rows)
        cache_db.executemany(
            "INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)",
            [(index, int(row["rowid"])) for index, row in enumerate(rows, start=1)],
        )
        cache_db.commit()
        return len(rows)

    rowids: list[int] = []
    instance_counts: dict[str, int] = {}
    author_counts: dict[str, int] = {}
    seen: set[int] = set()
    scanned = 0
    chunk_size = 10000

    def try_add(entry: sqlite3.Row) -> bool:
        """Handle try add."""
        rowid = int(entry["rowid"])
        if rowid in seen:
            return False
        instance = entry["instance_domain"] or ""
        if max_per_instance > 0 and instance:
            if instance_counts.get(instance, 0) >= max_per_instance:
                return False
        author: str | None = None
        channel_id = entry["channel_id"]
        if channel_id:
            author = f"{channel_id}::{instance}"
            if max_per_author > 0 and author_counts.get(author, 0) >= max_per_author:
                return False
        rowids.append(rowid)
        seen.add(rowid)
        if instance:
            instance_counts[instance] = instance_counts.get(instance, 0) + 1
        if author:
            author_counts[author] = author_counts.get(author, 0) + 1
        return True

    def scan_range(range_start: int, range_end: int) -> None:
        """Handle scan range."""
        nonlocal scanned
        if range_end < range_start:
            return
        current = range_start
        while current <= range_end and len(rowids) < target:
            rows = src_db.execute(
                """
                SELECT
                  e.rowid AS rowid,
                  v.instance_domain AS instance_domain,
                  v.channel_id AS channel_id
                FROM video_embeddings e
                JOIN videos v
                  ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
                WHERE e.rowid >= ? AND e.rowid <= ?
                ORDER BY e.rowid
                LIMIT ?
                """,
                (current, range_end, chunk_size),
            ).fetchall()
            if not rows:
                break
            scanned += len(rows)
            current = int(rows[-1]["rowid"]) + 1
            for entry in rows:
                if len(rowids) >= target:
                    break
                try_add(entry)

    scan_range(start_id, max_id)
    if len(rowids) < target:
        scan_range(min_id, start_id - 1)

    if len(rowids) < target:
        logging.info(
            "random cache filtered fill short: target=%d got=%d scanned=%d",
            target,
            len(rowids),
            scanned,
        )
    logging.info(
        "random cache filtered=%s size=%d scanned=%d max_per_instance=%d max_per_author=%d",
        filtered_mode,
        len(rowids),
        scanned,
        max_per_instance,
        max_per_author,
    )
    random.shuffle(rowids)
    cache_db.executemany(
        "INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)",
        [(index, rowid) for index, rowid in enumerate(rowids, start=1)],
    )
    cache_db.commit()
    return len(rowids)


def fetch_random_rowids(cache_db: sqlite3.Connection, limit: int) -> list[int]:
    """Handle fetch random rowids."""
    if limit <= 0:
        return []
    count_row = cache_db.execute("SELECT COUNT(*) FROM random_rowids").fetchone()
    if not count_row:
        return []
    total = int(count_row[0])
    if total <= 0:
        return []
    start = 0 if total <= limit else random.randint(0, total - limit)
    rows = cache_db.execute(
        "SELECT video_rowid FROM random_rowids ORDER BY position LIMIT ? OFFSET ?",
        (limit, start),
    ).fetchall()
    return [int(row["video_rowid"]) for row in rows]
