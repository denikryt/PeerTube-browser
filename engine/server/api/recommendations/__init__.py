"""Provide recommendations runtime helpers."""

from __future__ import annotations

from typing import Any, Protocol


class RecommendationStrategy(Protocol):
    """Represent recommendation strategy behavior."""
    name: str

    def generate_recommendations(
        self,
        server: Any,
        user_id: str,
        limit: int,
        refresh_cache: bool = False,
        mode: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recommendation rows for a user."""
        raise NotImplementedError
