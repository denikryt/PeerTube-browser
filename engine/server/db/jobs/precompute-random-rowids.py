#!/usr/bin/env python3
"""Provide precompute-random-rowids runtime helpers."""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.append(str(script_dir.parents[1]))

from data.random_cache import connect_random_cache_db, populate_random_cache


def connect_source_db(path: Path) -> sqlite3.Connection:
    """Handle connect source db."""
    quoted = path.as_posix()
    uri = f"file:{quoted}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def main() -> None:
    """Handle main."""
    parser = argparse.ArgumentParser(description="Precompute random rowid cache.")
    repo_root = script_dir.parents[3]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH

    default_db = (repo_root / DEFAULT_DB_PATH).resolve()
    default_out = script_dir.parent / "random-cache.db"
    parser.add_argument("--db", default=str(default_db), help="Path to crawl database.")
    parser.add_argument("--out", default=str(default_out), help="Output cache database.")
    parser.add_argument("--size", type=int, default=5000, help="Rowids to sample.")
    parser.add_argument("--reset", action="store_true", help="Clear existing cache.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Rebuild cache even if it already meets the size.",
    )
    parser.add_argument(
        "--filtered",
        action="store_true",
        help="Build cache with per-instance/author caps.",
    )
    parser.add_argument(
        "--max-per-instance",
        type=int,
        default=0,
        help="Max videos per instance (filtered mode).",
    )
    parser.add_argument(
        "--max-per-author",
        type=int,
        default=0,
        help="Max videos per channel (filtered mode).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    src_db = connect_source_db(Path(args.db))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_db = connect_random_cache_db(out_path)
    if args.reset:
        out_db.execute("DELETE FROM random_rowids")
        out_db.commit()
    count = populate_random_cache(
        src_db,
        out_db,
        args.size,
        args.refresh,
        args.filtered,
        args.max_per_instance,
        args.max_per_author,
    )
    logging.info("random cache size=%d", count)


if __name__ == "__main__":
    main()
