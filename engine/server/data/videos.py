"""Provide videos runtime helpers."""

from __future__ import annotations

import sqlite3

try:
    from engine.server.db.migrations.apply import apply_main_read_indexes
except ModuleNotFoundError:  # pragma: no cover - script import fallback
    from db.migrations.apply import apply_main_read_indexes


def ensure_video_indexes(conn: sqlite3.Connection) -> None:
    """Create indexes to speed up seed lookups and embedding joins.

    The Stage 6 migration helper keeps the existing conditional behavior: it
    only creates indexes whose target tables already exist.
    """
    apply_main_read_indexes(conn)


