#!/usr/bin/env python3
"""Provide ensure-video-indexes runtime helpers."""

import argparse
import logging
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.append(str(script_dir.parents[1]))

from data.db import connect_db
try:
    from engine.server.db.bootstrap import bootstrap_engine_read_indexes
except ModuleNotFoundError:  # pragma: no cover - script import fallback.
    from db.bootstrap import bootstrap_engine_read_indexes


def main() -> None:
    """Handle main."""
    parser = argparse.ArgumentParser(
        description="Create video/embedding indexes used by seed lookups."
    )
    repo_root = script_dir.parents[3]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH

    default_db = (repo_root / DEFAULT_DB_PATH).resolve()
    parser.add_argument("--db", default=str(default_db), help="Path to database.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db_path = Path(args.db)
    db = connect_db(db_path)
    bootstrap_engine_read_indexes(db)
    logging.info("video indexes ensured for %s", db_path)
    db.close()


if __name__ == "__main__":
    main()
