"""Regression tests for the stable video index-id migration."""
from __future__ import annotations

import sqlite3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))

from engine.server.db.migrations.apply import apply_video_index_ids_migration  # noqa: E402


def test_video_index_ids_migration_creates_stable_identity_table() -> None:
    """Runtime migration must expose the durable mapping required by ANN artifacts."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    apply_video_index_ids_migration(conn)

    columns = {row[1]: row for row in conn.execute("PRAGMA table_info(video_index_ids)")}
    assert columns["index_id"][5] == 1
    assert columns["video_id"]
    assert columns["instance_domain"]
    assert columns["is_active"]
    assert columns["retired_at"]
    assert columns["retired_reason"]
    indexes = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        if not row["name"].startswith("sqlite_autoindex")
    }
    assert {"idx_video_index_ids_active", "idx_video_index_ids_identity"}.issubset(indexes)


def test_video_index_ids_unique_video_identity_keeps_one_index_id() -> None:
    """The same video identity must not receive multiple FAISS ids."""
    conn = sqlite3.connect(":memory:")
    apply_video_index_ids_migration(conn)

    conn.execute(
        """
        INSERT INTO video_index_ids (video_id, instance_domain, created_at, updated_at)
        VALUES ('v1', 'tube.example', 1, 1)
        """
    )
    try:
        conn.execute(
            """
            INSERT INTO video_index_ids (video_id, instance_domain, created_at, updated_at)
            VALUES ('v1', 'tube.example', 2, 2)
            """
        )
    except sqlite3.IntegrityError:
        pass
    else:  # pragma: no cover - easier failure detail than pytest.raises here.
        raise AssertionError("duplicate video identity inserted")
