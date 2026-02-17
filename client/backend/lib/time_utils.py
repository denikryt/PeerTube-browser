"""Time helpers for Client backend."""
from __future__ import annotations

from time import time


def now_ms() -> int:
    """Return current unix timestamp in milliseconds."""
    return int(time() * 1000)
