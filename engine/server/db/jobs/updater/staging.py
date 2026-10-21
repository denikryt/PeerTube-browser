"""Staging database helpers for the updater pipeline.

These helpers preserve the current SQLite table assumptions while moving DB
operations out of the executable updater wrapper.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path


def remove_db_with_sidecars(db_path: Path) -> None:
    """Remove an SQLite DB and WAL/SHM sidecars using current file names."""

    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db_path) + suffix)
        if path.exists():
            path.unlink()


def init_staging_db(staging_db: Path, schema_path: Path) -> None:
    """Recreate staging DB from crawler schema and ensure crawl_state exists."""

    remove_db_with_sidecars(staging_db)
    staging_db.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = schema_path.read_text(encoding="utf-8")
    with sqlite3.connect(staging_db) as conn:
        conn.executescript(schema_sql)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS crawl_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.commit()


def shared_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Return ordered columns shared by prod main and attached staging table."""

    prod_cols = [row[1] for row in conn.execute(f"PRAGMA main.table_info({table})")]
    staging_cols = [row[1] for row in conn.execute(f"PRAGMA staging.table_info({table})")]
    return [col for col in prod_cols if col in staging_cols]


def seed_staging_from_prod(prod_db: Path, staging_db: Path) -> None:
    """Seed instances/channels from prod into staging using shared columns only."""

    with sqlite3.connect(prod_db) as conn:
        conn.execute("ATTACH DATABASE ? AS staging", (staging_db.as_posix(),))
        for table in ("instances", "channels"):
            cols = shared_columns(conn, table)
            if not cols:
                continue
            col_sql = ", ".join(f'"{col}"' for col in cols)
            conn.execute(
                f"INSERT OR REPLACE INTO staging.{table} ({col_sql}) "
                f"SELECT {col_sql} FROM main.{table}"
            )
        conn.execute(
            "INSERT OR REPLACE INTO staging.crawl_state(key, value) VALUES (?, datetime('now'))",
            ("stage_seeded_at",),
        )
        conn.execute(
            "INSERT OR REPLACE INTO staging.crawl_state(key, value) VALUES (?, ?)",
            ("stage_seeded_from", prod_db.as_posix()),
        )
        conn.commit()
        conn.execute("DETACH DATABASE staging")


def count_staging_deltas(prod_db: Path, staging_db: Path) -> dict[str, int]:
    """Count current staging rows not present in prod by primary identity."""

    with sqlite3.connect(prod_db) as conn:
        conn.execute("ATTACH DATABASE ? AS staging", (staging_db.as_posix(),))
        instances_new = conn.execute(
            "SELECT COUNT(*) FROM staging.instances s "
            "LEFT JOIN main.instances p ON lower(p.host)=lower(s.host) WHERE p.host IS NULL"
        ).fetchone()[0]
        channels_new = conn.execute(
            "SELECT COUNT(*) FROM staging.channels s "
            "LEFT JOIN main.channels p ON lower(p.host)=lower(s.host) "
            "AND p.name=s.name WHERE p.id IS NULL"
        ).fetchone()[0]
        videos_new = conn.execute(
            "SELECT COUNT(*) FROM staging.videos s "
            "LEFT JOIN main.videos p ON lower(p.host)=lower(s.host) "
            "AND p.uuid=s.uuid WHERE p.id IS NULL"
        ).fetchone()[0]
        embeddings_new = 0
        prod_has_embeddings = conn.execute(
            "SELECT COUNT(*) FROM main.sqlite_master WHERE type='table' AND name='video_embeddings'"
        ).fetchone()[0]
        staging_has_embeddings = conn.execute(
            
                "SELECT COUNT(*) FROM staging.sqlite_master "
                "WHERE type='table' AND name='video_embeddings'"
            
        ).fetchone()[0]
        if prod_has_embeddings and staging_has_embeddings:
            embeddings_new = conn.execute(
                "SELECT COUNT(*) FROM staging.video_embeddings s "
                "LEFT JOIN main.video_embeddings p ON p.video_id=s.video_id "
                "WHERE p.video_id IS NULL"
            ).fetchone()[0]
        conn.execute("DETACH DATABASE staging")
    return {
        "instances_new": int(instances_new),
        "channels_new": int(channels_new),
        "videos_new": int(videos_new),
        "embeddings_new": int(embeddings_new),
    }


def prune_staging_local_non_ok_instances(*, prod_db: Path, staging_db: Path) -> dict[str, int]:
    """Drop staging hosts that are marked non-ok in the prod instances table."""

    with sqlite3.connect(prod_db) as conn:
        bad_hosts = {
            str(row[0]).strip().lower()
            for row in conn.execute(
                "SELECT host FROM instances WHERE lower(COALESCE(health_status, 'ok')) != 'ok'"
            )
            if row[0]
        }
    if not bad_hosts:
        return {"removed": 0, "remaining": 0}
    placeholders = ",".join("?" for _ in bad_hosts)
    params = sorted(bad_hosts)
    with sqlite3.connect(staging_db) as conn:
        removed = 0
        for table in ("videos", "channels", "instances"):
            cur = conn.execute(f"DELETE FROM {table} WHERE lower(host) IN ({placeholders})", params)
            removed += cur.rowcount
        remaining = conn.execute("SELECT COUNT(*) FROM instances").fetchone()[0]
        conn.commit()
    logging.info("staging local non-ok prune removed=%d remaining_instances=%d", removed, remaining)
    return {"removed": int(removed), "remaining": int(remaining)}


def inject_replace_embedding_for_test(*, prod_db: Path, staging_db: Path) -> None:
    """Inject one staging embedding overlap to preserve the existing test hook."""

    with sqlite3.connect(prod_db) as prod, sqlite3.connect(staging_db) as staging:
        prod_has = prod.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='video_embeddings'"
        ).fetchone()[0]
        staging_has = staging.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='video_embeddings'"
        ).fetchone()[0]
        if not prod_has or not staging_has:
            logging.info("test embedding injection skipped: video_embeddings table missing")
            return
        row = prod.execute("SELECT * FROM video_embeddings LIMIT 1").fetchone()
        if row is None:
            logging.info("test embedding injection skipped: no prod embedding row")
            return
        cols = [info[1] for info in prod.execute("PRAGMA table_info(video_embeddings)")]
        placeholders = ", ".join("?" for _ in cols)
        col_sql = ", ".join(f'"{col}"' for col in cols)
        staging.execute(
            f"INSERT OR REPLACE INTO video_embeddings ({col_sql}) VALUES ({placeholders})",
            row,
        )
        staging.commit()
        logging.info("test embedding injection inserted overlapping video_embeddings row")
