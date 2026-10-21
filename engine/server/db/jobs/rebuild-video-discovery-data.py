#!/usr/bin/env python3
"""Rebuild updater-owned normalized tags and prepared facet snapshot."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))
api_dir = server_dir / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from data.db import connect_db  # noqa: E402
from data.prepared_discovery import rebuild_prepared_discovery  # noqa: E402
from scripts.cli_format import CompactHelpFormatter  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Parse the canonical DB path for the standalone rebuild job."""
    repo_root = script_dir.parents[3]
    from server_config import DEFAULT_DB_PATH

    parser = argparse.ArgumentParser(
        description="Rebuild normalized video tags and prepared video facets.",
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument(
        "--db",
        default=str((repo_root / DEFAULT_DB_PATH).resolve()),
        help="Path to the canonical whitelist database.",
    )
    return parser.parse_args()


def main() -> None:
    """Rebuild prepared Discovery atomically and refresh SQLite planner statistics."""
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db_path = Path(args.db).resolve()
    conn = connect_db(db_path)
    try:
        stats = rebuild_prepared_discovery(conn)
        conn.execute("PRAGMA optimize")
    finally:
        conn.close()

    logging.info(
        "prepared Discovery rebuilt db=%s source_videos=%d tag_memberships=%d "
        "languages=%d categories=%d tags=%d instances=%d",
        db_path,
        stats["source_video_count"],
        stats["tag_membership_count"],
        stats["language_count"],
        stats["category_count"],
        stats["tag_count"],
        stats["instance_count"],
    )


if __name__ == "__main__":
    main()
