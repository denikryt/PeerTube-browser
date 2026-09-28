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


def test_metadata_v1_columns_are_part_of_crawler_schema_contract() -> None:
    """Crawler current shape exposes every metadata-v1 producer-owned column."""
    conn = _load_schema()

    assert {
        "metadata_version",
        "language",
        "language_label",
        "category_id",
        "licence_id",
        "licence",
        "sensitive_summary",
        "originally_published_at",
        "updated_at",
        "is_live",
        "permanent_live",
        "live_save_replay",
        "aspect_ratio",
        "support",
        "account_username",
        "account_avatar_url",
        "thumbnail_width",
        "thumbnail_height",
    }.issubset(_columns(conn, "videos"))
    assert {
        "owner_account_username",
        "owner_account_display_name",
        "owner_account_url",
        "owner_account_avatar_url",
    }.issubset(_columns(conn, "channels"))


def test_whitelist_metadata_migration_is_additive_and_preserves_derived_data() -> None:
    """Metadata-v1 migration keeps production-only fields, embeddings, and stable IDs."""
    from engine.server.db.jobs.whitelist_migrations import migrate_whitelist_schema

    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE instances (
          host TEXT PRIMARY KEY, health_status TEXT, health_checked_at INTEGER,
          health_error TEXT, last_error TEXT, last_error_at INTEGER, last_error_source TEXT
        );
        CREATE TABLE channels (
          channel_id TEXT NOT NULL, channel_name TEXT, channel_url TEXT, display_name TEXT,
          instance_domain TEXT NOT NULL, videos_count INTEGER, followers_count INTEGER,
          avatar_url TEXT, health_status TEXT, health_checked_at INTEGER, health_error TEXT,
          last_error TEXT, last_error_at INTEGER, last_error_source TEXT,
          PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE videos (
          video_id TEXT NOT NULL, video_uuid TEXT, video_numeric_id INTEGER,
          instance_domain TEXT NOT NULL, channel_id TEXT, channel_name TEXT, channel_url TEXT,
          account_name TEXT, account_url TEXT, title TEXT, description TEXT, tags_json TEXT,
          category TEXT, published_at INTEGER, video_url TEXT, duration INTEGER,
          thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER,
          comments_count INTEGER, nsfw INTEGER, preview_path TEXT,
          popularity REAL NOT NULL DEFAULT 0, last_checked_at INTEGER NOT NULL,
          last_error TEXT, last_error_at INTEGER, error_count INTEGER NOT NULL DEFAULT 0,
          invalid_reason TEXT, invalid_at INTEGER,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_embeddings (
          video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL,
          embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_index_ids (
          index_id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
          UNIQUE(video_id, instance_domain)
        );
        INSERT INTO channels(channel_id, channel_name, instance_domain) VALUES ('c1', 'music', 'h1');
        INSERT INTO videos(video_id, video_uuid, instance_domain, popularity, last_checked_at)
          VALUES ('v1', 'u1', 'h1', 7.5, 1);
        INSERT INTO video_embeddings VALUES ('v1', 'h1', X'0102', 2, 'model', 'now');
        INSERT INTO video_index_ids(index_id, video_id, instance_domain, created_at, updated_at)
          VALUES (77, 'v1', 'h1', 1, 1);
        """
    )

    migrate_whitelist_schema(conn, "instances")
    first_columns = _columns(conn, "videos")
    migrate_whitelist_schema(conn, "instances")

    assert first_columns == _columns(conn, "videos")
    assert conn.execute(
        "SELECT metadata_version, popularity FROM videos WHERE video_id='v1'"
    ).fetchone() == (0, 7.5)
    assert conn.execute(
        "SELECT hex(embedding) FROM video_embeddings WHERE video_id='v1'"
    ).fetchone() == ("0102",)
    assert conn.execute(
        "SELECT index_id FROM video_index_ids WHERE video_id='v1'"
    ).fetchone() == (77,)


def _load_sync_whitelist_module():
    """Load sync-whitelist.py for focused full-sync schema contract tests."""
    import importlib.util

    path = ROOT / "engine/server/db/jobs/sync-whitelist.py"
    spec = importlib.util.spec_from_file_location("sync_whitelist_metadata_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_sync_copies_crawler_metadata_into_production_superset(tmp_path) -> None:
    """Full sync accepts production-only popularity while copying metadata-v1 columns."""
    mod = _load_sync_whitelist_module()
    source = tmp_path / "crawl.db"
    target = tmp_path / "whitelist.db"

    with sqlite3.connect(source) as source_conn:
        source_conn.executescript(SCHEMA.read_text())
        source_conn.executescript(
            """
            CREATE TABLE video_embeddings (
              video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL,
              embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(video_id, instance_domain)
            );
            INSERT INTO instances(host) VALUES ('example.org');
            INSERT INTO channels(
              channel_id, channel_name, display_name, instance_domain,
              owner_account_username, owner_account_url
            ) VALUES ('c1', 'music', 'Music', 'example.org', 'alice',
                      'https://example.org/accounts/alice');
            INSERT INTO videos(
              video_id, video_uuid, instance_domain, channel_id, channel_name,
              title, language, language_label, metadata_version, last_checked_at
            ) VALUES ('v1', 'u1', 'example.org', 'c1', 'Music', 'Song',
                      'en', 'English', 1, 1);
            INSERT INTO video_embeddings
              VALUES ('v1', 'example.org', X'0102', 2, 'model', 'now');
            """
        )
        source_conn.commit()

    with sqlite3.connect(target) as conn:
        mod.ensure_whitelist_schema(conn)
        mod.ensure_content_schema(conn)
        conn.execute("ATTACH DATABASE ? AS source", (source.as_posix(),))
        mod.ensure_schema_compatibility(conn)
        mod.sync_hosts(conn, {"example.org"})
        counts = mod.rebuild_content_tables(conn, {"example.org"})
        conn.commit()

        assert counts == (1, 1, 1)
        columns = _columns(conn, "videos")
        assert {"language", "metadata_version", "popularity"}.issubset(columns)
        assert conn.execute(
            "SELECT language, language_label, metadata_version, popularity "
            "FROM videos WHERE video_id='v1'"
        ).fetchone() == ("en", "English", 1, 0.0)
        assert conn.execute(
            "SELECT owner_account_username, owner_account_url FROM channels WHERE channel_id='c1'"
        ).fetchone() == ("alice", "https://example.org/accounts/alice")


def test_full_sync_content_schema_does_not_create_legacy_popularity_index() -> None:
    """Negative: full-sync schema creation leaves Engine read-index ownership centralized."""
    mod = _load_sync_whitelist_module()
    conn = sqlite3.connect(":memory:")

    mod.ensure_content_schema(conn)

    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_autoindex%'"
        )
    }
    assert "idx_videos_popularity" not in indexes


def _create_full_sync_source(path: Path, *, tag: str = "linux") -> None:
    """Create a production-shaped crawler source DB for full-sync main() tests."""
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA.read_text())
        conn.executescript(
            """
            CREATE TABLE video_embeddings (
              video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL,
              embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(video_id, instance_domain)
            );
            INSERT INTO instances(host) VALUES ('example.org');
            INSERT INTO channels(channel_id, channel_name, display_name, instance_domain)
              VALUES ('c1', 'music', 'Music', 'example.org');
            """
        )
        conn.execute(
            """
            INSERT INTO videos(
              video_id, video_uuid, instance_domain, channel_id, channel_name,
              title, tags_json, language, language_label, category, category_id,
              metadata_version, last_checked_at
            ) VALUES ('v1','u1','example.org','c1','Music','Song',?,
                      'en','English','Education','13',1,1)
            """,
            (f'["{tag}"]',),
        )
        conn.execute(
            "INSERT INTO video_embeddings VALUES ('v1','example.org',X'0102',2,'model','now')"
        )
        conn.commit()


def test_full_sync_main_publishes_read_indexes_and_prepared_discovery(monkeypatch, tmp_path) -> None:
    """Successful full sync returns only after current indexes and prepared Discovery exist."""
    from types import SimpleNamespace

    mod = _load_sync_whitelist_module()
    source = tmp_path / "source-main.db"
    target = tmp_path / "target-main.db"
    _create_full_sync_source(source)
    monkeypatch.setattr(mod, "fetch_hosts", lambda _url: {"example.org"})
    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: SimpleNamespace(
            url="https://unused.example",
            source_db=source,
            whitelist_db=target,
            mode="include",
        ),
    )

    mod.main()

    with sqlite3.connect(target) as conn:
        assert conn.execute(
            "SELECT tag, video_id, instance_domain FROM video_tags"
        ).fetchall() == [("linux", "v1", "example.org")]
        assert conn.execute(
            "SELECT schema_version FROM video_facets_snapshot WHERE snapshot_id=1"
        ).fetchone() == (1,)
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert "idx_videos_fresh_order" in indexes
        assert "idx_videos_trending_order" in indexes
        assert "idx_videos_popularity" not in indexes




def _attached_schema_names(conn: sqlite3.Connection) -> set[str]:
    """Return currently attached SQLite schema names for lifecycle assertions."""
    return {str(row[1]) for row in conn.execute("PRAGMA database_list")}


def test_full_sync_detaches_source_before_main_only_post_build_work(monkeypatch, tmp_path) -> None:
    """Source is attached for canonical replacement but absent before post-build work."""
    from types import SimpleNamespace

    mod = _load_sync_whitelist_module()
    source = tmp_path / "source-lifecycle.db"
    target = tmp_path / "target-lifecycle.db"
    _create_full_sync_source(source)
    monkeypatch.setattr(mod, "fetch_hosts", lambda _url: {"example.org"})
    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: SimpleNamespace(
            url="https://unused.example",
            source_db=source,
            whitelist_db=target,
            mode="include",
        ),
    )

    original_rebuild_content_tables = mod.rebuild_content_tables
    original_bootstrap_read_indexes = mod.bootstrap_engine_read_indexes
    lifecycle: list[tuple[str, set[str]]] = []

    def checked_rebuild_content_tables(conn, selected_hosts):
        """Assert that canonical replacement still has access to the input schema."""
        schemas = _attached_schema_names(conn)
        lifecycle.append(("replacement", schemas))
        assert "source" in schemas
        return original_rebuild_content_tables(conn, selected_hosts)

    def checked_bootstrap_read_indexes(conn):
        """Assert that main-only post-build work cannot address the input schema."""
        schemas = _attached_schema_names(conn)
        lifecycle.append(("post_build", schemas))
        assert "source" not in schemas
        return original_bootstrap_read_indexes(conn)

    monkeypatch.setattr(mod, "rebuild_content_tables", checked_rebuild_content_tables)
    monkeypatch.setattr(mod, "bootstrap_engine_read_indexes", checked_bootstrap_read_indexes)

    mod.main()

    assert lifecycle[0][0] == "replacement"
    assert lifecycle[1][0] == "post_build"


def test_full_sync_does_not_write_planner_statistics_to_source(monkeypatch, tmp_path) -> None:
    """Negative: main-only post-build optimize must not create stats in the input DB."""
    from types import SimpleNamespace

    mod = _load_sync_whitelist_module()
    source = tmp_path / "source-read-only.db"
    target = tmp_path / "target-read-only.db"
    _create_full_sync_source(source)
    with sqlite3.connect(source) as source_conn:
        # Source may be a production-shaped superset, not only a raw crawl DB.
        source_conn.execute("ALTER TABLE videos ADD COLUMN popularity REAL DEFAULT 0")
        source_conn.execute(
            "CREATE INDEX idx_videos_popularity ON videos(popularity DESC)"
        )
        source_conn.commit()
        assert source_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'"
        ).fetchone() is None

    monkeypatch.setattr(mod, "fetch_hosts", lambda _url: {"example.org"})
    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: SimpleNamespace(
            url="https://unused.example",
            source_db=source,
            whitelist_db=target,
            mode="include",
        ),
    )

    mod.main()

    with sqlite3.connect(source) as source_conn:
        assert source_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_videos_popularity'"
        ).fetchone() == (1,)
        assert source_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'"
        ).fetchone() is None


def test_full_sync_rebuild_failure_is_nonzero_and_leaves_snapshot_invalidated(
    monkeypatch, tmp_path
) -> None:
    """A failed post-replacement prepared rebuild cannot leave the previous READY marker."""
    from types import SimpleNamespace

    mod = _load_sync_whitelist_module()
    source = tmp_path / "source-fail.db"
    target = tmp_path / "target-fail.db"
    _create_full_sync_source(source, tag="new")
    with sqlite3.connect(target) as conn:
        mod.ensure_whitelist_schema(conn)
        mod.ensure_content_schema(conn)
        conn.execute(
            """
            CREATE TABLE video_facets_snapshot(
              snapshot_id INTEGER PRIMARY KEY CHECK(snapshot_id=1),
              schema_version INTEGER NOT NULL,
              built_at INTEGER NOT NULL,
              source_video_count INTEGER NOT NULL,
              payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO video_facets_snapshot VALUES(1,1,1,0,'{}')"
        )
        conn.commit()
    monkeypatch.setattr(mod, "fetch_hosts", lambda _url: {"example.org"})
    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: SimpleNamespace(
            url="https://unused.example",
            source_db=source,
            whitelist_db=target,
            mode="include",
        ),
    )
    if hasattr(mod, "rebuild_prepared_discovery"):
        monkeypatch.setattr(
            mod,
            "rebuild_prepared_discovery",
            lambda conn: (_ for _ in ()).throw(RuntimeError("prepared rebuild failed")),
        )

    with __import__("pytest").raises(RuntimeError, match="prepared rebuild failed"):
        mod.main()

    with sqlite3.connect(target) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM video_facets_snapshot"
        ).fetchone()[0] == 0
