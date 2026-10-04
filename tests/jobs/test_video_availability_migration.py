"""Availability cleanup preserves history and owns no transaction."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.server.db.jobs import whitelist_migrations

ROOT = Path(__file__).resolve().parents[2]


def _migration_module():
    """Load the real in-place migration command without invoking its CLI."""
    spec = importlib.util.spec_from_file_location(
        "video_availability_migrate", ROOT / "engine/server/db/jobs/migrate-whitelist.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(conn):
    """Seed live, transient, canonical, unknown, and anomalous historical rows."""
    conn.execute("""CREATE TABLE videos(
        video_id TEXT PRIMARY KEY, invalid_reason TEXT, invalid_at INTEGER,
        error_count INTEGER, last_error TEXT, last_error_at INTEGER, title TEXT)""")
    reasons = [
        None,
        "timeout",
        "tls_error",
        "cert_expired",
        "not_found",
        "gone",
        "legacy_unknown",
        "",
        " ",
        "TIMEOUT",
    ]
    conn.executemany(
        "INSERT INTO videos VALUES(?,?,?,?,?,?,?)",
        [
            (str(i), reason, 100 + i, 10 + i, "diagnostic", 200 + i, "title")
            for i, reason in enumerate(reasons)
        ],
    )
    conn.commit()


def test_normalization_is_narrow_idempotent_and_preserves_diagnostics():
    """Only the exact three transient reasons and their timestamps are cleared."""
    with sqlite3.connect(":memory:") as conn:
        _source(conn)
        before = conn.execute("SELECT * FROM videos ORDER BY video_id").fetchall()
        report = whitelist_migrations.normalize_video_availability_semantics(conn)
        assert report["rows_changed"] == 3
        assert report["transient_counts"] == {"timeout": 1, "tls_error": 1, "cert_expired": 1}
        assert report["canonical_counts"] == {"not_found": 1, "gone": 1}
        assert report["unknown_counts"] == {"legacy_unknown": 1, "": 1, " ": 1, "TIMEOUT": 1}
        after = conn.execute("SELECT * FROM videos ORDER BY video_id").fetchall()
        for old, new in zip(before, after, strict=True):
            if old[1] in ("timeout", "tls_error", "cert_expired"):
                assert new == (old[0], None, None, *old[3:])
            else:
                assert new == old
        assert (
            whitelist_migrations.normalize_video_availability_semantics(conn)["rows_changed"] == 0
        )
        assert conn.execute("SELECT * FROM videos ORDER BY video_id").fetchall() == after


def test_normalization_does_not_commit_caller_transaction():
    """A caller rollback restores cleaned availability together with other writes."""
    with sqlite3.connect(":memory:") as conn:
        _source(conn)
        conn.execute("BEGIN IMMEDIATE")
        whitelist_migrations.normalize_video_availability_semantics(conn)
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute(
            "SELECT invalid_reason,invalid_at FROM videos WHERE video_id='1'"
        ).fetchone() == ("timeout", 101)


@pytest.mark.parametrize("fail", [False, True])
def test_command_cleanup_and_prepared_invalidation_commit_together(monkeypatch, tmp_path, fail):
    """After schema completion, readiness and cleanup commit or roll back together."""
    mod = _migration_module()
    path = tmp_path / "whitelist.db"
    with sqlite3.connect(path) as conn:
        _source(conn)
        conn.execute("CREATE TABLE video_facets_snapshot(snapshot_id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO video_facets_snapshot VALUES(1)")
    monkeypatch.setattr(mod, "parse_args", lambda: SimpleNamespace(whitelist_db=path, backup=False))
    # Schema is an independently completed phase; test the command's data transaction.
    monkeypatch.setattr(
        mod, "migrate_whitelist_schema", lambda conn, table: conn.executescript("SELECT 1;")
    )
    real_invalidate = mod.invalidate_prepared_discovery

    def invalidate(conn):
        """Fail after actual invalidation to prove rollback protects both effects."""
        real_invalidate(conn)
        if fail:
            raise RuntimeError("injected invalidation failure")

    monkeypatch.setattr(mod, "invalidate_prepared_discovery", invalidate)
    if fail:
        with pytest.raises(RuntimeError, match="injected"):
            mod.main()
    else:
        mod.main()
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT invalid_reason,invalid_at FROM videos WHERE video_id='1'"
        ).fetchone() == (("timeout", 101) if fail else (None, None))
        assert conn.execute("SELECT COUNT(*) FROM video_facets_snapshot").fetchone()[0] == int(fail)


def test_zero_change_migration_preserves_readiness(monkeypatch, tmp_path):
    """No cleanup change does not delete readiness; version validation handles v1."""
    mod = _migration_module()
    path = tmp_path / "unchanged.db"
    with sqlite3.connect(path) as conn:
        _source(conn)
        conn.execute(
            "DELETE FROM videos WHERE invalid_reason IN ('timeout','tls_error','cert_expired')"
        )
        conn.execute("CREATE TABLE video_facets_snapshot(snapshot_id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO video_facets_snapshot VALUES(1)")
    monkeypatch.setattr(mod, "parse_args", lambda: SimpleNamespace(whitelist_db=path, backup=False))
    monkeypatch.setattr(
        mod, "migrate_whitelist_schema", lambda conn, table: conn.executescript("SELECT 1;")
    )
    mod.main()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM video_facets_snapshot").fetchone()[0] == 1


def test_real_schema_migration_backup_and_repeat_cleanup(monkeypatch, tmp_path, caplog):
    """The real migration CLI phase preserves a backup, reports unknowns, and is repeatable."""
    import json
    import logging

    mod = _migration_module()
    path = tmp_path / "real.db"
    with sqlite3.connect(path) as conn:
        conn.executescript((ROOT / "engine/crawler/schema.sql").read_text())
        for reason in ["timeout", "tls_error", "cert_expired", "not_found", "gone", "", "unknown"]:
            conn.execute(
                """INSERT INTO videos(video_id,instance_domain,last_checked_at,
                invalid_reason,invalid_at,error_count,last_error)
                VALUES(?,'example.org',1,?,123,7,'history')""",
                (str(reason), reason),
            )
    args = SimpleNamespace(whitelist_db=path, backup=True)
    monkeypatch.setattr(mod, "parse_args", lambda: args)
    caplog.set_level(logging.INFO)
    mod.main()
    backups = list(tmp_path.glob("real.db.bak-*"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert (
            backup.execute("SELECT invalid_reason FROM videos WHERE video_id='timeout'").fetchone()[
                0
            ]
            == "timeout"
        )
    reports = [
        json.loads(r.message.split(": ", 1)[1])
        for r in caplog.records
        if r.message.startswith("Availability normalization: ")
    ]
    assert reports[-1]["rows_changed"] == 3
    assert reports[-1]["unknown_counts"] == {"": 1, "unknown": 1}
    args.backup = False
    mod.main()
    reports = [
        json.loads(r.message.split(": ", 1)[1])
        for r in caplog.records
        if r.message.startswith("Availability normalization: ")
    ]
    assert reports[-1]["rows_changed"] == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT invalid_reason,invalid_at,error_count,last_error "
            "FROM videos WHERE video_id='timeout'"
        ).fetchone() == (None, None, 7, "history")
