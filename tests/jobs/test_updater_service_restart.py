"""Characterization tests for updater service restart failure behavior."""

from __future__ import annotations

import subprocess

import pytest

from engine.server.db.jobs.updater import pipeline
from tests.jobs.test_updater_pipeline_commands import _args, _patch_lightweight


def _run_with_failure(monkeypatch, tmp_path, args, fail_name: str):
    """Run pipeline with a fake command runner that fails on a named script."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []

    def runner(cmd, cwd):
        seen.append(list(cmd))
        if any(fail_name in part for part in cmd):
            raise subprocess.CalledProcessError(1, list(cmd))

    with pytest.raises((subprocess.CalledProcessError, RuntimeError)):
        pipeline.run_pipeline(args, command_runner=runner, validate_files=False)
    return seen


def test_service_restarts_after_merge_failure(monkeypatch, tmp_path) -> None:
    """Service start is still recorded after a post-stop merge failure."""

    seen = _run_with_failure(monkeypatch, tmp_path, _args(tmp_path), "merge-staging-db.py")
    assert ["systemctl", "stop", "svc"] in seen
    assert ["systemctl", "start", "svc"] in seen


def test_skip_systemctl_suppresses_stop_start_on_failure(monkeypatch, tmp_path) -> None:
    """skip-systemctl suppresses service commands even on failures."""

    seen = _run_with_failure(
        monkeypatch, tmp_path, _args(tmp_path, skip_systemctl=True), "merge-staging-db.py"
    )
    assert all(cmd[0] != "systemctl" for cmd in seen)


def test_fail_before_merge_triggers_before_service_stop(monkeypatch, tmp_path) -> None:
    """The fail-before-merge hook still happens before stop/merge."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []
    with pytest.raises(RuntimeError, match="before merge"):
        pipeline.run_pipeline(
            _args(tmp_path, fail_before_merge=True),
            command_runner=lambda cmd, cwd: seen.append(list(cmd)),
            validate_files=False,
        )
    assert all(cmd[0] != "systemctl" for cmd in seen)


def test_fail_during_ann_build_restarts_service(monkeypatch, tmp_path) -> None:
    """The ANN failure hook runs after merge/popularity and restarts service."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []
    with pytest.raises(RuntimeError, match="ANN build"):
        pipeline.run_pipeline(
            _args(tmp_path, fail_during_ann_build=True),
            command_runner=lambda cmd, cwd: seen.append(list(cmd)),
            validate_files=False,
        )
    assert any("merge-staging-db.py" in part for cmd in seen for part in cmd)
    assert any("recompute-popularity.py" in part for cmd in seen for part in cmd)
    assert ["systemctl", "start", "svc"] in seen


def test_fail_after_merge_before_similarity_restarts_service(monkeypatch, tmp_path) -> None:
    """The post-ANN failure hook preserves start-in-finally behavior."""

    _patch_lightweight(monkeypatch)
    seen: list[list[str]] = []
    with pytest.raises(RuntimeError, match="after merge"):
        pipeline.run_pipeline(
            _args(tmp_path, fail_after_merge_before_similarity=True),
            command_runner=lambda cmd, cwd: seen.append(list(cmd)),
            validate_files=False,
        )
    assert any("build-ann-index.py" in part for cmd in seen for part in cmd)
    assert ["systemctl", "start", "svc"] in seen
