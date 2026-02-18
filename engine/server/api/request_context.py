"""Provide request context runtime helpers."""

import threading
from typing import Any

_REQUEST_CONTEXT = threading.local()


def set_request_client_likes(likes: list[dict[str, Any]] | None, use_client: bool) -> None:
    """Handle set request client likes."""
    _REQUEST_CONTEXT.client_likes = likes if use_client else []
    _REQUEST_CONTEXT.use_client_likes = bool(use_client)


def clear_request_context() -> None:
    """Handle clear request context."""
    if hasattr(_REQUEST_CONTEXT, "client_likes"):
        delattr(_REQUEST_CONTEXT, "client_likes")
    if hasattr(_REQUEST_CONTEXT, "use_client_likes"):
        delattr(_REQUEST_CONTEXT, "use_client_likes")


def fetch_recent_likes_request(user_id: str, limit: int) -> list[dict[str, Any]]:
    """Return request-scoped likes only (no Engine users DB fallback)."""
    use_client = bool(getattr(_REQUEST_CONTEXT, "use_client_likes", False))
    if not use_client:
        return []
    likes = getattr(_REQUEST_CONTEXT, "client_likes", None) or []
    if limit <= 0:
        return list(likes)
    return list(likes)[:limit]
