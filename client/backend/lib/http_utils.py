"""Non-response utility helpers for the Client backend."""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone

DEFAULT_USER_ID = "local-user"


def resolve_user_id(raw: str | None) -> str:
    """Normalize user id input and fall back to the default id."""
    if isinstance(raw, str):
        value = raw.strip()
        if value:
            return value
    return DEFAULT_USER_ID


class RateLimiter:
    """Simple in-memory rate limiter by key and time window."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        """Initialize the rate limiter with a maximum request count per window."""
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.lock = threading.Lock()
        self.requests: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Return whether one request for ``key`` is allowed in the current window."""
        if self.max_requests <= 0 or self.window_seconds <= 0:
            return True
        now = datetime.now(timezone.utc).timestamp()
        with self.lock:
            bucket = self.requests.get(key)
            if bucket is None:
                bucket = deque()
                self.requests[key] = bucket
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True
