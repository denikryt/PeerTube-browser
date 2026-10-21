"""Bootstrap the Client backend SQLite databases before runtime use.

This module is the runtime entrypoint for creating the current Client-owned
users/likes schema. Production startup and repositories call this bootstrap
layer directly instead of transitional ensure wrappers.
"""
from __future__ import annotations

import sqlite3

try:
    from client.backend.db.migrate import apply_client_user_migrations
except ModuleNotFoundError:  # pragma: no cover - direct script/test import fallback.
    from db.migrate import apply_client_user_migrations


def bootstrap_client_users_db(conn: sqlite3.Connection) -> None:
    """Apply the current Client users/likes schema before runtime use.

    This is the explicit runtime bootstrap boundary for the Client DB. It
    delegates to checked-in current-shape SQL resources.
    """
    apply_client_user_migrations(conn)
