"""Apply Client backend current-shape SQLite migrations.

This module owns the checked-in SQL resource application for the Client users
DB. It intentionally does not create a migration history table in Stage 6
because existing startup paths rely on idempotent current-shape schema helpers.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def apply_client_user_migrations(conn: sqlite3.Connection) -> None:
    """Apply the current users/likes schema to a Client users database.

    The files are executed in filename order so future current-shape resources
    have one deterministic application point while preserving current helper
    behavior for existing callers.
    """
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.executescript(path.read_text(encoding="utf-8"))
    conn.commit()
