from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from recommendations.sources import SimilarFromLikesSource


@dataclass(frozen=True)
class SimilarFromLikesDeps:
    source: SimilarFromLikesSource
    fallback_source: SimilarFromLikesSource | None = None
    fetch_random_rows_from_cache: Callable[[Any, int], list[dict[str, Any]]] | None = None
    fetch_random_rows: Callable[[Any, int], list[dict[str, Any]]] | None = None


class SimilarFromLikesGenerator:
    name = "likes"

    def __init__(self, deps: SimilarFromLikesDeps) -> None:
        self.deps = deps

    def get_candidates(
        self,
        server: Any,
        user_id: str,
        limit: int,
        refresh_cache: bool = False,
        config: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.deps.source.get_candidates(server, user_id, limit, refresh_cache)
        if rows or self.deps.fallback_source is None:
            return rows
        rows = self.deps.fallback_source.get_candidates(server, user_id, limit, refresh_cache)
        if rows:
            return rows
        if self.deps.fetch_random_rows_from_cache is not None:
            rows = self.deps.fetch_random_rows_from_cache(server, limit)
            if rows:
                return rows
        if self.deps.fetch_random_rows is None:
            return []
        if hasattr(server, "db_lock"):
            with server.db_lock:
                return self.deps.fetch_random_rows(server.db, limit)
        return self.deps.fetch_random_rows(server.db, limit)
