"""Real SQLite CLI coverage for the shared canonical merge/availability commit."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from engine.server.db.jobs.updater.staging import init_staging_db, video_availability_report

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "engine/crawler/schema.sql"
MERGER = ROOT / "engine/server/db/jobs/merge-staging-db.py"


@pytest.fixture
def state(tmp_path):
    """Create an ordinary canonical DB and completed updater evidence."""
    prod, staging = tmp_path / "production.db", tmp_path / "staging.db"
    with sqlite3.connect(prod) as conn:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.execute("CREATE TABLE instance_denylist(host TEXT PRIMARY KEY,is_active INTEGER)")
        conn.execute("CREATE TABLE video_facets_snapshot(snapshot_id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO video_facets_snapshot VALUES(1)")
        conn.execute("INSERT INTO videos(video_id,instance_domain,video_uuid,last_checked_at,invalid_reason,invalid_at) VALUES('old','example.org','old-uuid',10,'not_found',100)")
        conn.execute("INSERT INTO instances(host,health_status,health_checked_at,health_error) VALUES('example.org','error',1000,'offline')")
    init_staging_db(staging, SCHEMA)
    with sqlite3.connect(staging) as conn:
        conn.execute("INSERT INTO instances(host,health_status,health_checked_at) VALUES('example.org','ok',2000)")
        conn.execute("INSERT INTO videos(video_id,instance_domain,video_uuid,last_checked_at) VALUES('new','example.org','new-uuid',20)")
        conn.execute("INSERT INTO video_availability_work(video_id,instance_domain,video_uuid,outcome,checked_at) VALUES('old','example.org','old-uuid','available',3000)")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"tables": [
        {"name": "instances", "strategy": "INSERT_ONLY", "keys": ["host"]},
        {"name": "videos", "strategy": "INSERT_ONLY", "keys": ["video_id", "instance_domain"]},
    ]}), encoding="utf-8")
    scope = tmp_path / "scope.txt"
    scope.write_text("example.org\n", encoding="utf-8")
    return prod, staging, rules, scope


def invoke(state, *, apply=True, report_override=None):
    """Exercise the real merger executable instead of an in-process mock."""
    prod, staging, rules, scope = state
    cmd = [sys.executable, str(MERGER), "--prod-db", str(prod),
           "--staging-db", str(staging), "--rules", str(rules),
           "--parent-health-hosts-file", str(scope)]
    if apply:
        report = report_override if report_override is not None else video_availability_report(staging, missing_uuid=0)
        cmd += ["--availability-sweep-report-json", json.dumps(report)]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def snapshot(prod):
    """Read video availability, parent health and Prepared readiness atomically."""
    with sqlite3.connect(prod) as conn:
        return (
            conn.execute("SELECT video_id,invalid_reason,invalid_at FROM videos ORDER BY video_id").fetchall(),
            conn.execute("SELECT host,health_status FROM instances").fetchall(),
            conn.execute("SELECT snapshot_id FROM video_facets_snapshot").fetchall(),
        )


def test_shared_commit_publishes_merge_health_and_available(state):
    """A successful apply publishes all canonical changes in one commit."""
    result = invoke(state)
    assert result.returncode == 0, result.stderr
    videos, health, prepared = snapshot(state[0])
    assert videos == [("new", None, None), ("old", None, None)]
    assert health == [("example.org", "ok")]
    assert prepared == []


def test_conflicting_uuid_rolls_back_merged_video_parent_and_readiness(state):
    """Late evidence rejection must undo preceding INSERT and parent UPDATE."""
    with sqlite3.connect(state[1]) as conn:
        conn.execute("UPDATE video_availability_work SET video_uuid='drift'")
    before = snapshot(state[0])
    result = invoke(state)
    assert result.returncode != 0
    assert "UUID" in result.stderr
    assert snapshot(state[0]) == before


def test_invalid_report_rolls_back_full_merge(state):
    """A report mismatch cannot commit unrelated staged canonical changes."""
    before = snapshot(state[0])
    result = invoke(state, report_override={})
    assert result.returncode != 0
    assert snapshot(state[0]) == before


def test_no_apply_preserves_existing_canonical_availability(state):
    """Normal merge without an availability option retains existing video invalidity."""
    result = invoke(state, apply=False)
    assert result.returncode == 0, result.stderr
    videos, health, prepared = snapshot(state[0])
    assert videos == [("new", None, None), ("old", "not_found", 100)]
    assert health == [("example.org", "ok")]
    assert prepared == []  # New videos invalidate readiness independently.


def test_publisher_core_rejects_missing_transaction(state):
    """A direct in-process caller cannot bypass the single-writer transaction."""
    from engine.server.db.jobs.updater.availability_publish import (
        apply_existing_video_availability_conn,
    )

    with sqlite3.connect(state[0]) as conn:
        conn.execute("ATTACH DATABASE ? AS evidence", (str(state[1]),))
        with pytest.raises(RuntimeError, match="caller-owned transaction"):
            apply_existing_video_availability_conn(
                conn, sweep_report=video_availability_report(state[1], missing_uuid=0)
            )
    assert snapshot(state[0])[0] == [("old", "not_found", 100)]


def test_legacy_available_clears_reason_without_weakening_denylist(state):
    """Historical invalidity is availability; active moderation denial is separate."""
    with sqlite3.connect(state[0]) as conn:
        conn.execute("UPDATE videos SET invalid_reason='legacy_unknown' WHERE video_id='old'")
    result = invoke(state)
    assert result.returncode == 0, result.stderr
    assert snapshot(state[0])[0] == [("new", None, None), ("old", None, None)]

    # A new, equally definitive observation must not override denied identity.
    prod, staging, _, _ = state
    with sqlite3.connect(prod) as conn:
        conn.execute("UPDATE videos SET invalid_reason='legacy_unknown',invalid_at=100 WHERE video_id='old'")
        conn.execute("INSERT INTO instance_denylist VALUES('example.org',1)")
    result = invoke(state)
    assert result.returncode == 0, result.stderr
    assert snapshot(prod)[0][1] == ("old", "legacy_unknown", 100)


def test_sqlite_failure_during_availability_update_rolls_back_prior_merge(state):
    """An apply-time SQL abort rolls back the earlier staged INSERT and parent refresh."""
    prod = state[0]
    with sqlite3.connect(prod) as conn:
        conn.execute("""CREATE TRIGGER reject_availability BEFORE UPDATE OF invalid_reason ON videos
          WHEN OLD.video_id='old' BEGIN SELECT RAISE(ABORT, 'apply update blocked'); END""")
    before = snapshot(prod)
    result = invoke(state)
    assert result.returncode != 0
    assert "apply update blocked" in result.stderr
    assert snapshot(prod) == before


@pytest.mark.parametrize("payload", [None, [], False, 0])
def test_explicit_nonobject_report_rejects_before_canonical_write(state, payload):
    """Explicit JSON null must not downgrade requested apply to an ordinary merge."""
    prod, staging, rules, scope = state
    before = snapshot(prod)
    cmd = [sys.executable, str(MERGER), "--prod-db", str(prod),
           "--staging-db", str(staging), "--rules", str(rules),
           "--parent-health-hosts-file", str(scope),
           "--availability-sweep-report-json", json.dumps(payload)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "Availability report must be a JSON object" in result.stderr
    assert snapshot(prod) == before
