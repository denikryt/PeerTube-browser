"""Regression coverage for observable incremental popularity writes."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JOB = ROOT / "engine/server/db/jobs/recompute-popularity.py"


def test_incremental_popularity_skips_unchanged_zero_score(tmp_path: Path) -> None:
    """An already-zero score causes no row write; a new positive score persists."""
    db_path = tmp_path / "videos.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE videos (
                video_id TEXT NOT NULL,
                instance_domain TEXT NOT NULL,
                title TEXT,
                views INTEGER,
                likes INTEGER,
                published_at INTEGER,
                popularity REAL,
                PRIMARY KEY (video_id, instance_domain)
            );
            CREATE TABLE observed_updates (video_id TEXT NOT NULL);
            CREATE TRIGGER popularity_write AFTER UPDATE OF popularity ON videos
            BEGIN
                INSERT INTO observed_updates(video_id) VALUES (NEW.video_id);
            END;
            INSERT INTO videos VALUES ('zero', 'example.org', 'Zero', 0, 0, 1, 0);
            INSERT INTO videos VALUES ('new', 'example.org', 'New', 100, 1, 1, 0);
            INSERT INTO videos VALUES ('unset', 'example.org', 'Unset', 0, 0, 1, NULL);
            """
        )

    # Run the production CLI, then inspect the trigger log so a same-value
    # UPDATE remains visible even when the stored popularity still equals zero.
    subprocess.run(
        [sys.executable, str(JOB), "--db", str(db_path), "--incremental"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    with sqlite3.connect(db_path) as conn:
        updates = conn.execute("SELECT video_id FROM observed_updates").fetchall()
        scores = dict(conn.execute("SELECT video_id, popularity FROM videos"))

    assert updates == [("new",), ("unset",)]
    assert scores["zero"] == 0
    assert scores["new"] > 0
    assert scores["unset"] == 0
