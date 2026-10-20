"""Single-run lock helpers for the updater worker."""

from __future__ import annotations

import fcntl
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _pid_alive(pid: int) -> bool:
    """Preserve the wrapper's PID diagnostic API; it does not grant lock ownership."""
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
    """Hold a nonblocking POSIX lock through all updater work, then remove its file.

    PID text is diagnostic only: an empty file can belong to an active creator.
    Verify the locked inode is still named by the path before entering, because
    an earlier owner may have unlinked it after this process opened its handle.
    """

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                existing = os.pread(fd, 64, 0).decode("ascii", errors="replace").strip()
                raise RuntimeError(
                    f"Another updater-worker is already running (pid={existing or 'unknown'})"
                ) from None
            owned = os.fstat(fd)
            try:
                current = lock_path.stat()
            except FileNotFoundError:
                continue
            if (owned.st_dev, owned.st_ino) != (current.st_dev, current.st_ino):
                continue
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode("ascii"))
            try:
                yield
            finally:
                # Unlink while still locked. A waiter with the removed inode
                # must reopen and validate the replacement before it can enter.
                try:
                    current = lock_path.stat()
                    if (owned.st_dev, owned.st_ino) == (current.st_dev, current.st_ino):
                        lock_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    logging.warning("failed to remove updater lock: %s", lock_path)
            return
        finally:
            os.close(fd)
