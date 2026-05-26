"""Runtime state for the FastAPI Client backend adapter.

This module keeps the dependencies that were historically stored on
the transitional stdlib server in one explicit object. The object is intentionally
small and behavior-neutral: it preserves current database, Engine gateway,
publish-mode, and rate-limit ownership while the HTTP framework changes.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from lib.http_utils import RateLimiter
from repositories.users import UsersRepository
from services.bridge_publisher import resolve_publish_mode


@dataclass
class ClientRuntimeState:
    """Dependencies shared by Client backend FastAPI route adapters."""

    user_db: sqlite3.Connection
    users: UsersRepository
    engine_ingest_base: str
    publish_mode: str
    rate_limiter: RateLimiter

    @classmethod
    def create(
        cls,
        user_db: sqlite3.Connection,
        engine_ingest_base: str,
        publish_mode: str,
        rate_limiter: RateLimiter,
    ) -> ClientRuntimeState:
        """Create state with the same normalization used by the legacy server."""
        users = UsersRepository(user_db)
        return cls(
            user_db=user_db,
            users=users,
            engine_ingest_base=engine_ingest_base.rstrip("/"),
            publish_mode=resolve_publish_mode(publish_mode),
            rate_limiter=rate_limiter,
        )
