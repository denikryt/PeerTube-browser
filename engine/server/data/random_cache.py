"""Provide random cache runtime helpers backed by stable video index ids."""

from __future__ import annotations

import logging
import random
import sqlite3
from pathlib import Path


def connect_random_cache_db(path: Path) -> sqlite3.Connection:
    """Open the random-cache artifact DB with row-aware results."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def populate_random_cache(
    src_db: sqlite3.Connection,
    cache_db: sqlite3.Connection,
    size: int,
    refresh: bool = False,
    filtered_mode: bool = False,
    max_per_instance: int = 0,
    max_per_author: int = 0,
) -> int:
    """Populate random-cache artifacts with stable `video_index_ids.index_id` values.

    The cache is rebuildable, but the ids inside it must be durable across
    embedding-table rebuilds. Source rows therefore come from active
    `video_index_ids` joined to `videos` and `video_embeddings`.
    """
    if size <= 0:
        return 0
    existing = cache_db.execute("SELECT COUNT(*) FROM random_index_ids").fetchone()
    if not refresh and existing and int(existing[0]) >= size:
        return int(existing[0])
    cache_db.execute("DELETE FROM random_index_ids")
    total_row = src_db.execute(
        """
        SELECT COUNT(*) AS total, MIN(vii.index_id) AS min_id, MAX(vii.index_id) AS max_id
        FROM video_index_ids vii
        JOIN video_embeddings e
          ON e.video_id = vii.video_id AND e.instance_domain = vii.instance_domain
        JOIN videos v
          ON v.video_id = vii.video_id AND v.instance_domain = vii.instance_domain
        WHERE vii.is_active = 1
        """
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
        rows = _fetch_unfiltered_index_ids(src_db, start_id, target, before_start=False)
        if len(rows) < target:
            rows += _fetch_unfiltered_index_ids(src_db, start_id, target - len(rows), before_start=True)
        random.shuffle(rows)
        cache_db.executemany(
            "INSERT INTO random_index_ids (position, index_id) VALUES (?, ?)",
            [(index, int(row["index_id"])) for index, row in enumerate(rows, start=1)],
        )
        cache_db.commit()
        return len(rows)

    index_ids: list[int] = []
    instance_counts: dict[str, int] = {}
    author_counts: dict[str, int] = {}
    seen: set[int] = set()
    scanned = 0
    chunk_size = 10000

    def try_add(entry: sqlite3.Row) -> bool:
        """Add a candidate while preserving existing diversity caps."""
        index_id = int(entry["index_id"])
        if index_id in seen:
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
        index_ids.append(index_id)
        seen.add(index_id)
        if instance:
            instance_counts[instance] = instance_counts.get(instance, 0) + 1
        if author:
            author_counts[author] = author_counts.get(author, 0) + 1
        return True

    def scan_range(range_start: int, range_end: int) -> None:
        """Scan active index ids in a deterministic window before shuffling."""
        nonlocal scanned
        if range_end < range_start:
            return
        current = range_start
        while current <= range_end and len(index_ids) < target:
            rows = src_db.execute(
                """
                SELECT
                  vii.index_id AS index_id,
                  v.instance_domain AS instance_domain,
                  v.channel_id AS channel_id
                FROM video_index_ids vii
                JOIN video_embeddings e
                  ON e.video_id = vii.video_id AND e.instance_domain = vii.instance_domain
                JOIN videos v
                  ON v.video_id = vii.video_id AND v.instance_domain = vii.instance_domain
                WHERE vii.is_active = 1
                  AND vii.index_id >= ? AND vii.index_id <= ?
                ORDER BY vii.index_id
                LIMIT ?
                """,
                (current, range_end, chunk_size),
            ).fetchall()
            if not rows:
                break
            scanned += len(rows)
            current = int(rows[-1]["index_id"]) + 1
            for entry in rows:
                if len(index_ids) >= target:
                    break
                try_add(entry)

    scan_range(start_id, max_id)
    if len(index_ids) < target:
        scan_range(min_id, start_id - 1)

    if len(index_ids) < target:
        logging.info(
            "random cache filtered fill short: target=%d got=%d scanned=%d",
            target,
            len(index_ids),
            scanned,
        )
    logging.info(
        "random cache filtered=%s size=%d scanned=%d max_per_instance=%d max_per_author=%d",
        filtered_mode,
        len(index_ids),
        scanned,
        max_per_instance,
        max_per_author,
    )
    random.shuffle(index_ids)
    cache_db.executemany(
        "INSERT INTO random_index_ids (position, index_id) VALUES (?, ?)",
        [(index, index_id) for index, index_id in enumerate(index_ids, start=1)],
    )
    cache_db.commit()
    return len(index_ids)


def _fetch_unfiltered_index_ids(
    src_db: sqlite3.Connection, start_id: int, target: int, *, before_start: bool
) -> list[sqlite3.Row]:
    """Fetch active random-cache candidates from one side of the start id."""
    comparator = "<" if before_start else ">="
    return src_db.execute(
        f"""
        SELECT vii.index_id
        FROM video_index_ids vii
        JOIN video_embeddings e
          ON e.video_id = vii.video_id AND e.instance_domain = vii.instance_domain
        JOIN videos v
          ON v.video_id = vii.video_id AND v.instance_domain = vii.instance_domain
        WHERE vii.is_active = 1 AND vii.index_id {comparator} ?
        ORDER BY vii.index_id
        LIMIT ?
        """,
        (start_id, target),
    ).fetchall()


def fetch_random_index_ids(cache_db: sqlite3.Connection, limit: int) -> list[int]:
    """Return stable index ids from the random-cache artifact DB."""
    if limit <= 0:
        return []
    count_row = cache_db.execute("SELECT COUNT(*) FROM random_index_ids").fetchone()
    if not count_row:
        return []
    total = int(count_row[0])
    if total <= 0:
        return []
    start = 0 if total <= limit else random.randint(0, total - limit)
    rows = cache_db.execute(
        "SELECT index_id FROM random_index_ids ORDER BY position LIMIT ? OFFSET ?",
        (limit, start),
    ).fetchall()
    return [int(row["index_id"]) for row in rows]
