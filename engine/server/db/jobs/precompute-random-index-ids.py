#!/usr/bin/env python3
"""Build and atomically publish the updater-owned random browse-order artifact."""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.append(str(script_dir.parents[1]))

from data.random_cache import rebuild_random_cache


def connect_source_db(path: Path) -> sqlite3.Connection:
    """Open the canonical source DB read-only for artifact construction."""
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def build_parser() -> argparse.ArgumentParser:
    """Create the standalone builder CLI without obsolete reset compatibility."""
    parser = argparse.ArgumentParser(description="Precompute random index-id cache.")
    repo_root = script_dir.parents[3]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH

    parser.add_argument("--db", default=str((repo_root / DEFAULT_DB_PATH).resolve()), help="Path to crawl database.")
    parser.add_argument("--out", default=str(script_dir.parent / "random-cache.db"), help="Final artifact path.")
    parser.add_argument("--size", type=int, default=5000, help="Index ids to sample.")
    parser.add_argument("--refresh", action="store_true", help="Force a new artifact generation even if the final artifact is sufficient.")
    parser.add_argument("--filtered", action="store_true", help="Build cache with per-instance/author caps.")
    parser.add_argument("--max-per-instance", type=int, default=0, help="Max videos per instance in filtered mode.")
    parser.add_argument("--max-per-author", type=int, default=0, help="Max videos per channel in filtered mode.")
    return parser


def main() -> None:
    """Build a complete sibling temp DB and publish it to ``--out`` atomically."""
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    src_db = connect_source_db(Path(args.db))
    try:
        result = rebuild_random_cache(
            src_db,
            Path(args.out),
            size=args.size,
            refresh=args.refresh,
            filtered_mode=args.filtered,
            max_per_instance=args.max_per_instance,
            max_per_author=args.max_per_author,
        )
    finally:
        src_db.close()
    logging.info(
        "random cache size=%d build_id=%s rebuilt=%s",
        int(result["count"]),
        result["build_id"],
        "true" if result["rebuilt"] else "false",
    )


if __name__ == "__main__":
    main()
