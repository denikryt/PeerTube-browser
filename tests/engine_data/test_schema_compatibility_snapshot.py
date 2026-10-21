"""Snapshot the crawler SQL schema columns consumed by Engine read paths."""
from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"


def _load_schema() -> sqlite3.Connection:
    """Apply crawler schema.sql to a temporary database for compatibility checks."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text())
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return column names for one table in the applied schema."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_crawler_schema_creates_tables_used_by_engine_data_paths() -> None:
    """Crawler schema must keep the core tables Engine modules expect to read."""
    conn = _load_schema()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert {"instances", "channels", "videos", "instance_crawl_progress", "channel_crawl_progress", "video_crawl_progress"}.issubset(tables)


def test_videos_table_keeps_identity_metadata_ranking_and_filter_columns() -> None:
    """Video columns form the contract between crawler output and Engine reads."""
    conn = _load_schema()

    assert {
        "video_id",
        "video_uuid",
        "video_numeric_id",
        "instance_domain",
        "channel_id",
        "channel_name",
        "channel_url",
        "account_name",
        "account_url",
        "title",
        "description",
        "tags_json",
        "category",
        "published_at",
        "video_url",
        "duration",
        "thumbnail_url",
        "embed_path",
        "views",
        "likes",
        "dislikes",
        "comments_count",
        "nsfw",
        "preview_path",
        "last_checked_at",
        "error_count",
    }.issubset(_columns(conn, "videos"))


def test_channels_and_progress_tables_keep_engine_relevant_columns() -> None:
    """Channel display metadata and crawl progress columns should not drift silently."""
    conn = _load_schema()

    assert {"channel_id", "instance_domain", "display_name", "avatar_url", "followers_count", "videos_count"}.issubset(_columns(conn, "channels"))
    assert {"host", "status", "error_count", "last_start", "updated_at"}.issubset(_columns(conn, "instance_crawl_progress"))
    assert {"instance_domain", "channel_id", "status", "last_error", "updated_at"}.issubset(_columns(conn, "video_crawl_progress"))
