"""Install the canonical parent-health columns required by Engine read fixtures.

Production crawler schema always provides these tables. Small API/Data fixtures
may specify only the columns under test, so extend them without affecting data.
"""

from __future__ import annotations

import sqlite3


def ensure_parent_health_schema(conn: sqlite3.Connection) -> None:
    """Add explicit error-observation columns to an existing minimal test schema."""
    conn.execute("CREATE TABLE IF NOT EXISTS instances(host TEXT PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS channels("
        "channel_id TEXT, instance_domain TEXT, "
        "PRIMARY KEY(channel_id,instance_domain))"
    )
    for table in ("instances", "channels"):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, dtype in (
            ("health_status", "TEXT"),
            ("health_checked_at", "INTEGER"),
            ("health_error", "TEXT"),
        ):
            if column not in columns:
                # Existing positional inserts in test setup run before this
                # extension; subsequent test writes should name their columns.
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {dtype}")
