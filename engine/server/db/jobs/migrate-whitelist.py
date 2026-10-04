#!/usr/bin/env python3
"""Migrate an existing whitelist.db to the latest schema without rebuilding data."""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
engine_dir = script_dir.parents[2]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))
if str(engine_dir) not in sys.path:
    sys.path.insert(0, str(engine_dir))

if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from scripts.cli_format import CompactHelpFormatter
from data.prepared_discovery import invalidate_prepared_discovery
from whitelist_migrations import (
    migrate_whitelist_schema,
    normalize_video_availability_semantics,
)

DEFAULT_WHITELIST_DB_PATH = Path("engine/server/db/whitelist.db")
TABLE_NAME = "instances"


def parse_args() -> argparse.Namespace:
    """Handle parse args."""
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
    """Handle backup db."""
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
    """Handle main."""
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
        # Schema helpers may executescript()/commit; the semantic cutover owns
        # a separate transaction so cleanup and readiness cannot split.
        conn.execute('BEGIN IMMEDIATE')
        with conn:
            report = normalize_video_availability_semantics(conn)
            if report['rows_changed']:
                invalidate_prepared_discovery(conn)
        logging.info('Availability normalization: %s', json.dumps(report, ensure_ascii=True))
    finally:
        conn.close()

    logging.info("Migration completed for %s", args.whitelist_db)


if __name__ == "__main__":
    main()
