"""Define internal recommendation boundary types.

The dataclasses in this module document service and configuration boundaries
without becoming public HTTP schemas. Route adapters still emit primitive dicts
so frontend and Client contracts remain unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias

LayerName: TypeAlias = str
CandidateRow: TypeAlias = dict[str, Any]


@dataclass(frozen=True)
class ValidatedGeneratorConfig:
    """Describe validated metadata for one configured recommendation generator."""

    name: str
    enabled: bool
    gather_ratio: float
    mix_ratio: float
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class ValidatedProfileConfig:
    """Describe validated metadata for one recommendation profile."""

    name: str
    batch_size: int | None
    overfetch_factor: float
    generators: Mapping[str, ValidatedGeneratorConfig]
    mixing_order: tuple[str, ...]
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class ValidatedRecommendationConfig:
    """Describe validated recommendation configuration while retaining raw data."""

    default_profile: str | None
    profiles: Mapping[str, ValidatedProfileConfig]
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class RecommendationRequest:
    """Represent the internal route-to-service recommendation request boundary."""

    path: str
    method: str
    params: Mapping[str, list[str]]
    body: Mapping[str, Any] | None
    user_id: str
    limit: int
    mode: str | None
    debug: bool
    refresh: bool


@dataclass(frozen=True)
class RecommendationContext:
    """Represent per-request recommendation context produced by service parsing."""

    request_id: str
    user_id: str
    mode: str | None
    client_likes: tuple[Mapping[str, Any], ...]
    resolved_likes: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class RecommendationResult:
    """Adapt internal recommendation rows to the existing Engine response shape."""

    rows: tuple[Mapping[str, Any], ...]
    seed: Mapping[str, Any] | None
    generated_at: int
    total: int | None = None

    def to_response(self) -> dict[str, Any]:
        """Return the current primitive response contract without schema redesign."""
        row_list = [dict(row) for row in self.rows]
        return {
            "generatedAt": self.generated_at,
            "total": self.total if self.total is not None else len(row_list),
            "count": len(row_list),
            "seed": dict(self.seed) if self.seed is not None else None,
            "rows": row_list,
        }
