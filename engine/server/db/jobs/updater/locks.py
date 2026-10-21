"""Single-run lock helpers for the updater worker."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _pid_alive(pid: int) -> bool:
    """Return whether a process id appears alive using the current POSIX check."""

    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def single_run_lock(lock_path: Path) -> Iterator[None]:
    """Acquire the updater single-run lock and remove it on all exits."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            existing = int(lock_path.read_text().strip())
        except Exception:
            existing = -1
        if _pid_alive(existing):
            raise RuntimeError(
                f"Another updater-worker is already running (pid={existing})"
            ) from None
        logging.warning("removing stale updater lock pid=%s path=%s", existing, lock_path)
        lock_path.unlink(missing_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w") as fh:
        fh.write(str(pid))
    try:
        yield
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            logging.warning("failed to remove updater lock: %s", lock_path)
