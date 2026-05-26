"""Repository wrapper for Client-owned users and likes persistence."""
from __future__ import annotations

import sqlite3
from typing import Any

from lib import users_store


class UsersRepository:
    """Repository for Client-owned users and likes stored in SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Store the existing SQLite connection without changing ownership."""
        self.conn = conn

    def ensure_schema(self) -> None:
        """Create the current Client users schema if it is missing."""
        users_store.ensure_user_schema(self.conn)

    def get_or_create_user(self, user_id: str) -> None:
        """Ensure a local Client user row exists for the given user id."""
        users_store.get_or_create_user(self.conn, user_id)

    def record_like(self, user_id: str, video: dict[str, Any], max_likes: int) -> None:
        """Record or update one Client-owned like using existing store semantics."""
        users_store.record_like(self.conn, user_id, "like", video, max_likes)

    def remove_like(self, user_id: str, video_id: str, instance_domain: str) -> None:
        """Remove one Client-owned like by canonical Engine identity."""
        users_store.remove_like(self.conn, user_id, video_id, instance_domain)

    def clear_likes(self, user_id: str) -> None:
        """Remove all Client-owned likes for one local user."""
        users_store.clear_likes(self.conn, user_id)

    def fetch_recent_likes(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        """Return stored like identities in the current newest-first order."""
        return users_store.fetch_recent_likes(self.conn, user_id, limit)
