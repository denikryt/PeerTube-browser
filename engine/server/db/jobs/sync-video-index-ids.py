#!/usr/bin/env python3
"""Synchronize stable FAISS-compatible video index ids.

The job owns the durable mapping from canonical video identity to numeric
`index_id`. It runs after the production content DB has been merged/pruned and
before ANN, random-cache, or similarity artifacts are rebuilt.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

try:
    from engine.server.db.bootstrap import bootstrap_engine_video_index_ids
except ModuleNotFoundError:  # pragma: no cover - script import fallback.
    from db.bootstrap import bootstrap_engine_video_index_ids


@dataclass(frozen=True)
class SyncStats:
    """Report observable row counts from one index-id sync run."""

    inserted: int
    reactivated: int
    retired: int
    active: int
    total: int


def connect_db(path: Path) -> sqlite3.Connection:
    """Open the target Engine-readable SQLite DB for identity synchronization."""
    conn = sqlite3.connect(path.as_posix())
    conn.row_factory = sqlite3.Row
    return conn


def _now_ms() -> int:
    """Return UTC epoch milliseconds for deterministic integer timestamps."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def sync_video_index_ids(conn: sqlite3.Connection, *, dry_run: bool = False) -> SyncStats:
    """Refresh `video_index_ids` from the current videos+embeddings join.

    A mapping is active only when the same `(video_id, instance_domain)` exists
    in both content metadata and embeddings. Inactive rows are retained so old
    ids are never reassigned to a different video.
    """
    bootstrap_engine_video_index_ids(conn)
    now = _now_ms()
    before_total = int(conn.execute("SELECT COUNT(*) FROM video_index_ids").fetchone()[0])
    before_inactive_indexable = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM video_index_ids vii
            JOIN video_embeddings e
              ON e.video_id = vii.video_id
             AND e.instance_domain = vii.instance_domain
            JOIN videos v
              ON v.video_id = vii.video_id
             AND v.instance_domain = vii.instance_domain
            WHERE vii.is_active = 0
            """
        ).fetchone()[0]
    )
    before_retirable = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM video_index_ids vii
            WHERE vii.is_active = 1
              AND NOT EXISTS (
                SELECT 1
                FROM video_embeddings e
                JOIN videos v
                  ON v.video_id = e.video_id
                 AND v.instance_domain = e.instance_domain
                WHERE e.video_id = vii.video_id
                  AND e.instance_domain = vii.instance_domain
              )
            """
        ).fetchone()[0]
    )
    if dry_run:
        active = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM video_index_ids vii
                JOIN video_embeddings e
                  ON e.video_id = vii.video_id
                 AND e.instance_domain = vii.instance_domain
                JOIN videos v
                  ON v.video_id = vii.video_id
                 AND v.instance_domain = vii.instance_domain
                """
            ).fetchone()[0]
        )
        return SyncStats(0, before_inactive_indexable, before_retirable, active, before_total)

    # Insert current indexable videos without touching existing mappings; the
    # UNIQUE key preserves the original index_id for already-known identities.
    conn.execute(
        """
        INSERT OR IGNORE INTO video_index_ids (
          video_id,
          instance_domain,
          is_active,
          created_at,
          updated_at,
          retired_at,
          retired_reason
        )
        SELECT e.video_id, e.instance_domain, 1, ?, ?, NULL, NULL
        FROM video_embeddings e
        JOIN videos v
          ON v.video_id = e.video_id
         AND v.instance_domain = e.instance_domain
        """,
        (now, now),
    )
    after_insert_total = int(conn.execute("SELECT COUNT(*) FROM video_index_ids").fetchone()[0])
    inserted = after_insert_total - before_total

    # Reactivation keeps the same index_id but makes the mapping eligible for
    # future artifacts once both the video and embedding exist again.
    conn.execute(
        """
        UPDATE video_index_ids
        SET is_active = 1,
            updated_at = ?,
            retired_at = NULL,
            retired_reason = NULL
        WHERE is_active = 0
          AND EXISTS (
            SELECT 1
            FROM video_embeddings e
            JOIN videos v
              ON v.video_id = e.video_id
             AND v.instance_domain = e.instance_domain
            WHERE e.video_id = video_index_ids.video_id
              AND e.instance_domain = video_index_ids.instance_domain
          )
        """,
        (now,),
    )

    # Retired mappings remain durable history. The reason is diagnostic only and
    # never changes public API output.
    conn.execute(
        """
        UPDATE video_index_ids
        SET is_active = 0,
            updated_at = ?,
            retired_at = ?,
            retired_reason = CASE
              WHEN NOT EXISTS (
                SELECT 1 FROM videos v
                WHERE v.video_id = video_index_ids.video_id
                  AND v.instance_domain = video_index_ids.instance_domain
              ) THEN 'missing_video'
              WHEN NOT EXISTS (
                SELECT 1 FROM video_embeddings e
                WHERE e.video_id = video_index_ids.video_id
                  AND e.instance_domain = video_index_ids.instance_domain
              ) THEN 'missing_embedding'
              ELSE 'not_indexable'
            END
        WHERE is_active = 1
          AND NOT EXISTS (
            SELECT 1
            FROM video_embeddings e
            JOIN videos v
              ON v.video_id = e.video_id
             AND v.instance_domain = e.instance_domain
            WHERE e.video_id = video_index_ids.video_id
              AND e.instance_domain = video_index_ids.instance_domain
          )
        """,
        (now, now),
    )
    conn.commit()
    active = int(conn.execute("SELECT COUNT(*) FROM video_index_ids WHERE is_active = 1").fetchone()[0])
    total = int(conn.execute("SELECT COUNT(*) FROM video_index_ids").fetchone()[0])
    return SyncStats(inserted, before_inactive_indexable, before_retirable, active, total)


def main() -> None:
    """Run the stable index-id synchronization command."""
    parser = argparse.ArgumentParser(description="Synchronize stable video index ids.")
    repo_root = script_dir.parents[3]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH

    default_db = (repo_root / DEFAULT_DB_PATH).resolve()
    parser.add_argument("--db", "--db-path", dest="db", default=str(default_db), help="Path to Engine SQLite database.")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without mutating mappings.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    conn = connect_db(Path(args.db))
    stats = sync_video_index_ids(conn, dry_run=args.dry_run)
    logging.info(
        "inserted=%d reactivated=%d retired=%d active=%d total=%d",
        stats.inserted,
        stats.reactivated,
        stats.retired,
        stats.active,
        stats.total,
    )
    conn.close()


if __name__ == "__main__":
    main()
