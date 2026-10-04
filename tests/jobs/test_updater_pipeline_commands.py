"""Characterization tests for updater pipeline command sequencing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.server.db.jobs.updater import pipeline


def _args(tmp_path: Path, **overrides):
    """Build representative updater args for command-sequence tests."""

    crawler = tmp_path / "crawler"
    staging = tmp_path / "staging.db"
    prod = tmp_path / "prod.db"
    rules = tmp_path / "rules.json"
    for path in (crawler / "dist",):
        path.mkdir(parents=True, exist_ok=True)
    args = SimpleNamespace(
        prod_db=str(prod),
        staging_db=str(staging),
        resume_staging=True,
        index_path=str(tmp_path / "ann.index"),
        index_meta_path=str(tmp_path / "ann.index.json"),
        similarity_db=str(tmp_path / "similarity.db"),
        random_cache_db=str(tmp_path / "random-cache.db"),
        merge_rules=str(rules),
        mode="dev",
        service_name="svc",
        systemctl_bin="systemctl",
        systemctl_use_sudo=False,
        skip_systemctl=False,
        logs=str(tmp_path / "worker.log"),
        lock_file=str(tmp_path / "worker.lock"),
        crawler_dir=str(crawler),
        node_bin="node",
        python_bin="python",
        concurrency=4,
        host_concurrency=2,
        host_delay_ms=200,
        timeout_ms=5000,
        max_retries=3,
        videos_stop_after_full_pages=2,
        max_instances=0,
        max_channels=0,
        max_videos_pages=0,
        hosts_file=None,
        whitelist_url="https://join.example/hosts",
        sync_join_whitelist=False,
        retry_errors=False,
        yes=False,
        dry_run=False,
        skip_local_dead=False,
        nlist=4096,
        inject_replace_embedding_for_test=False,
        fail_before_merge=False,
        fail_during_ann_build=False,
        fail_after_merge_before_similarity=False,
        use_gpu=True,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _patch_lightweight(
    monkeypatch, *, denied=frozenset(), join=frozenset(), prod=frozenset(), prepared_ready=True
):
    """Patch heavy DB/network helpers while exercising real pipeline command construction."""

    monkeypatch.setattr(pipeline, "assert_production_schema_compatible", lambda prod_db, schema_path: None)
    monkeypatch.setattr(pipeline, "load_denied_hosts", lambda prod_db: set(denied))
    monkeypatch.setattr(pipeline, "fetch_join_hosts", lambda url: set(join))
    monkeypatch.setattr(pipeline, "list_prod_hosts", lambda prod_db: set(prod))
    monkeypatch.setattr(pipeline, "purge_hosts", lambda **kwargs: {})
    monkeypatch.setattr(pipeline, "init_staging_db", lambda staging_db, schema_path: None)
    monkeypatch.setattr(pipeline, "seed_staging_from_prod", lambda prod_db, staging_db: None)
    monkeypatch.setattr(pipeline, "purge_hosts_from_staging", lambda staging_db, hosts: {})
    monkeypatch.setattr(pipeline, "load_scoped_hosts_file", lambda hosts_file: {"target.example"})
    monkeypatch.setattr(
        pipeline,
        "count_staging_deltas",
        lambda prod_db, staging_db, scoped_hosts=None: {
            "instances_new": 0,
            "channels_new": 0,
            "videos_new": 0,
            "embeddings_new": 0,
        },
    )
    monkeypatch.setattr(pipeline, "inject_replace_embedding_for_test", lambda **kwargs: None)
    monkeypatch.setattr(pipeline, "prune_staging_local_non_ok_instances", lambda **kwargs: {})
    if hasattr(pipeline, "_prepared_discovery_is_available"):
        monkeypatch.setattr(
            pipeline, "_prepared_discovery_is_available", lambda prod_db: prepared_ready
        )


def test_normal_run_counts_unknown_channels_before_crawling_video_metadata(monkeypatch, tmp_path) -> None:
    """Normal updates resolve missing counts before selecting channels with videos."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []
    pipeline.run_pipeline(
        _args(tmp_path),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )
    names = [Path(cmd[1] if cmd[0] in {"node", "python"} else cmd[0]).name for cmd in seen]
    assert names == [
        "instances-cli.js",
        "channels-cli.js",
        "channels-videos-count-cli.js",
        "videos-cli.js",
        "build-video-embeddings.py",
        "systemctl",
        "merge-staging-db.py",
        "recompute-popularity.py",
        "rebuild-video-discovery-data.py",
        "sync-video-index-ids.py",
        "rebuild-video-search-index.py",
        "build-ann-index.py",
        "precompute-random-index-ids.py",
        "precompute-similar-ann.py",
        "systemctl",
    ]
    assert "--gpu" in seen[4]
    assert "--force" in seen[4]
    assert seen[5] == ["systemctl", "stop", "svc"]
    assert seen[-1] == ["systemctl", "start", "svc"]
    search_cmd = next(cmd for cmd in seen if "rebuild-video-search-index.py" in cmd[1])
    assert "ensure-video-indexes.py" not in names
    prepared_index = names.index("rebuild-video-discovery-data.py")
    sync_index = names.index("sync-video-index-ids.py")
    search_index = names.index("rebuild-video-search-index.py")
    ann_index = names.index("build-ann-index.py")
    assert prepared_index < sync_index < search_index < ann_index
    assert "--gpu" not in search_cmd
    assert "--cpu" not in search_cmd
    random_cmd = next(cmd for cmd in seen if "precompute-random-index-ids.py" in cmd[1])
    assert "--db" in random_cmd
    assert str(tmp_path / "prod.db") in random_cmd
    assert "--out" in random_cmd
    assert str(tmp_path / "random-cache.db") in random_cmd
    assert "--refresh" in random_cmd
    assert "--reset" not in random_cmd
    assert "--filtered" in random_cmd
    assert "--max-per-author" in random_cmd
    assert "100" in random_cmd
    assert "--cpu" not in random_cmd
    assert "--gpu" not in random_cmd
    precompute = seen[-2]
    assert precompute.count(str(tmp_path / "ann.index")) == 1
    # Refresh mode derives its source set from the existing cache. Recreating
    # that cache first would erase every source and turn the refresh into a no-op.
    assert "--refresh-existing" in precompute
    assert "--recreate-out-db" not in precompute


def test_host_pipeline_mode_replaces_three_global_crawler_stages(monkeypatch, tmp_path) -> None:
    """Opt-in host scheduling uses one crawler command after instance discovery."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []
    pipeline.run_pipeline(
        _args(tmp_path, host_pipeline=True),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )

    crawler_names = [Path(cmd[1]).name for cmd in seen if cmd[0] == "node"]
    assert crawler_names == ["instances-cli.js", "host-pipeline-cli.js"]
    host_command = next(cmd for cmd in seen if "host-pipeline-cli.js" in cmd[1])
    assert host_command[host_command.index("--concurrency") + 1] == "4"
    assert "--resume" in host_command


def test_skip_systemctl_removes_stop_start_only(monkeypatch, tmp_path) -> None:
    """Skipping systemctl preserves data-build commands and removes service commands."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []
    pipeline.run_pipeline(
        _args(tmp_path, skip_systemctl=True),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )
    assert all(cmd[0] != "systemctl" for cmd in seen)
    assert any("merge-staging-db.py" in part for cmd in seen for part in cmd)


def test_sync_join_no_changes_finishes_early(monkeypatch, tmp_path) -> None:
    """Sync mode with no new or stale hosts does not run crawler or merge commands."""

    _patch_lightweight(monkeypatch, join={"a.ex"}, prod={"a.ex"})
    seen: list[list[str]] = []
    pipeline.run_pipeline(
        _args(tmp_path, sync_join_whitelist=True),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )
    assert seen == []


def test_sync_join_dry_run_returns_before_commands(monkeypatch, tmp_path) -> None:
    """Dry-run sync returns after purge planning and before stage commands."""

    _patch_lightweight(monkeypatch, join={"a.ex"}, prod={"old.ex"})
    seen: list[list[str]] = []
    pipeline.run_pipeline(
        _args(tmp_path, sync_join_whitelist=True, dry_run=True),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )
    assert seen == []


def test_denied_hosts_add_exclude_file(monkeypatch, tmp_path) -> None:
    """Denylisted hosts add exclude-hosts-file to crawler commands."""

    _patch_lightweight(monkeypatch, denied={"bad.ex"})
    seen: list[list[str]] = []
    pipeline.run_pipeline(
        _args(tmp_path),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )
    crawler_cmds = [cmd for cmd in seen if cmd[0] == "node"]
    assert all("--exclude-hosts-file" in cmd for cmd in crawler_cmds)


def test_sync_new_hosts_add_whitelist_file(monkeypatch, tmp_path) -> None:
    """New JoinPeerTube hosts in sync mode add whitelist file to instances crawl."""

    _patch_lightweight(monkeypatch, join={"new.ex"}, prod=set())
    seen: list[list[str]] = []
    pipeline.run_pipeline(
        _args(tmp_path, sync_join_whitelist=True),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )
    assert "--whitelist-file" in seen[0]


def test_cpu_mode_appends_cpu_to_heavy_jobs(monkeypatch, tmp_path) -> None:
    """CPU mode preserves current heavy-job CPU flags."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []
    pipeline.run_pipeline(
        _args(tmp_path, use_gpu=False),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )
    heavy_scripts = {
        "build-video-embeddings.py",
        "build-ann-index.py",
        "precompute-similar-ann.py",
    }
    heavy = [
        cmd
        for cmd in seen
        if len(cmd) > 1 and Path(cmd[1]).name in heavy_scripts
    ]
    assert all("--cpu" in cmd for cmd in heavy)
    random_cmd = next(cmd for cmd in seen if "precompute-random-index-ids.py" in cmd[1])
    assert "--cpu" not in random_cmd
    assert "--gpu" not in random_cmd


def test_hosts_file_scopes_all_crawler_stages(monkeypatch, tmp_path) -> None:
    """Updater passes host-scope files through every crawler stage command."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []
    pipeline.run_pipeline(
        _args(tmp_path, hosts_file="/tmp/hosts.txt"),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )
    crawler_cmds = [cmd for cmd in seen if cmd[0] == "node"]
    assert len(crawler_cmds) == 4
    assert all("--hosts-file" in cmd for cmd in crawler_cmds)
    assert all("/tmp/hosts.txt" in cmd for cmd in crawler_cmds)


def test_host_concurrency_is_forwarded_to_per_host_crawler_stages(monkeypatch, tmp_path) -> None:
    """Updater gives every host-local crawler stage the requested request limit."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []
    pipeline.run_pipeline(
        _args(tmp_path, host_concurrency=1),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )
    crawler_cmds = [cmd for cmd in seen if cmd[0] == "node" and Path(cmd[1]).name != "instances-cli.js"]
    assert crawler_cmds
    assert all(cmd[cmd.index("--host-concurrency") + 1] == "1" for cmd in crawler_cmds)


def test_host_delay_is_forwarded_to_every_per_host_crawler_stage(monkeypatch, tmp_path) -> None:
    """Updater applies one pacing value to channels, videos, and count requests."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []
    pipeline.run_pipeline(
        _args(tmp_path, host_delay_ms=750),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )
    crawler_cmds = [cmd for cmd in seen if cmd[0] == "node"]
    assert crawler_cmds
    assert all(cmd[cmd.index("--host-delay") + 1] == "750" for cmd in crawler_cmds)


def test_retry_errors_runs_only_error_capable_crawler_stages(monkeypatch, tmp_path) -> None:
    """Retry mode revisits failed staging records without replaying successful discovery."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []
    # Resume fixtures represent a current availability-semantics generation.
    import sqlite3
    with sqlite3.connect(tmp_path / "staging.db") as conn:
        conn.execute("CREATE TABLE crawl_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        conn.execute("INSERT INTO crawl_state VALUES('video_availability_semantics','canonical_absence_v1')")
    pipeline.run_pipeline(
        _args(tmp_path, retry_errors=True, resume_staging=True),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )
    crawler_cmds = [cmd for cmd in seen if cmd[0] == "node"]
    assert [Path(cmd[1]).name for cmd in crawler_cmds] == [
        "channels-cli.js",
        "channels-videos-count-cli.js",
        "videos-cli.js",
    ]
    assert all("--errors" in cmd for cmd in crawler_cmds)
    assert seen == crawler_cmds


def test_retry_errors_refuses_missing_staging(monkeypatch, tmp_path) -> None:
    """Retry mode cannot silently initialize an empty DB and discard the error set."""

    _patch_lightweight(monkeypatch)
    with pytest.raises(RuntimeError, match="existing --resume-staging"):
        pipeline.run_pipeline(
            _args(tmp_path, retry_errors=True, resume_staging=True),
            command_runner=lambda cmd, cwd: None,
            validate_files=False,
        )


def test_schema_preflight_runs_before_any_sync_purge(monkeypatch, tmp_path) -> None:
    """Stale production schema aborts before sync code can mutate production."""

    events: list[str] = []
    _patch_lightweight(monkeypatch, join={"new.ex"}, prod={"old.ex"})

    def fail_preflight(prod_db, schema_path):
        events.append("preflight")
        raise RuntimeError("Run migrate-whitelist.py")

    monkeypatch.setattr(pipeline, "assert_production_schema_compatible", fail_preflight)
    monkeypatch.setattr(
        pipeline,
        "purge_hosts",
        lambda **kwargs: events.append("purge") or {},
    )

    with pytest.raises(RuntimeError, match="migrate-whitelist"):
        pipeline.run_pipeline(
            _args(tmp_path, sync_join_whitelist=True, yes=True),
            command_runner=lambda cmd, cwd: events.append("command"),
            validate_files=False,
        )

    assert events == ["preflight"]


def test_resume_staging_force_rebuilds_embeddings_before_merge(monkeypatch, tmp_path) -> None:
    """A resumed staging DB never contributes pre-existing recipe embeddings to prod."""

    _patch_lightweight(monkeypatch)
    # Resume fixtures represent a current availability-semantics generation.
    import sqlite3
    with sqlite3.connect(tmp_path / "staging.db") as conn:
        conn.execute("CREATE TABLE crawl_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        conn.execute("INSERT INTO crawl_state VALUES('video_availability_semantics','canonical_absence_v1')")
    seen: list[list[str]] = []
    pipeline.run_pipeline(
        _args(tmp_path, resume_staging=True),
        command_runner=lambda cmd, cwd: seen.append(list(cmd)),
        validate_files=False,
    )

    embeddings_index = next(
        i for i, cmd in enumerate(seen) if len(cmd) > 1 and "build-video-embeddings.py" in cmd[1]
    )
    merge_index = next(
        i for i, cmd in enumerate(seen) if len(cmd) > 1 and "merge-staging-db.py" in cmd[1]
    )
    assert "--force" in seen[embeddings_index]
    assert embeddings_index < merge_index


def test_staging_embedding_rebuild_failure_prevents_merge(monkeypatch, tmp_path) -> None:
    """Merge is fail-closed when the mandatory current-recipe staging rebuild fails."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []

    def runner(cmd, cwd):
        seen.append(list(cmd))
        if len(cmd) > 1 and "build-video-embeddings.py" in cmd[1]:
            raise RuntimeError("embedding rebuild failed")

    with pytest.raises(RuntimeError, match="embedding rebuild failed"):
        pipeline.run_pipeline(_args(tmp_path), command_runner=runner, validate_files=False)

    assert not any(
        len(cmd) > 1 and "merge-staging-db.py" in cmd[1]
        for cmd in seen
    )


def test_sync_stale_host_delete_happens_only_after_engine_stop(monkeypatch, tmp_path) -> None:
    """Dry-run planning may happen early, but destructive stale purge is offline."""
    events: list[str] = []
    _patch_lightweight(monkeypatch, join={"new.example"}, prod={"stale.example"})

    def fake_purge_hosts(**kwargs):
        events.append("purge-dry" if kwargs["dry_run"] else "purge-live")
        return {}

    monkeypatch.setattr(pipeline, "purge_hosts", fake_purge_hosts)

    def runner(cmd, cwd):
        if cmd[:3] == ["systemctl", "stop", "svc"]:
            events.append("stop")
        elif cmd[:3] == ["systemctl", "start", "svc"]:
            events.append("start")

    pipeline.run_pipeline(
        _args(tmp_path, sync_join_whitelist=True, yes=True),
        command_runner=runner,
        validate_files=False,
    )

    assert events.index("purge-dry") < events.index("stop")
    assert events.index("stop") < events.index("purge-live")
    assert events.index("purge-live") < events.index("start")


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("marker", [None, "legacy_transient_invalidity", "canonical_absence_v1"])
def test_resume_marker_preflight_precedes_network_and_commands(
    monkeypatch, tmp_path, retry, marker
):
    """Legacy resume/retry stops before side effects; current marked resume proceeds."""
    import sqlite3

    args = _args(tmp_path, retry_errors=retry, sync_join_whitelist=True)
    _patch_lightweight(monkeypatch)
    with sqlite3.connect(args.staging_db) as conn:
        conn.execute("CREATE TABLE crawl_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        if marker:
            conn.execute(
                "INSERT INTO crawl_state VALUES(?,?)", ("video_availability_semantics", marker)
            )
    reached = []

    def network(url):
        """Record reaching the outer network boundary after marker admission."""
        reached.append("network")
        raise RuntimeError("network boundary reached")

    monkeypatch.setattr(pipeline, "fetch_join_hosts", network)
    seen = []
    if marker == "canonical_absence_v1":
        with pytest.raises(RuntimeError, match="network boundary reached"):
            pipeline.run_pipeline(
                args, command_runner=lambda cmd, cwd=None: seen.append(cmd), validate_files=False
            )
        assert reached == ["network"]
    else:
        with pytest.raises(RuntimeError, match="recreate"):
            pipeline.run_pipeline(
                args, command_runner=lambda cmd, cwd=None: seen.append(cmd), validate_files=False
            )
        assert reached == []
    assert seen == []


@pytest.mark.parametrize("skip_systemctl", [False, True])
def test_first_run_owns_fresh_staging_and_explicit_service_lifecycle(
    monkeypatch, tmp_path, skip_systemctl
):
    """First no-resume run stamps staging itself; outer-offline mode issues no systemctl."""
    from engine.server.db.jobs.updater.staging import (
        init_staging_db,
        assert_video_availability_staging_semantics,
    )

    args = _args(tmp_path, resume_staging=False, skip_systemctl=skip_systemctl)
    _patch_lightweight(monkeypatch)
    (Path(args.crawler_dir) / "schema.sql").write_text("CREATE TABLE instances(host TEXT);")
    monkeypatch.setattr(pipeline, "init_staging_db", init_staging_db)
    seen = []

    def command(cmd, cwd):
        """Check actual staging evidence before the first external command."""
        assert_video_availability_staging_semantics(Path(args.staging_db))
        seen.append(list(cmd))

    pipeline.run_pipeline(args, command_runner=command, validate_files=False)
    lifecycle = [cmd[1] for cmd in seen if cmd[0] == "systemctl"]
    assert lifecycle == ([] if skip_systemctl else ["stop", "start"])
    if not skip_systemctl:
        stop = next(i for i, cmd in enumerate(seen) if cmd[0] == "systemctl" and cmd[1] == "stop")
        merge = next(
            i for i, cmd in enumerate(seen) if any("merge-staging-db.py" in part for part in cmd)
        )
        start = next(i for i, cmd in enumerate(seen) if cmd[0] == "systemctl" and cmd[1] == "start")
        assert stop < merge < start
