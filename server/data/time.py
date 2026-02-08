from __future__ import annotations

from datetime import datetime, timezone


def now_ms() -> int:
    """Return current UTC timestamp in milliseconds."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)
