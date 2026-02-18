"""Provide request context runtime helpers."""

import threading
from typing import Any

_REQUEST_CONTEXT = threading.local()


def set_request_client_likes(likes: list[dict[str, Any]] | None, use_client: bool) -> None:
    """Handle set request client likes."""
    _REQUEST_CONTEXT.client_likes = likes if use_client else []
    _REQUEST_CONTEXT.use_client_likes = bool(use_client)


def set_request_id(request_id: str | None) -> None:
    """Store request id in thread-local context for logging correlation."""
    value = (request_id or "").strip()
    if value:
        _REQUEST_CONTEXT.request_id = value
        return
    if hasattr(_REQUEST_CONTEXT, "request_id"):
        delattr(_REQUEST_CONTEXT, "request_id")


def fetch_request_id() -> str | None:
    """Return the current request id from thread-local context when set."""
    value = getattr(_REQUEST_CONTEXT, "request_id", None)
    if not isinstance(value, str) or not value:
        return None
    return value


def clear_request_context() -> None:
    """Handle clear request-scoped likes and request id context."""
    if hasattr(_REQUEST_CONTEXT, "client_likes"):
        delattr(_REQUEST_CONTEXT, "client_likes")
    if hasattr(_REQUEST_CONTEXT, "use_client_likes"):
        delattr(_REQUEST_CONTEXT, "use_client_likes")
    if hasattr(_REQUEST_CONTEXT, "request_id"):
        delattr(_REQUEST_CONTEXT, "request_id")


def fetch_recent_likes_request(user_id: str, limit: int) -> list[dict[str, Any]]:
    """Return request-scoped likes only (no Engine users DB fallback)."""
    use_client = bool(getattr(_REQUEST_CONTEXT, "use_client_likes", False))
    if not use_client:
        return []
    likes = getattr(_REQUEST_CONTEXT, "client_likes", None) or []
    if limit <= 0:
        return list(likes)
    return list(likes)[:limit]
