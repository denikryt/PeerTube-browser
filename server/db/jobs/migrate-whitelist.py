#!/usr/bin/env python3
"""Migrate an existing whitelist.db to the latest schema without rebuilding data."""
from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from scripts.cli_format import CompactHelpFormatter
from server.db.jobs.whitelist_migrations import migrate_whitelist_schema

DEFAULT_WHITELIST_DB_PATH = Path("server/db/whitelist.db")
TABLE_NAME = "instances"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate whitelist.db schema in-place.",
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument(
        "--db",
        dest="whitelist_db",
        type=Path,
        default=DEFAULT_WHITELIST_DB_PATH,
        help="Path to whitelist.db.",
    )
    parser.add_argument(
        "--backup",
        dest="backup",
        action="store_true",
        default=True,
        help="Create a timestamped backup before migrating (default).",
    )
    parser.add_argument(
        "--no-backup",
        dest="backup",
        action="store_false",
        help="Skip backup creation.",
    )
    return parser.parse_args()


def backup_db(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak-{timestamp}")
    backup_path.write_bytes(path.read_bytes())
    wal = path.with_suffix(path.suffix + "-wal")
    shm = path.with_suffix(path.suffix + "-shm")
    if wal.exists():
        wal_backup = wal.with_name(f"{wal.name}.bak-{timestamp}")
        wal_backup.write_bytes(wal.read_bytes())
    if shm.exists():
        shm_backup = shm.with_name(f"{shm.name}.bak-{timestamp}")
        shm_backup.write_bytes(shm.read_bytes())
    return backup_path


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not args.whitelist_db.exists():
        raise FileNotFoundError(args.whitelist_db)

    if args.backup:
        backup_path = backup_db(args.whitelist_db)
        logging.info("Backup created: %s", backup_path)

    conn = sqlite3.connect(args.whitelist_db.as_posix())
    try:
        with conn:
            migrate_whitelist_schema(conn, TABLE_NAME)
    finally:
        conn.close()

    logging.info("Migration completed for %s", args.whitelist_db)


if __name__ == "__main__":
    main()
