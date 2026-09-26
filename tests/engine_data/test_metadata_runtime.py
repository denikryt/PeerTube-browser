"""Canonical runtime metadata projection regression tests."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from engine.server.data.metadata import fetch_metadata, fetch_metadata_by_ids, fetch_metadata_by_index_ids
from engine.server.db.migrations.apply import apply_video_index_ids_migration


def _db() -> sqlite3.Connection:
    """Create one canonical video reachable by all metadata identity paths."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE channels (
          channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT,
          PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE videos (
          video_id TEXT, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT,
          channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT,
          title TEXT, description TEXT, tags_json TEXT, category TEXT, category_id TEXT,
          language TEXT, language_label TEXT, published_at INTEGER, video_url TEXT, duration INTEGER,
          thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER,
          comments_count INTEGER, nsfw INTEGER, preview_path TEXT, last_checked_at INTEGER,
          error_count INTEGER DEFAULT 0, PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_embeddings (
          video_id TEXT, instance_domain TEXT, embedding_dim INTEGER, model_name TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        """
    )
    apply_video_index_ids_migration(conn)
    conn.execute("INSERT INTO channels VALUES ('c1', 'example.org', 'Channel', '/a.jpg')")
    conn.execute(
        """
        INSERT INTO videos VALUES (
          'v1','uuid-v1',1,'example.org','c1','channel','https://example.org/c','acct','https://example.org/a',
          'Title','Desc','[""Linux""]','Education','13','uk','Ukrainian',1000,
          'https://example.org/w/v1',60,'/t.jpg','/embed',10,2,0,0,0,'/p.jpg',1000,0
        )
        """.replace('[""Linux""]', '["Linux"]')
    )
    conn.execute("INSERT INTO video_embeddings VALUES ('v1','example.org',3,'test')")
    conn.execute(
        "INSERT INTO video_index_ids(index_id, video_id, instance_domain, is_active, created_at, updated_at) VALUES (7,'v1','example.org',1,1,1)"
    )
    return conn


def _assert_new_fields(row: dict[str, object]) -> None:
    """Assert the shared card/filter metadata contract without numeric coercion."""
    assert row["language"] == "uk"
    assert row["language_label"] == "Ukrainian"
    assert row["category"] == "Education"
    assert row["category_id"] == "13"
    assert row["tags_json"] == '["Linux"]'
    assert row["instance_domain"] == "example.org"


def test_all_metadata_fetchers_expose_canonical_filter_fields() -> None:
    """Positive path: rowid, stable-index, and public-id resolution expose identical metadata."""
    conn = _db()
    rowid = int(conn.execute("SELECT rowid FROM video_embeddings").fetchone()[0])
    _assert_new_fields(fetch_metadata(conn, [rowid])[rowid])
    _assert_new_fields(fetch_metadata_by_index_ids(conn, [7])[7])
    _assert_new_fields(fetch_metadata_by_ids(conn, [{"video_id": "v1", "instance_domain": "example.org"}])["v1::example.org"])


def test_metadata_fetchers_do_not_fabricate_unknown_or_numeric_category_id() -> None:
    """Negative path: missing metadata remains null and TEXT ids are never coerced to numbers."""
    conn = _db()
    conn.execute("UPDATE videos SET language=NULL, language_label=NULL, category_id='0013' WHERE video_id='v1'")
    row = fetch_metadata_by_index_ids(conn, [7])[7]
    assert row["language"] is None
    assert row["language_label"] is None
    assert row["category_id"] == "0013"
    assert row["language"] != "_unknown"


def test_metadata_fetchers_return_the_same_canonical_row() -> None:
    """Positive path: every identity lookup returns one canonical metadata value shape."""
    conn = _db()
    rowid = int(conn.execute("SELECT rowid FROM video_embeddings").fetchone()[0])

    by_rowid = fetch_metadata(conn, [rowid])[rowid]
    by_index = fetch_metadata_by_index_ids(conn, [7])[7]
    by_video = fetch_metadata_by_ids(
        conn,
        [{"video_id": "v1", "instance_domain": "example.org"}],
    )["v1::example.org"]

    assert by_rowid == by_index == by_video


def test_metadata_fetchers_do_not_expose_internal_lookup_keys() -> None:
    """Negative path: query-only rowid/index_id keys never become canonical metadata fields."""
    conn = _db()
    rowid = int(conn.execute("SELECT rowid FROM video_embeddings").fetchone()[0])

    assert "rowid" not in fetch_metadata(conn, [rowid])[rowid]
    assert "index_id" not in fetch_metadata_by_index_ids(conn, [7])[7]
