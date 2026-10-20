"""Observable Engine visibility regressions for explicit parent failures."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine/server"))
from data.serving_moderation import ServingVisibility, build_serving_visibility_sql


@pytest.mark.parametrize("domain", ["example.org", "Example.org", " example.org "])
@pytest.mark.parametrize("parent", ["instances", "channels"])
def test_parent_visibility_normalizes_legacy_video_host_without_rewriting_identity(domain, parent):
    """Legacy video PK spelling cannot bypass a freshly observed canonical parent error."""
    from data.parent_health_visibility import filter_rows_by_parent_health

    with sqlite3.connect(":memory:") as conn:
        conn.executescript("""
          CREATE TABLE videos(video_id,instance_domain,channel_id,invalid_reason);
          CREATE TABLE instances(host TEXT PRIMARY KEY,health_status);
          CREATE TABLE channels(channel_id,instance_domain,health_status,
            PRIMARY KEY(channel_id,instance_domain));
          INSERT INTO instances VALUES('example.org',NULL);
          INSERT INTO channels VALUES('c','example.org',NULL);
        """)
        conn.execute("INSERT INTO videos VALUES('v',?,'c',NULL)", (domain,))
        sql = build_serving_visibility_sql("v", ServingVisibility(False, False))
        query = f"SELECT video_id FROM videos v WHERE {sql}"
        row = {"video_id": "v", "instance_domain": domain, "channel_id": "c"}
        assert conn.execute(query).fetchall() == [("v",)]
        conn.execute(f"UPDATE {parent} SET health_status='error'")
        assert conn.execute(query).fetchall() == []
        assert filter_rows_by_parent_health(conn, [row]) == []
        conn.execute(f"UPDATE {parent} SET health_status='ok'")
        assert conn.execute(query).fetchall() == [("v",)]
        assert filter_rows_by_parent_health(conn, [row]) == [row]
        assert conn.execute("SELECT instance_domain,invalid_reason FROM videos").fetchone() == (domain, None)


def test_explicit_parent_errors_hide_video_even_with_moderation_disabled() -> None:
    """Explicit parent failures hide child rows irrespective of moderation switches."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE videos(video_id TEXT, instance_domain TEXT, channel_id TEXT, invalid_reason TEXT);
        CREATE TABLE instances(host TEXT PRIMARY KEY, health_status TEXT);
        CREATE TABLE channels(channel_id TEXT, instance_domain TEXT, health_status TEXT, PRIMARY KEY(channel_id,instance_domain));
        INSERT INTO videos VALUES ('v1','a.example','c1',NULL), ('v2','b.example','c2',NULL),
                                  ('v3','c.example','c3',NULL), ('v4','d.example','c4',NULL);
        INSERT INTO instances VALUES ('a.example','ok'), ('b.example','error'), ('c.example',NULL);
        INSERT INTO channels VALUES ('c1','a.example','error'), ('c2','b.example','ok'),
                                   ('c3','c.example',NULL);
    """)
    sql = build_serving_visibility_sql("v", ServingVisibility(False, False))
    observed = {row[0] for row in conn.execute(f"SELECT video_id FROM videos v WHERE {sql}")}
    assert observed == {"v3", "v4"}
    conn.close()


def test_parent_error_gate_uses_attached_canonical_db() -> None:
    """Random's attached DB cannot accidentally check an unrelated main schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("ATTACH DATABASE ':memory:' AS canonical")
    conn.executescript("""
        CREATE TABLE canonical.videos(video_id TEXT, instance_domain TEXT, channel_id TEXT, invalid_reason TEXT);
        CREATE TABLE canonical.instances(host TEXT PRIMARY KEY, health_status TEXT);
        CREATE TABLE canonical.channels(channel_id TEXT, instance_domain TEXT, health_status TEXT, PRIMARY KEY(channel_id, instance_domain));
        INSERT INTO canonical.videos VALUES ('v1','a.example','c1',NULL);
        INSERT INTO canonical.instances VALUES ('a.example','error');
        INSERT INTO canonical.channels VALUES ('c1','a.example',NULL);
    """)
    sql = build_serving_visibility_sql("v", ServingVisibility(False, False), schema="canonical")
    assert conn.execute(f"SELECT count(*) FROM canonical.videos v WHERE {sql}").fetchone()[0] == 0
    conn.close()


def test_materialized_recommendations_filter_unhealthy_parents() -> None:
    """Cached rows obey fresh parent errors even with runtime moderation disabled."""
    import threading
    from types import SimpleNamespace
    from data.serving_moderation import apply_serving_moderation_filters

    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE instances(host TEXT PRIMARY KEY, health_status TEXT);
        CREATE TABLE channels(channel_id TEXT, instance_domain TEXT, health_status TEXT,
                              PRIMARY KEY(channel_id, instance_domain));
        INSERT INTO instances VALUES ('bad.example','error'), ('ok.example','ok');
        INSERT INTO channels VALUES ('bad-channel','ok.example','error'), ('ok-channel','ok.example','ok');
    """)
    server = SimpleNamespace(
        db=conn,
        db_lock=threading.RLock(),
        enable_instance_ignore=False,
        enable_channel_blocklist=False,
    )
    rows = [
        {"video_id": "bad-host", "instance_domain": "bad.example", "channel_id": "c"},
        {"video_id": "bad-channel", "instance_domain": "ok.example", "channel_id": "bad-channel"},
        {"video_id": "ok", "instance_domain": "ok.example", "channel_id": "ok-channel"},
        {"video_id": "unknown", "instance_domain": "missing.example", "channel_id": "unknown"},
    ]
    visible, stats = apply_serving_moderation_filters(server, rows)
    assert [row["video_id"] for row in visible] == ["ok", "unknown"]
    assert stats is None
    conn.close()
