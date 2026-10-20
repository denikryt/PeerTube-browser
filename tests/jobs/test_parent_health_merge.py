"""Parent health publication is scoped, validated and atomic across table merges."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from engine.server.db.jobs.updater.staging import init_staging_db

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "engine/crawler/schema.sql"
MERGER = ROOT / "engine/server/db/jobs/merge-staging-db.py"
RULES = ROOT / "engine/server/db/jobs/merge_rules.json"


@pytest.fixture
def databases(tmp_path):
    """Create canonical and valid updater-owned staging databases."""
    production, staging = tmp_path / "production.db", tmp_path / "stage.db"
    with sqlite3.connect(production) as conn:
        conn.executescript(SCHEMA.read_text(encoding="utf8"))
        conn.execute("CREATE TABLE video_facets_snapshot(snapshot_id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO video_facets_snapshot VALUES (1)")
    init_staging_db(staging, SCHEMA)
    for path in (production, staging):
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE video_embeddings(video_id TEXT NOT NULL, "
                "instance_domain TEXT NOT NULL, embedding BLOB, "
                "PRIMARY KEY(video_id, instance_domain))"
            )
    return production, staging


def merge(databases, hosts_file=None):
    """Execute the actual CLI and return its status for observable assertions."""
    production, staging = databases
    command = [sys.executable, str(MERGER), "--prod-db", str(production),
               "--staging-db", str(staging), "--rules", str(RULES)]
    if hosts_file is not None:
        command.extend(["--parent-health-hosts-file", str(hosts_file)])
    return subprocess.run(command, capture_output=True, text=True, check=False)


def state(production):
    """Read committed parent rows and discovery readiness after the merger."""
    with sqlite3.connect(production) as conn:
        return (
            conn.execute("SELECT host,health_status,health_checked_at,health_error FROM instances ORDER BY host").fetchall(),
            conn.execute("SELECT channel_id,instance_domain,display_name,health_status,health_checked_at,health_error FROM channels ORDER BY instance_domain").fetchall(),
            conn.execute("SELECT snapshot_id FROM video_facets_snapshot").fetchall(),
        )


def scope_file(tmp_path, hosts):
    """Represent exact frozen host selection, including the empty set."""
    path = tmp_path / "scope.txt"
    path.write_text("\n".join(hosts), encoding="utf8")
    return path


def insert_parents(databases, host, status, time=1700000000000, error=None, *, into="staging"):
    """Save matching instance and channel observations into the specified DB."""
    with sqlite3.connect(databases[1 if into == "staging" else 0]) as conn:
        conn.execute("INSERT INTO instances(host,health_status,health_checked_at,health_error) VALUES(?,?,?,?)", (host, status, time, error))
        conn.execute("INSERT INTO channels(channel_id,instance_domain,display_name,health_status,health_checked_at,health_error) VALUES(?,?,?,?,?,?)", ("channel", host, "metadata from " + into, status, time, error))


def test_new_and_existing_parent_health_are_published_by_one_scoped_path(databases, tmp_path):
    """A selected new error and existing successful parent publish without metadata replacement."""
    insert_parents(databases, "existing.org", "error", error="old", into="production")
    insert_parents(databases, "existing.org", "ok")
    insert_parents(databases, "new.org", "error", error="remote refused")
    insert_parents(databases, "unselected.org", "error", error="old staging")
    result = merge(databases, scope_file(tmp_path, ["existing.org", "new.org"]))
    assert result.returncode == 0, result.stderr
    instances, channels, marker = state(databases[0])
    assert [r[1] for r in instances] == ["ok", "error", None]
    assert [r[3] for r in channels] == ["ok", "error", None]
    assert channels[0][2] == "metadata from production"
    assert channels[1][2] == "metadata from staging"
    assert marker == []  # Both error->ok and NULL->error alter serving visibility.


def test_omitted_and_empty_scope_never_publish_stale_health(databases, tmp_path):
    """New metadata is imported without treating staging health as run evidence."""
    insert_parents(databases, "stale.org", "error", error="copied from previous run")
    assert merge(databases).returncode == 0
    assert state(databases[0])[0] == [("stale.org", None, None, None)]
    with sqlite3.connect(databases[0]) as conn:
        conn.execute("UPDATE instances SET health_status='ok',health_checked_at=1 WHERE host='stale.org'")
    assert merge(databases, scope_file(tmp_path, [])).returncode == 0
    assert state(databases[0])[0] == [("stale.org", "ok", 1, None)]
    assert state(databases[0])[2] == [(1,)]


@pytest.mark.parametrize("status,time,error", [("error", None, "failed"), ("ok", 123, "unexpected"), ("error", 123, ""), ("bad", 123, None), (None, 123, None)])
def test_malformed_scoped_health_aborts_before_any_production_insert(databases, tmp_path, status, time, error):
    """A partial or contradictory trio fails closed without touching production."""
    insert_parents(databases, "bad.org", status, time, error)
    result = merge(databases, scope_file(tmp_path, ["bad.org"]))
    assert result.returncode != 0
    assert state(databases[0]) == ([], [], [(1,)])


def test_large_json_scope_can_publish_without_sql_bind_count_limit(databases, tmp_path):
    """More than 999 selected hosts update both parent tables correctly."""
    hosts = [f"host-{i:04d}.org" for i in range(1024)]
    with sqlite3.connect(databases[1]) as conn:
        conn.executemany("INSERT INTO instances(host,health_status,health_checked_at) VALUES(?,'ok',1234567890000)", [(host,) for host in hosts])
        conn.executemany("INSERT INTO channels(channel_id,instance_domain,health_status,health_checked_at) VALUES('c',?,'ok',1234567890000)", [(host,) for host in hosts])
    result = merge(databases, scope_file(tmp_path, hosts))
    assert result.returncode == 0, result.stderr
    assert len(state(databases[0])[0]) == 1024
    assert all(row[1] == "ok" for row in state(databases[0])[0])


def test_invalid_scope_file_fails_closed(databases, tmp_path):
    """A missing file or malformed identity cannot broaden publication or merge data."""
    insert_parents(databases, "valid.org", "ok")
    missing = merge(databases, tmp_path / "does-not-exist")
    assert missing.returncode != 0
    malformed = merge(databases, scope_file(tmp_path, ["https://valid.org"]))
    assert malformed.returncode != 0
    assert state(databases[0]) == ([], [], [(1,)])


def test_parent_health_and_prepared_marker_roll_back_after_later_merge_failure(databases, tmp_path):
    """A failure in a later merge rule undoes the health and marker transitions."""
    insert_parents(databases, "fresh.org", "error", error="remote failed")
    with sqlite3.connect(databases[0]) as conn:
        conn.execute("CREATE TRIGGER refuse_embedding BEFORE INSERT ON video_embeddings BEGIN SELECT RAISE(ABORT,'blocked embedding'); END")
    with sqlite3.connect(databases[1]) as conn:
        conn.execute("INSERT INTO video_embeddings(video_id,instance_domain,embedding) VALUES('v','fresh.org',x'00')")
    result = merge(databases, scope_file(tmp_path, ["fresh.org"]))
    assert result.returncode != 0 and "blocked embedding" in result.stderr
    assert state(databases[0]) == ([], [], [(1,)])


def test_healthy_parent_never_invalidates_prepared_snapshot(databases, tmp_path):
    """NULL->ok is a health refresh, not a change in error suppression."""
    insert_parents(databases, "fresh.org", "ok")
    result = merge(databases, scope_file(tmp_path, ["fresh.org"]))
    assert result.returncode == 0, result.stderr
    assert state(databases[0])[2] == [(1,)]


def test_selected_unobserved_parent_does_not_replace_existing_health(databases, tmp_path):
    """A selected parent with no observation keeps its committed error state."""
    insert_parents(databases, "retained.org", "error", error="previous error", into="production")
    with sqlite3.connect(databases[1]) as conn:
        conn.execute("INSERT INTO instances(host) VALUES('retained.org')")
        conn.execute("INSERT INTO channels(channel_id,instance_domain,display_name) VALUES('channel','retained.org','staged')")
    result = merge(databases, scope_file(tmp_path, ["retained.org"]))
    assert result.returncode == 0, result.stderr
    instances, channels, marker = state(databases[0])
    assert instances[0][1:] == ("error", 1700000000000, "previous error")
    assert channels[0][3:] == ("error", 1700000000000, "previous error")
    assert marker == [(1,)]  # No status transition was actually published.


def test_production_parent_outside_scope_keeps_health_while_other_parent_updates(databases, tmp_path):
    """A different selected host does not refresh any previously committed parent."""
    insert_parents(databases, "excluded.org", "error", error="old", into="production")
    insert_parents(databases, "excluded.org", "ok", time=1700000001000)
    insert_parents(databases, "selected.org", "ok")
    result = merge(databases, scope_file(tmp_path, ["selected.org"]))
    assert result.returncode == 0, result.stderr
    instances, channels, marker = state(databases[0])
    assert instances[0][1:] == ("error", 1700000000000, "old")
    assert channels[0][3:] == ("error", 1700000000000, "old")
    assert instances[1][1] == "ok" and channels[1][3] == "ok"
    assert marker == [(1,)]
