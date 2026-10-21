"""Characterization tests for updater pipeline command sequencing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
        timeout_ms=5000,
        max_retries=3,
        videos_stop_after_full_pages=2,
        max_instances=0,
        max_channels=0,
        max_videos_pages=0,
        whitelist_url="https://join.example/hosts",
        sync_join_whitelist=False,
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


def _patch_lightweight(monkeypatch, *, denied=frozenset(), join=frozenset(), prod=frozenset()):
    """Patch heavy DB/network helpers while exercising real pipeline command construction."""

    monkeypatch.setattr(pipeline, "load_denied_hosts", lambda prod_db: set(denied))
    monkeypatch.setattr(pipeline, "fetch_join_hosts", lambda url: set(join))
    monkeypatch.setattr(pipeline, "list_prod_hosts", lambda prod_db: set(prod))
    monkeypatch.setattr(pipeline, "purge_hosts", lambda **kwargs: {})
    monkeypatch.setattr(pipeline, "init_staging_db", lambda staging_db, schema_path: None)
    monkeypatch.setattr(pipeline, "seed_staging_from_prod", lambda prod_db, staging_db: None)
    monkeypatch.setattr(pipeline, "purge_hosts_from_staging", lambda staging_db, hosts: {})
    monkeypatch.setattr(
        pipeline,
        "count_staging_deltas",
        lambda prod_db, staging_db: {
            "instances_new": 0,
            "channels_new": 0,
            "videos_new": 0,
            "embeddings_new": 0,
        },
    )
    monkeypatch.setattr(pipeline, "inject_replace_embedding_for_test", lambda **kwargs: None)
    monkeypatch.setattr(pipeline, "prune_staging_local_non_ok_instances", lambda **kwargs: {})


def test_normal_run_preserves_command_order_and_gpu_flags(monkeypatch, tmp_path) -> None:
    """Normal runs emit the current crawler/job/systemctl command order."""

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
        "videos-cli.js",
        "channels-videos-count-cli.js",
        "build-video-embeddings.py",
        "systemctl",
        "merge-staging-db.py",
        "recompute-popularity.py",
        "build-ann-index.py",
        "precompute-similar-ann.py",
        "systemctl",
    ]
    assert "--gpu" in seen[4]
    assert seen[5] == ["systemctl", "stop", "svc"]
    assert seen[-1] == ["systemctl", "start", "svc"]
    precompute = seen[-2]
    assert precompute.count(str(tmp_path / "ann.index")) == 2


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
    heavy = [
        cmd
        for cmd in seen
        if any(name in " ".join(cmd) for name in ["embeddings", "build-ann", "precompute"])
    ]
    assert all("--cpu" in cmd for cmd in heavy)
