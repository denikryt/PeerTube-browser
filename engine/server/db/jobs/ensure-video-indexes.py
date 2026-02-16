#!/usr/bin/env python3
import argparse
import logging
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.append(str(script_dir.parents[2]))

from data.db import connect_db
from data.videos import ensure_video_indexes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create video/embedding indexes used by seed lookups."
    )
    repo_root = script_dir.parents[4]
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
    ensure_video_indexes(db)
    logging.info("video indexes ensured for %s", db_path)
    db.close()


if __name__ == "__main__":
    main()
