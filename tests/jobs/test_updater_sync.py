"""Characterization tests for updater sync helpers."""

from __future__ import annotations

import json
import sqlite3

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
    monkeypatch.setattr(sync, "ensure_moderation_schema", lambda conn: None)
    monkeypatch.setattr(sync, "purge_host_data", lambda conn, host, dry_run: {"videos": 1})
    monkeypatch.setattr(sync, "purge_similarity_for_host", lambda conn, host, dry_run: {"rows": 2})
    assert sync.purge_hosts(prod_db=prod, similarity_db=sim, hosts={"a", "b"}, dry_run=True) == {
        "videos": 2,
        "similarity_rows": 4,
    }
