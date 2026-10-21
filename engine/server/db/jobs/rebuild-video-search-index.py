#!/usr/bin/env python3
"""Rebuild the Engine SQLite FTS5 lightweight video search index."""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

script_dir = Path(__file__).resolve().parent
repo_root = script_dir.parents[3]
server_dir = repo_root / "engine" / "server"
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from data.db import connect_db  # noqa: E402
from data.video_search import rebuild_video_search_index  # noqa: E402


def _count_table_rows(conn, table_name: str) -> int | None:
    """Return a table row count for operational logs without failing the rebuild."""
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row is not None else None


def _count_source_videos(conn) -> int | None:
    """Count eligible source videos so operators can distinguish empty DBs from job failures."""
    try:
        row = conn.execute("SELECT COUNT(*) FROM videos WHERE COALESCE(invalid_reason, '') = ''").fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row is not None else None


def main() -> None:
    """Parse CLI args, rebuild the search index, and log the resulting row count."""
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH  # noqa: WPS433 - loaded after path setup.

    parser = argparse.ArgumentParser(description="Rebuild the SQLite FTS5 video search index.")
    default_db = (repo_root / DEFAULT_DB_PATH).resolve()
    parser.add_argument("--db", default=str(default_db), help="Path to the Engine videos database.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db_path = Path(args.db)
    started = time.monotonic()
    logging.info("video search index rebuild started db=%s", db_path)
    conn = connect_db(db_path)
    try:
        source_count = _count_source_videos(conn)
        if source_count is None:
            logging.info("video search source count unavailable db=%s", db_path)
        else:
            logging.info("video search source videos eligible=%s db=%s", source_count, db_path)

        stats = rebuild_video_search_index(conn)
        docs_count = _count_table_rows(conn, "video_search_docs")
        fts_count = _count_table_rows(conn, "video_search_fts")
        elapsed = time.monotonic() - started
        logging.info(
            "video search index tables docs=%s fts=%s elapsed=%.2fs db=%s",
            docs_count if docs_count is not None else "unknown",
            fts_count if fts_count is not None else "unknown",
            elapsed,
            db_path,
        )
        logging.info("video search index rebuilt rows=%s db=%s", stats.get("rows", 0), db_path)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
