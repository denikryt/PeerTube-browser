"""Characterization tests for updater CLI parsing."""

from __future__ import annotations

from pathlib import Path

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
    assert args.timeout_ms == 5000
    assert args.dry_run is False
    assert args.sync_join_whitelist is False
    assert Path(args.lock_file).name == "peertube-browser-staging-sync.lock"


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
