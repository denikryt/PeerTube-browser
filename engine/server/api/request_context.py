import threading
from typing import Any
import sqlite3

from data.users import fetch_recent_likes

_REQUEST_CONTEXT = threading.local()


def set_request_client_likes(likes: list[dict[str, Any]] | None, use_client: bool) -> None:
    _REQUEST_CONTEXT.client_likes = likes if use_client else None
    _REQUEST_CONTEXT.use_client_likes = bool(use_client)


def clear_request_context() -> None:
    if hasattr(_REQUEST_CONTEXT, "client_likes"):
        delattr(_REQUEST_CONTEXT, "client_likes")
    if hasattr(_REQUEST_CONTEXT, "use_client_likes"):
        delattr(_REQUEST_CONTEXT, "use_client_likes")


def fetch_recent_likes_request(
    conn: sqlite3.Connection, user_id: str, limit: int
) -> list[dict[str, Any]]:
    use_client = bool(getattr(_REQUEST_CONTEXT, "use_client_likes", False))
    if use_client:
        likes = getattr(_REQUEST_CONTEXT, "client_likes", None) or []
        if limit <= 0:
            return list(likes)
        return list(likes)[:limit]
    return fetch_recent_likes(conn, user_id, limit)
