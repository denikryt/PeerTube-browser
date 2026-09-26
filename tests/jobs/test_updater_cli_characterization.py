"""Characterization tests for updater CLI parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.server.db.jobs.updater import cli


def test_parse_args_keeps_representative_defaults(monkeypatch) -> None:
    """Parser keeps current flags/defaults while accepting explicit argv in tests."""

    monkeypatch.setattr(cli, "resolve_default_engine_service_name", lambda mode: f"svc-{mode}")
    args = cli.parse_args(["--mode", "dev", "--cpu", "--skip-systemctl"])
    assert args.mode == "dev"
    assert args.use_gpu is False
    assert args.skip_systemctl is True
    assert args.service_name == "svc-dev"
    assert args.concurrency == 4
    assert args.host_concurrency == 2
    assert args.host_delay_ms == 200
    assert args.retry_errors is False
    assert args.timeout_ms == 5000
    assert args.hosts_file is None
    assert args.dry_run is False
    assert args.sync_join_whitelist is False
    assert Path(args.lock_file).name == "peertube-browser-staging-sync.lock"
    assert args.random_cache_db.endswith("engine/server/db/random-cache.db")


def test_service_name_falls_back_without_installer(monkeypatch, tmp_path: Path) -> None:
    """Installer lookup fallback keeps dev/prod service-name compatibility."""

    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    assert cli.resolve_default_engine_service_name("dev") == "peertube-engine-dev"
    assert cli.resolve_default_engine_service_name("prod") == "peertube-engine"


def test_dry_run_without_sync_remains_pipeline_error(monkeypatch) -> None:
    """Argparse still accepts dry-run by itself; pipeline enforces the combination."""

    monkeypatch.setattr(cli, "resolve_default_engine_service_name", lambda mode: "svc")
    args = cli.parse_args(["--dry-run"])
    assert args.dry_run is True
    assert args.sync_join_whitelist is False


def test_random_cache_db_override_is_respected(monkeypatch) -> None:
    """Parser exposes the updater-owned random index-id cache output path."""

    monkeypatch.setattr(cli, "resolve_default_engine_service_name", lambda mode: "svc")
    args = cli.parse_args(["--random-cache-db", "/tmp/random.db"])
    assert args.random_cache_db == "/tmp/random.db"


def test_hosts_file_override_is_respected(monkeypatch) -> None:
    """Parser exposes the updater host-scope file for targeted reruns."""

    monkeypatch.setattr(cli, "resolve_default_engine_service_name", lambda mode: "svc")
    args = cli.parse_args(["--hosts-file", "/tmp/hosts.txt"])
    assert args.hosts_file == "/tmp/hosts.txt"


def test_hosts_file_relative_path_is_resolved_from_invocation_cwd(monkeypatch, tmp_path: Path) -> None:
    """Relative host-scope paths stay valid after updater changes cwd for crawler CLIs."""

    monkeypatch.setattr(cli, "resolve_default_engine_service_name", lambda mode: "svc")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tmp").mkdir()
    args = cli.parse_args(["--hosts-file", "tmp/hosts.txt"])
    assert args.hosts_file == str((tmp_path / "tmp/hosts.txt").resolve())


def test_retry_errors_and_host_request_limits_are_exposed(monkeypatch) -> None:
    """Operators can combine error retry with per-host concurrency and pacing limits."""

    monkeypatch.setattr(cli, "resolve_default_engine_service_name", lambda mode: "svc")
    args = cli.parse_args([
        "--resume-staging", "--retry-errors", "--host-concurrency", "1",
        "--host-delay-ms", "750"
    ])
    assert args.resume_staging is True
    assert args.retry_errors is True
    assert args.host_concurrency == 1
    assert args.host_delay_ms == 750


def test_retry_errors_requires_resumed_staging(monkeypatch) -> None:
    """Error-only mode cannot erase the progress rows it was asked to retry."""

    monkeypatch.setattr(cli, "resolve_default_engine_service_name", lambda mode: "svc")
    with pytest.raises(SystemExit):
        cli.parse_args(["--retry-errors"])


def test_host_pipeline_mode_is_exposed_and_rejects_error_only_mode(monkeypatch) -> None:
    """Host scheduling is opt-in and does not ambiguously combine with repair mode."""

    monkeypatch.setattr(cli, "resolve_default_engine_service_name", lambda mode: "svc")
    assert cli.parse_args(["--host-pipeline"]).host_pipeline is True
    with pytest.raises(SystemExit):
        cli.parse_args(["--resume-staging", "--retry-errors", "--host-pipeline"])
