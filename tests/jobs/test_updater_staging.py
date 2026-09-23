"""Characterization tests for updater staging database helpers."""

from __future__ import annotations

import sqlite3

from engine.server.db.jobs.updater.staging import (
    count_staging_deltas,
    init_staging_db,
    prune_staging_local_non_ok_instances,
    remove_db_with_sidecars,
    seed_staging_from_prod,
)


def _create_minimal_db(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE instances(id INTEGER PRIMARY KEY, host TEXT UNIQUE, health_status TEXT);
            CREATE TABLE channels(id INTEGER PRIMARY KEY, host TEXT, name TEXT);
            CREATE TABLE videos(id INTEGER PRIMARY KEY, host TEXT, uuid TEXT);
            CREATE TABLE video_embeddings(video_id INTEGER PRIMARY KEY, embedding BLOB);
            """
        )
        conn.commit()


def _create_current_identity_db(path) -> None:
    """Create a DB that matches the current prod/staging identity columns."""

    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE instances(host TEXT PRIMARY KEY, health_status TEXT);
            CREATE TABLE channels(
              channel_id TEXT NOT NULL,
              channel_name TEXT,
              instance_domain TEXT NOT NULL,
              PRIMARY KEY(channel_id, instance_domain)
            );
            CREATE TABLE videos(
              video_id TEXT NOT NULL,
              video_uuid TEXT,
              instance_domain TEXT NOT NULL,
              PRIMARY KEY(video_id, instance_domain)
            );
            CREATE TABLE video_embeddings(video_id TEXT PRIMARY KEY, embedding BLOB);
            """
        )
        conn.commit()


def test_remove_db_with_sidecars_removes_all_files(tmp_path) -> None:
    """SQLite DB sidecars are deleted with the main DB."""

    db = tmp_path / "staging.db"
    for suffix in ("", "-wal", "-shm"):
        (tmp_path / f"staging.db{suffix}").write_text("x", encoding="utf-8")
    remove_db_with_sidecars(db)
    assert not any((tmp_path / f"staging.db{suffix}").exists() for suffix in ("", "-wal", "-shm"))


def test_init_staging_db_executes_schema_and_creates_crawl_state(tmp_path) -> None:
    """Staging initialization uses supplied schema and adds crawl_state."""

    schema = tmp_path / "schema.sql"
    schema.write_text("CREATE TABLE instances(host TEXT);", encoding="utf-8")
    db = tmp_path / "staging.db"
    init_staging_db(db, schema)
    with sqlite3.connect(db) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"instances", "crawl_state"}.issubset(tables)


def test_seed_staging_from_prod_copies_shared_columns_and_marks_state(tmp_path) -> None:
    """Prod instances/channels are copied with shared columns only."""

    prod = tmp_path / "prod.db"
    staging = tmp_path / "staging.db"
    _create_minimal_db(prod)
    _create_minimal_db(staging)
    with sqlite3.connect(prod) as conn:
        conn.execute("INSERT INTO instances(host, health_status) VALUES ('a.example', 'ok')")
        conn.execute("INSERT INTO channels(host, name) VALUES ('a.example', 'chan')")
        conn.commit()
    with sqlite3.connect(staging) as conn:
        conn.execute("CREATE TABLE crawl_state(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.commit()
    seed_staging_from_prod(prod, staging)
    with sqlite3.connect(staging) as conn:
        assert conn.execute("SELECT COUNT(*) FROM instances").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0] == 1
        keys = {row[0] for row in conn.execute("SELECT key FROM crawl_state")}
    assert {"stage_seeded_at", "stage_seeded_from"}.issubset(keys)


def test_count_staging_deltas_returns_current_keys(tmp_path) -> None:
    """Delta counting returns the current instances/channels/videos/embeddings keys."""

    prod = tmp_path / "prod.db"
    staging = tmp_path / "staging.db"
    _create_minimal_db(prod)
    _create_minimal_db(staging)
    with sqlite3.connect(staging) as conn:
        conn.execute("INSERT INTO instances(host) VALUES ('new.example')")
        conn.execute("INSERT INTO channels(host, name) VALUES ('new.example', 'chan')")
        conn.execute("INSERT INTO videos(host, uuid) VALUES ('new.example', 'uuid')")
        conn.execute("INSERT INTO video_embeddings(video_id, embedding) VALUES (1, x'00')")
        conn.commit()
    assert count_staging_deltas(prod, staging) == {
        "instances_new": 1,
        "channels_new": 1,
        "videos_new": 1,
        "embeddings_new": 1,
    }


def test_count_staging_deltas_supports_current_prod_identity_columns(tmp_path) -> None:
    """Delta counting works with current whitelist/crawler identity columns."""

    prod = tmp_path / "prod-current.db"
    staging = tmp_path / "staging-current.db"
    _create_current_identity_db(prod)
    _create_current_identity_db(staging)
    with sqlite3.connect(prod) as conn:
        conn.execute("INSERT INTO instances(host) VALUES ('old.example')")
        conn.execute(
            "INSERT INTO channels(channel_id, channel_name, instance_domain) VALUES ('old-id', 'old', 'old.example')"
        )
        conn.execute(
            "INSERT INTO videos(video_id, video_uuid, instance_domain) VALUES ('old-video', 'old-uuid', 'old.example')"
        )
        conn.execute("INSERT INTO video_embeddings(video_id, embedding) VALUES ('old-video', x'00')")
        conn.commit()
    with sqlite3.connect(staging) as conn:
        conn.execute("INSERT INTO instances(host) VALUES ('new.example')")
        conn.execute(
            "INSERT INTO channels(channel_id, channel_name, instance_domain) VALUES ('chan-1', 'chan', 'new.example')"
        )
        conn.execute(
            "INSERT INTO videos(video_id, video_uuid, instance_domain) VALUES ('video-1', 'uuid-1', 'new.example')"
        )
        conn.execute("INSERT INTO video_embeddings(video_id, embedding) VALUES ('video-1', x'00')")
        conn.commit()
    assert count_staging_deltas(prod, staging) == {
        "instances_new": 1,
        "channels_new": 1,
        "videos_new": 1,
        "embeddings_new": 1,
    }


def test_count_staging_deltas_uses_composite_embedding_identity(tmp_path) -> None:
    """Same video_id on another host is a distinct embedding in current schema."""

    prod = tmp_path / "prod-composite-embeddings.db"
    staging = tmp_path / "staging-composite-embeddings.db"
    schema = """
        CREATE TABLE instances(host TEXT PRIMARY KEY);
        CREATE TABLE channels(
          channel_id TEXT NOT NULL, instance_domain TEXT NOT NULL,
          PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE videos(
          video_id TEXT NOT NULL, video_uuid TEXT, instance_domain TEXT NOT NULL,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE video_embeddings(
          video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB,
          PRIMARY KEY(video_id, instance_domain)
        );
    """
    for path in (prod, staging):
        with sqlite3.connect(path) as conn:
            conn.executescript(schema)
            conn.commit()
    with sqlite3.connect(prod) as conn:
        conn.execute("INSERT INTO instances VALUES ('one.example')")
        conn.execute("INSERT INTO videos VALUES ('same-video', 'uuid-one', 'one.example')")
        conn.execute("INSERT INTO video_embeddings VALUES ('same-video', 'one.example', x'00')")
        conn.commit()
    with sqlite3.connect(staging) as conn:
        conn.execute("INSERT INTO instances VALUES ('two.example')")
        conn.execute("INSERT INTO videos VALUES ('same-video', 'uuid-two', 'two.example')")
        conn.execute("INSERT INTO video_embeddings VALUES ('same-video', 'two.example', x'01')")
        conn.commit()

    assert count_staging_deltas(prod, staging) == {
        "instances_new": 1,
        "channels_new": 0,
        "videos_new": 1,
        "embeddings_new": 1,
    }


def test_count_staging_deltas_can_scope_to_target_hosts(tmp_path) -> None:
    """Host-scoped updater runs count deltas only for the targeted instances."""

    prod = tmp_path / "prod-scoped.db"
    staging = tmp_path / "staging-scoped.db"
    _create_current_identity_db(prod)
    _create_current_identity_db(staging)
    with sqlite3.connect(staging) as conn:
        conn.execute("INSERT INTO instances(host) VALUES ('target.example')")
        conn.execute("INSERT INTO instances(host) VALUES ('other.example')")
        conn.execute(
            "INSERT INTO channels(channel_id, channel_name, instance_domain) VALUES ('chan-1', 'chan', 'target.example')"
        )
        conn.execute(
            "INSERT INTO channels(channel_id, channel_name, instance_domain) VALUES ('chan-2', 'chan', 'other.example')"
        )
        conn.execute(
            "INSERT INTO videos(video_id, video_uuid, instance_domain) VALUES ('video-1', 'uuid-1', 'target.example')"
        )
        conn.execute(
            "INSERT INTO videos(video_id, video_uuid, instance_domain) VALUES ('video-2', 'uuid-2', 'other.example')"
        )
        conn.execute("INSERT INTO video_embeddings(video_id, embedding) VALUES ('video-1', x'00')")
        conn.execute("INSERT INTO video_embeddings(video_id, embedding) VALUES ('video-2', x'00')")
        conn.commit()
    assert count_staging_deltas(prod, staging, scoped_hosts={"target.example"}) == {
        "instances_new": 1,
        "channels_new": 1,
        "videos_new": 1,
        "embeddings_new": 1,
    }




def test_prune_staging_local_non_ok_instances_supports_current_schema(tmp_path) -> None:
    """Current crawler schema uses instance_domain for channel/video host identity."""

    prod = tmp_path / "prod-current-prune.db"
    staging = tmp_path / "staging-current-prune.db"
    _create_current_identity_db(prod)
    _create_current_identity_db(staging)
    with sqlite3.connect(prod) as conn:
        conn.execute("INSERT INTO instances(host, health_status) VALUES ('bad.example', 'dead')")
        conn.commit()
    with sqlite3.connect(staging) as conn:
        conn.execute("INSERT INTO instances(host) VALUES ('bad.example')")
        conn.execute(
            "INSERT INTO channels(channel_id, channel_name, instance_domain) VALUES ('chan', 'chan', 'bad.example')"
        )
        conn.execute(
            "INSERT INTO videos(video_id, video_uuid, instance_domain) VALUES ('video', 'uuid', 'bad.example')"
        )
        conn.commit()

    result = prune_staging_local_non_ok_instances(prod_db=prod, staging_db=staging)

    assert result == {"removed": 3, "remaining": 0}

def test_prune_staging_local_non_ok_instances_removes_bad_hosts(tmp_path) -> None:
    """Local non-ok prod instances are pruned from staging tables."""

    prod = tmp_path / "prod.db"
    staging = tmp_path / "staging.db"
    _create_minimal_db(prod)
    _create_minimal_db(staging)
    with sqlite3.connect(prod) as conn:
        conn.execute("INSERT INTO instances(host, health_status) VALUES ('bad.example', 'dead')")
        conn.commit()
    with sqlite3.connect(staging) as conn:
        conn.execute("INSERT INTO instances(host) VALUES ('bad.example')")
        conn.execute("INSERT INTO channels(host, name) VALUES ('bad.example', 'chan')")
        conn.execute("INSERT INTO videos(host, uuid) VALUES ('bad.example', 'uuid')")
        conn.commit()
    result = prune_staging_local_non_ok_instances(prod_db=prod, staging_db=staging)
    assert result == {"removed": 3, "remaining": 0}
