"""Characterization tests for updater lock behavior."""

from __future__ import annotations

import pytest

from engine.server.db.jobs.updater import locks


def test_active_lock_raises(monkeypatch, tmp_path) -> None:
    """An active pid lock blocks a second updater run."""

    lock = tmp_path / "worker.lock"
    lock.write_text("123", encoding="utf-8")
    monkeypatch.setattr(locks, "_pid_alive", lambda pid: True)
    with pytest.raises(RuntimeError, match="already running"):
        with locks.single_run_lock(lock):
            pass


def test_stale_lock_is_replaced_and_removed(monkeypatch, tmp_path) -> None:
    """A stale pid lock is replaced and removed on context exit."""

    lock = tmp_path / "worker.lock"
    lock.write_text("123", encoding="utf-8")
    monkeypatch.setattr(locks, "_pid_alive", lambda pid: False)
    with locks.single_run_lock(lock):
        assert lock.exists()
    assert not lock.exists()


def test_lock_removed_after_exception(tmp_path) -> None:
    """Lock cleanup must happen even when the updater body fails."""

    lock = tmp_path / "worker.lock"
    with pytest.raises(ValueError):
        with locks.single_run_lock(lock):
            assert lock.exists()
            raise ValueError("boom")
    assert not lock.exists()
