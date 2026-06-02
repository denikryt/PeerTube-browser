#!/usr/bin/env python3
"""Rebuild the Engine SQLite FTS5 lightweight video search index."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
repo_root = script_dir.parents[3]
server_dir = repo_root / "engine" / "server"
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from data.db import connect_db  # noqa: E402
from data.video_search import rebuild_video_search_index  # noqa: E402


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
    conn = connect_db(db_path)
    try:
        stats = rebuild_video_search_index(conn)
        logging.info("video search index rebuilt rows=%s db=%s", stats.get("rows", 0), db_path)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
