"""End-to-end staging eligibility contracts for parent-controlled availability work."""

import sqlite3
from pathlib import Path

from engine.server.db.jobs.updater import staging

SCHEMA = Path(__file__).resolve().parents[2] / "engine/crawler/schema.sql"


def _seed(tmp_path):
    """Create real crawler databases with one complete and three ineligible hosts."""
    prod, stage = tmp_path / "production.db", tmp_path / "staging.db"
    staging.init_staging_db(prod, SCHEMA)
    staging.init_staging_db(stage, SCHEMA)
    hosts = ("ready.test", "error.test", "incomplete.test", "untrusted.test")
    with sqlite3.connect(prod) as db:
        for host in hosts:
            db.execute("INSERT INTO videos(video_id,video_uuid,instance_domain,channel_id,last_checked_at) VALUES(?,?,?,?,?)",
                       (host, "uuid-" + host, host, "channel", 123))
    with sqlite3.connect(stage) as db:
        for host in hosts:
            db.execute("INSERT INTO instances(host,health_status,health_checked_at) VALUES(?,?,?)",
                       (host, "error" if host == "error.test" else "ok", 123))
            db.execute("INSERT INTO channels(channel_id,channel_name,instance_domain,health_status,health_checked_at) VALUES(?,?,?,?,?)",
                       ("channel", "handle", host, "ok", 123))
            db.execute("INSERT INTO channel_crawl_progress(instance_domain,status,updated_at) VALUES(?,?,?)",
                       (host, "in_progress" if host == "incomplete.test" else "done", 123))
            if host != "untrusted.test":
                db.execute("INSERT INTO crawl_state(key,value) VALUES(?,?)",
                           ("parent_enumeration_v1:" + host, "page_zero_complete_v1"))
    return prod, stage


def test_parent_healthy_done_with_provenance_admits_only_eligible_work(tmp_path):
    """A fresh healthy complete parent admits a real production video."""
    prod, stage = _seed(tmp_path)
    assert staging.materialize_video_availability_work(prod, stage, included_hosts=None, denied_hosts=set()) == 0
    with sqlite3.connect(stage) as db:
        rows = db.execute("SELECT video_id FROM video_availability_work").fetchall()
    assert rows == [("ready.test",)]


def test_missing_unhealthy_or_incomplete_parents_never_produce_child_requests(tmp_path):
    """Parent failure, unfinished enumeration and old unproven done are excluded."""
    prod, stage = _seed(tmp_path)
    with sqlite3.connect(stage) as db:
        db.execute("UPDATE channels SET health_status=NULL WHERE instance_domain='ready.test'")
    staging.materialize_video_availability_work(prod, stage, included_hosts=None, denied_hosts=set())
    with sqlite3.connect(stage) as db:
        assert db.execute("SELECT COUNT(*) FROM video_availability_work").fetchone()[0] == 0


def test_retry_accepts_only_selected_hosts_with_current_enumeration_provenance(tmp_path):
    """A current completion stamp permits an error-repair selection without reset."""
    _, stage = _seed(tmp_path)
    staging.assert_retry_parent_provenance(stage, {"ready.test", "error.test"})
    with sqlite3.connect(stage) as db:
        assert db.execute(
            "SELECT status FROM channel_crawl_progress WHERE instance_domain='ready.test'"
        ).fetchone() == ("done",)


def test_retry_ignores_unrelated_legacy_host_without_repair(tmp_path):
    """An old done row without repair work cannot block ready count repair."""
    _, stage = _seed(tmp_path)
    with sqlite3.connect(stage) as db:
        db.execute("UPDATE channels SET last_error_source='videos_count' "
                   "WHERE instance_domain='ready.test'")
    staging.assert_retry_parent_provenance(stage, {"ready.test", "untrusted.test"})


def test_retry_rejects_old_done_with_count_repair_before_network(tmp_path):
    """Actual legacy error repair requires page-zero provenance before any child call."""
    import pytest
    _, stage = _seed(tmp_path)
    with sqlite3.connect(stage) as db:
        db.execute("UPDATE channels SET last_error_source='videos_count' "
                   "WHERE instance_domain='untrusted.test'")
    with pytest.raises(RuntimeError, match="untrusted.test.*ordinary --resume-staging"):
        staging.assert_retry_parent_provenance(stage, {"ready.test", "untrusted.test"})


def test_retry_rejects_old_done_with_video_repair_before_network(tmp_path):
    """Video enumeration errors also require current provenance, not historic done."""
    import pytest
    _, stage = _seed(tmp_path)
    with sqlite3.connect(stage) as db:
        db.execute("UPDATE channels SET videos_count=1 WHERE instance_domain='untrusted.test'")
        db.execute("INSERT INTO video_crawl_progress "
                   "(instance_domain,channel_id,channel_name,status,last_start,updated_at) "
                   "VALUES('untrusted.test','channel','handle','error',0,123)")
    with pytest.raises(RuntimeError, match="untrusted.test.*ordinary --resume-staging"):
        staging.assert_retry_parent_provenance(stage, {"ready.test", "untrusted.test"})


def test_retry_ignores_errors_outside_exact_host_scope(tmp_path):
    """An explicit host scope is a strict cap even if others have failed work."""
    _, stage = _seed(tmp_path)
    with sqlite3.connect(stage) as db:
        db.execute("UPDATE channels SET last_error_source='videos_count' "
                   "WHERE instance_domain='untrusted.test'")
    staging.assert_retry_parent_provenance(stage, {"ready.test"})


def test_scoped_parent_seed_copies_metadata_only_for_existing_selected_hosts(tmp_path):
    """Strict-sync sweep does not seed stale or unselected production parents."""
    prod, stage = tmp_path / "prod.db", tmp_path / "staging.db"
    staging.init_staging_db(prod, SCHEMA)
    staging.init_staging_db(stage, SCHEMA)
    with sqlite3.connect(prod) as db:
        for host in ("selected.test", "unselected.test"):
            db.execute("INSERT INTO instances(host,health_status) VALUES(?,'error')", (host,))
            db.execute("INSERT INTO channels(channel_id,instance_domain) VALUES('id',?)", (host,))
    staging.seed_staging_from_prod(prod, stage, {"selected.test"})
    with sqlite3.connect(stage) as db:
        assert db.execute("SELECT host FROM instances").fetchall() == [("selected.test",)]
        assert db.execute("SELECT instance_domain FROM channels").fetchall() == [("selected.test",)]
