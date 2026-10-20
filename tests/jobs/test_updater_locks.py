"""Characterization tests for updater lock behavior."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine.server.db.jobs.updater import locks


PROJECT = Path(__file__).resolve().parents[2]


def _child(lock, body):
    """Start a separate updater-lock participant with an explicit pipe barrier."""
    code = "import os,sys\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom engine.server.db.jobs.updater import locks\nlock=Path(sys.argv[2])\n" + body
    return subprocess.Popen([sys.executable, "-c", code, str(PROJECT), str(lock)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def _release(child):
    """Always release a barrier and reap the process after an assertion failure."""
    if child.poll() is None:
        try:
            child.stdin.write("\n")
            child.stdin.flush()
        except BrokenPipeError:
            pass
    stdout, stderr = child.communicate(timeout=10)
    assert child.returncode == 0, (stdout, stderr)


def test_active_lock_raises(tmp_path) -> None:
    """An actual process holding the kernel lock blocks a second updater run."""
    lock = tmp_path / "worker.lock"
    child = _child(lock, "with locks.single_run_lock(lock):\n print('HELD',flush=True)\n sys.stdin.readline()\n")
    try:
        assert child.stdout.readline().strip() == "HELD"
        with pytest.raises(RuntimeError, match="already running"):
            with locks.single_run_lock(lock):
                pytest.fail("Two updaters entered the protected region")
    finally:
        _release(child)


def test_stale_lock_is_replaced_and_removed(tmp_path) -> None:
    """Unowned PID text cannot block an updater; its file is cleaned on exit."""

    lock = tmp_path / "worker.lock"
    lock.write_text("123", encoding="utf-8")
    with locks.single_run_lock(lock):
        assert lock.exists()
        assert lock.read_text() == str(os.getpid())
    assert not lock.exists()


def test_creator_before_pid_write_cannot_be_mistaken_for_stale_lock(tmp_path):
    """Pausing the active creator with an empty file must not admit a sibling."""
    lock = tmp_path / "worker.lock"
    body = """
actual_write=locks.os.write
actual_fdopen=locks.os.fdopen
def pause_write(*args,**kwargs):
 print('EMPTY',flush=True)
 sys.stdin.readline()
 return actual_write(*args,**kwargs)
def pause_fdopen(*args,**kwargs):
 print('EMPTY',flush=True)
 sys.stdin.readline()
 return actual_fdopen(*args,**kwargs)
locks.os.write=pause_write
locks.os.fdopen=pause_fdopen
with locks.single_run_lock(lock):
 print('ENTERED',flush=True)
"""
    child = _child(lock, body)
    try:
        assert child.stdout.readline().strip() == "EMPTY"
        assert lock.read_text() == ""
        with pytest.raises(RuntimeError, match="already running"):
            with locks.single_run_lock(lock):
                pytest.fail("Empty active lock was incorrectly reclaimed")
    finally:
        _release(child)


def test_opened_previous_inode_cannot_bypass_a_replacement_lock(tmp_path):
    """A delayed opener must revalidate the pathname after the old owner exits."""
    lock = tmp_path / "worker.lock"
    body = """
actual=locks.os.open
first=True
def pause_open(*args,**kwargs):
 global first
 fd=actual(*args,**kwargs)
 if first:
  first=False
  print('OPENED',flush=True)
  sys.stdin.readline()
 return fd
locks.os.open=pause_open
try:
 with locks.single_run_lock(lock):
  print('ENTERED',flush=True)
except RuntimeError:
 print('REJECTED',flush=True)
"""
    child = None
    try:
        with locks.single_run_lock(lock):
            child = _child(lock, body)
            assert child.stdout.readline().strip() == "OPENED"
        with locks.single_run_lock(lock):
            child.stdin.write("\n")
            child.stdin.flush()
            assert child.stdout.readline().strip() == "REJECTED"
    finally:
        if child is not None:
            _release(child)


def test_lock_removed_after_exception(tmp_path) -> None:
    """Lock cleanup must happen even when the updater body fails."""

    lock = tmp_path / "worker.lock"
    with pytest.raises(ValueError):
        with locks.single_run_lock(lock):
            assert lock.exists()
            raise ValueError("boom")
    assert not lock.exists()
