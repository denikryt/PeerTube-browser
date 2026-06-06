"""Characterization tests for updater sync helpers."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from engine.server.db.jobs.updater import sync


class _Response:
    """Tiny urlopen response fake used by sync fetch tests."""

    def __init__(self, payload) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_fetch_join_hosts_accepts_data_and_list_shapes(monkeypatch) -> None:
    """JoinPeerTube payload parsing preserves existing accepted shapes."""

    monkeypatch.setattr(
        sync,
        "urlopen",
        lambda request, timeout: _Response({"data": [{"host": " A.EX "}, {"domain": "b.ex"}]}),
    )
    assert sync.fetch_join_hosts("https://example.test") == {"a.ex", "b.ex"}
    monkeypatch.setattr(
        sync, "urlopen", lambda request, timeout: _Response([" C.EX ", {"name": "d.ex"}, ""])
    )
    assert sync.fetch_join_hosts("https://example.test") == {"c.ex", "d.ex"}


def test_list_prod_hosts_and_write_hosts_file(tmp_path) -> None:
    """Host listing and temp-file writing normalize and sort hosts."""

    db = tmp_path / "prod.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE instances(host TEXT)")
        conn.executemany("INSERT INTO instances(host) VALUES (?)", [(" A.EX ",), ("b.ex",), ("",)])
        conn.commit()
    assert sync.list_prod_hosts(db) == {"a.ex", "b.ex"}
    assert sync.write_hosts_file(set(), "x-") is None
    path = sync.write_hosts_file({"b.ex", "a.ex"}, "hosts-")
    assert path is not None
    assert path.read_text(encoding="utf-8") == "a.ex\nb.ex\n"


def test_purge_hosts_aggregates_results(monkeypatch, tmp_path) -> None:
    """Purge helper aggregates prod and similarity purge counts per host."""

    prod = tmp_path / "prod.db"
    sim = tmp_path / "sim.db"
    sqlite3.connect(prod).close()
    sqlite3.connect(sim).close()
    monkeypatch.setattr(sync, "bootstrap_engine_moderation_db", lambda conn: None)
    monkeypatch.setattr(sync, "purge_host_data", lambda conn, host, dry_run: {"videos": 1})
    monkeypatch.setattr(sync, "purge_similarity_for_host", lambda conn, host, dry_run: {"rows": 2})
    assert sync.purge_hosts(prod_db=prod, similarity_db=sim, hosts={"a", "b"}, dry_run=True) == {
        "videos": 2,
        "similarity_rows": 4,
    }


def test_load_denied_hosts_reads_named_rows_from_plain_sqlite_connection(tmp_path) -> None:
    """Updater denylist loading works with the connection it opens itself."""

    db = tmp_path / "prod.db"
    with sqlite3.connect(db) as conn:
        sync.bootstrap_engine_moderation_db(conn)
        conn.execute(
            """
            INSERT INTO instance_denylist(host, reason, note, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            ("Blocked.EX", "test", "test", 1, 1),
        )
        conn.execute(
            """
            INSERT INTO instance_denylist(host, reason, note, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?)
            """,
            ("inactive.ex", "test", "test", 1, 1),
        )
        conn.commit()

    assert sync.load_denied_hosts(db) == {"blocked.ex"}


def test_purge_hosts_from_staging_uses_real_crawler_schema(tmp_path) -> None:
    """Denylisted hosts are removed through the real crawler schema columns."""

    db = tmp_path / "staging.db"
    schema_path = Path(__file__).resolve().parents[2] / "engine" / "crawler" / "schema.sql"
    with sqlite3.connect(db) as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO instances(host) VALUES (?)", ("blocked.example",))
        conn.execute(
            """
            INSERT INTO channels(channel_id, channel_name, instance_domain)
            VALUES (?, ?, ?)
            """,
            ("channel-1", "Blocked channel", "blocked.example"),
        )
        conn.execute(
            """
            INSERT INTO videos(video_id, video_uuid, instance_domain, last_checked_at)
            VALUES (?, ?, ?, ?)
            """,
            ("video-1", "uuid-1", "blocked.example", 1),
        )
        conn.execute(
            """
            INSERT INTO instance_crawl_progress(host, status, updated_at)
            VALUES (?, ?, ?)
            """,
            ("blocked.example", "done", 1),
        )
        conn.execute(
            """
            INSERT INTO channel_crawl_progress(instance_domain, status, updated_at)
            VALUES (?, ?, ?)
            """,
            ("blocked.example", "done", 1),
        )
        conn.execute(
            """
            INSERT INTO video_crawl_progress(
                instance_domain, channel_id, status, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            ("blocked.example", "channel-1", "done", 1),
        )
        conn.commit()

    result = sync.purge_hosts_from_staging(db, {"BLOCKED.EXAMPLE"})

    assert result == {
        "videos": 1,
        "channels": 1,
        "instances": 1,
        "video_crawl_progress": 1,
        "channel_crawl_progress": 1,
        "instance_crawl_progress": 1,
    }
    with sqlite3.connect(db) as conn:
        for table in (
            "videos",
            "channels",
            "instances",
            "video_crawl_progress",
            "channel_crawl_progress",
            "instance_crawl_progress",
        ):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
