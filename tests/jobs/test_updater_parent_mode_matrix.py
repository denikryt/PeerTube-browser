"""Run-mode contracts for the updater's fresh parent lifecycle boundary.

These scenarios execute the real Python pipeline and SQLite staging state. Only
external crawler/network/derived subprocesses are simulated at the process edge.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from engine.server.db.jobs.updater import pipeline, staging
from tests.jobs.test_updater_pipeline_commands import _args

SCHEMA = Path(__file__).resolve().parents[2] / "engine/crawler/schema.sql"


def _prepare_db(tmp_path: Path) -> tuple[Path, Path]:
    """Produce production parents and one existing video for scope assertions."""
    prod, stage = tmp_path / "prod.db", tmp_path / "staging.db"
    with sqlite3.connect(prod) as conn:
        conn.executescript(SCHEMA.read_text())
        for host in ("a.example", "b.example"):
            conn.execute("INSERT INTO instances(host) VALUES(?)", (host,))
            conn.execute(
                "INSERT INTO channels(channel_id,channel_name,instance_domain) VALUES('owned','owned',?)",
                (host,),
            )
        conn.execute(
            "INSERT INTO videos(video_id,video_uuid,channel_id,instance_domain,last_checked_at) "
            "VALUES('existing','existing-uuid','owned','a.example',0)"
        )
    return prod, stage


def _runner(stage: Path, seen: list[tuple[str, list[str], tuple[str, ...] | None]]):
    """Simulate crawler's persisted parent observations, not updater SQL selection."""
    def run(cmd, cwd):
        name = Path(cmd[1]).name if cmd[0] in ("node", "python") else cmd[0]
        hosts = None
        if "--hosts-file" in cmd:
            f = Path(cmd[cmd.index("--hosts-file") + 1])
            hosts = tuple(line.strip() for line in f.read_text().splitlines() if line.strip())
        seen.append((name, list(cmd), hosts))
        if cmd[0] != "node":
            return
        with sqlite3.connect(stage) as conn:
            if name == "channels-cli.js" and "--initialize-only" in cmd:
                for host in hosts or ():
                    conn.execute(
                        "INSERT INTO channel_crawl_progress(instance_domain,status,last_start,updated_at) "
                        "VALUES(?,'pending',0,1) ON CONFLICT(instance_domain) DO UPDATE SET "
                        "status='pending',last_start=0,updated_at=1", (host,),
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO crawl_state(key,value) "
                        "VALUES(?,'page_zero_complete_v1')", ("parent_enumeration_v1:" + host,),
                    )
                    conn.execute(
                        "UPDATE instances SET health_status=NULL,health_checked_at=NULL,health_error=NULL WHERE host=?", (host,),
                    )
                    conn.execute(
                        "UPDATE channels SET health_status=NULL,health_checked_at=NULL,health_error=NULL "
                        "WHERE instance_domain=?", (host,),
                    )
            elif name == "instances-health-cli.js":
                for host in hosts or ():
                    conn.execute("UPDATE instances SET health_status='ok',health_checked_at=123 WHERE host=?", (host,))
            elif name == "channels-cli.js" and "--already-initialized" in cmd:
                for host in hosts or ():
                    conn.execute("UPDATE channel_crawl_progress SET status='done',last_start=0 WHERE instance_domain=?", (host,))
            elif name == "channels-cli.js" and "--check-health" in cmd:
                for host in hosts or ():
                    conn.execute("UPDATE channels SET health_status='ok',health_checked_at=123 WHERE instance_domain=?", (host,))
            elif name == "host-pipeline-cli.js":
                for host in hosts or ():
                    # Single host-pipeline subprocess owns reset, probe and listing.
                    conn.execute(
                        "INSERT OR REPLACE INTO crawl_state(key,value) "
                        "VALUES(?,'page_zero_complete_v1')", ("parent_enumeration_v1:" + host,),
                    )
                    conn.execute(
                        "INSERT INTO channel_crawl_progress(instance_domain,status,last_start,updated_at) "
                        "VALUES(?,'done',0,123) ON CONFLICT(instance_domain) DO UPDATE SET "
                        "status='done',last_start=0,updated_at=123", (host,),
                    )
                    conn.execute("UPDATE instances SET health_status='ok',health_checked_at=123 WHERE host=?", (host,))
                    conn.execute("UPDATE channels SET health_status='ok',health_checked_at=123 WHERE instance_domain=?", (host,))
            elif name == "videos-cli.js" and "--check-availability" in cmd:
                conn.execute("UPDATE video_availability_work SET outcome='available',checked_at=123")
    return run


@pytest.mark.parametrize("mode", ["normal", "resume", "retry", "host-pipeline", "strict-sync", "empty"])
def test_parent_scope_and_run_mode_cannot_authorize_unselected_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """Each mode owns a precise host selection; old progress cannot promote other hosts."""
    prod, stage = _prepare_db(tmp_path)
    args = _args(tmp_path, resume_staging=False, skip_systemctl=True)
    (Path(args.crawler_dir) / "schema.sql").write_text(SCHEMA.read_text())
    selected = tmp_path / "selected-hosts.txt"
    selected.write_text("missing.example\n" if mode == "empty" else "a.example\n")
    args.hosts_file = str(selected)
    monkeypatch.setattr(pipeline, "_prepared_discovery_is_available", lambda p: True)
    monkeypatch.setattr(pipeline, "assert_production_schema_compatible", lambda p, s: None)
    monkeypatch.setattr(pipeline, "load_denied_hosts", lambda p: set())
    monkeypatch.setattr(pipeline, "fetch_join_hosts", lambda url: {"a.example", "b.example"})
    monkeypatch.setattr(pipeline, "list_prod_hosts", lambda p: {"a.example", "b.example"})
    monkeypatch.setattr(pipeline, "purge_hosts", lambda **kwargs: {})
    monkeypatch.setattr(pipeline, "inject_replace_embedding_for_test", lambda **kwargs: None)
    if mode in {"resume", "retry"}:
        staging.init_staging_db(stage, SCHEMA)
        staging.seed_staging_from_prod(prod, stage)
        with sqlite3.connect(stage) as conn:
            conn.execute(
                "INSERT INTO channel_crawl_progress(instance_domain,status,last_start,updated_at) "
                "VALUES('a.example','done',0,1)"
            )
            conn.execute("UPDATE instances SET health_status='error',health_checked_at=12,health_error='old' WHERE host='a.example'")
            if mode == "retry":
                conn.execute("UPDATE instances SET health_status='ok',health_checked_at=10,health_error=NULL WHERE host='a.example'")
                conn.execute("UPDATE channels SET health_status='ok',health_checked_at=10 WHERE instance_domain='a.example'")
                conn.execute("INSERT INTO crawl_state VALUES('parent_enumeration_v1:a.example','page_zero_complete_v1')")
                conn.execute("UPDATE channels SET last_error='count failed',last_error_source='videos_count' WHERE instance_domain='a.example'")
        args.resume_staging = True
    if mode == "retry":
        args.retry_errors = True
    if mode == "host-pipeline":
        args.host_pipeline = True
    if mode == "strict-sync":
        args.sync_join_whitelist = True
        args.check_existing_video_availability = True

    seen: list[tuple[str, list[str], tuple[str, ...] | None]] = []
    pipeline.run_pipeline(args, command_runner=_runner(stage, seen), validate_files=False)
    nodes = [part for part in seen if part[1][0] == "node"]
    names = [part[0] for part in nodes]
    # A nonempty operator scope with zero registry overlap is valid zero work.
    # Only discovery gets the opt-in; all other stages remain exact-scope.
    discovery = [cmd for name, cmd, _ in nodes if name == "instances-cli.js"]
    if mode not in {"retry", "strict-sync"}:
        assert len(discovery) == 1
        assert "--allow-empty-scoped-whitelist" in discovery[0]
    assert all("--allow-empty-scoped-whitelist" not in cmd
               for name, cmd, _ in nodes if name != "instances-cli.js")
    if mode == "retry":
        assert names == ["channels-videos-count-cli.js", "videos-cli.js"]
        assert all("--errors" in part[1] for part in nodes)
    elif mode == "host-pipeline":
        assert names == ["instances-cli.js", "host-pipeline-cli.js"]
    elif mode == "empty":
        assert all(name == "instances-cli.js" for name in names)
    else:
        if mode == "strict-sync":
            assert "channels-videos-count-cli.js" not in names
            assert not any(name == "videos-cli.js" and "--check-availability" not in cmd
                           for name, cmd, _ in nodes)
        else:
            assert names.count("instances-health-cli.js") == 1
            assert names.count("channels-cli.js") == 3
            assert "channels-videos-count-cli.js" in names
    merges = [part for part in seen if part[0] == "merge-staging-db.py"]
    if mode != "retry":
        assert len(merges) == 1
        cmd = merges[0][1]
        assert "--parent-health-hosts-file" in cmd
        assert Path(cmd[cmd.index("--parent-health-hosts-file") + 1]).name.startswith("ptb-parent-run-")
    else:
        assert not merges

    with sqlite3.connect(stage) as conn:
        # Every selected parent is fresh; historical 'done' of b.example
        # must never become an authorization for work on b.example.
        rows = conn.execute(
            "SELECT instance_domain,status FROM channel_crawl_progress ORDER BY instance_domain"
        ).fetchall()
        assert not any(host == "b.example" and status == "done" for host, status in rows)
        if mode not in {"empty", "retry"}:
            assert ("a.example", "done") in rows
        if mode == "retry":
            assert conn.execute("SELECT health_checked_at FROM instances WHERE host='a.example'").fetchone() == (10,)
