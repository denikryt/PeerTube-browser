"""Provide scoring runtime helpers."""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from typing import Any, Iterable

from data.time import now_ms


@dataclass(frozen=True)
class ScoringSettings:
    """Represent scoring settings behavior."""
    similarity_weight: float
    freshness_weight: float
    popularity_weight: float
    layer_weights: dict[str, float]
    freshness_half_life_days: float
    popularity_view_weight: float
    popularity_like_weight: float


def build_scoring_settings(config: dict[str, Any]) -> ScoringSettings:
    """Handle build scoring settings."""
    scoring = config.get("scoring", {})
    weights = scoring.get("weights", {})
    popularity = scoring.get("popularity", {})
    return ScoringSettings(
        similarity_weight=float(weights.get("similarity", 1.0)),
        freshness_weight=float(weights.get("freshness", 0.0)),
        popularity_weight=float(weights.get("popularity", 0.0)),
        layer_weights={str(k): float(v) for k, v in (scoring.get("layer_weights") or {}).items()},
        freshness_half_life_days=float(scoring.get("freshness_half_life_days", 14.0)),
        popularity_view_weight=float(popularity.get("views", 1.0)),
        popularity_like_weight=float(popularity.get("likes", 2.0)),
    )


def score_candidate(
    candidate: dict[str, Any],
    settings: ScoringSettings,
    layer_name: str | None = None,
    now_ms_value: int | None = None,
) -> float:
    """Handle score candidate."""
    if now_ms_value is None:
        now_ms_value = now_ms()
    similarity = _extract_similarity(candidate)
    freshness = _freshness_score(candidate.get("published_at"), now_ms_value, settings)
    popularity = _popularity_score(candidate.get("views"), candidate.get("likes"), settings)
    layer_bonus = settings.layer_weights.get(layer_name or "", 0.0)
    score = (
        (settings.similarity_weight * similarity)
        + (settings.freshness_weight * freshness)
        + (settings.popularity_weight * popularity)
        + layer_bonus
    )
    candidate["similarity_score"] = similarity
    candidate["score"] = score
    candidate["debug_freshness_score"] = freshness
    candidate["debug_popularity_score"] = popularity
    if layer_name is not None:
        candidate["debug_layer"] = layer_name
    return score


def rank_scored_candidates(
    candidates: list[tuple[str | None, dict[str, Any]]],
    config: dict[str, Any],
    size: int | None = None,
) -> list[tuple[str | None, dict[str, Any]]]:
    """Rank scored candidates with optional explore/exploit mixing."""
    if not candidates:
        return []
    candidates = list(candidates)
    candidates.sort(key=lambda item: float(item[1].get("score") or 0.0), reverse=True)
    for index, item in enumerate(candidates):
        item[1]["debug_rank_before"] = index + 1
    explore_cfg = config.get("explore", {})
    explore_ratio = float(explore_cfg.get("ratio") or 0.0)
    explore_min = float(explore_cfg.get("similarity_min", 0.0))
    explore_max = float(explore_cfg.get("similarity_max", 1.0))
    jitter_window = int(explore_cfg.get("jitter_window") or 0)

    similarity_values: list[float] = []
    for _, candidate in candidates:
        raw_similarity = candidate.get("similarity_score")
        try:
            similarity = float(raw_similarity)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(similarity):
            continue
        similarity_values.append(similarity)

    similarity_pool_min = min(similarity_values) if similarity_values else None
    similarity_pool_max = max(similarity_values) if similarity_values else None

    logging.info(
        "[recommendations] similarity pool: min=%s max=%s count=%d",
        f"{similarity_pool_min:.6f}" if similarity_pool_min is not None else "n/a",
        f"{similarity_pool_max:.6f}" if similarity_pool_max is not None else "n/a",
        len(similarity_values),
    )

    for _, candidate in candidates:
        candidate["debug_explore_min"] = explore_min
        candidate["debug_explore_max"] = explore_max
        candidate["debug_similarity_pool_min"] = similarity_pool_min
        candidate["debug_similarity_pool_max"] = similarity_pool_max

    if explore_ratio <= 0.0:
        for item in candidates:
            item[1]["debug_bucket"] = "exploit"
            item[1]["debug_explore_empty"] = False
        return _apply_jitter(candidates, jitter_window)

    explore_pool: list[tuple[str | None, dict[str, Any]]] = []
    exploit_pool: list[tuple[str | None, dict[str, Any]]] = []
    for item in candidates:
        similarity = item[1].get("similarity_score")
        if similarity is not None and explore_min <= float(similarity) < explore_max:
            item[1]["debug_bucket"] = "explore"
            item[1]["debug_explore_empty"] = False
            explore_pool.append(item)
        else:
            item[1]["debug_bucket"] = "exploit"
            item[1]["debug_explore_empty"] = False
            exploit_pool.append(item)

    if not explore_pool and similarity_values:
        logging.warning(
            "[recommendations] explore pool empty: similarity_min=%.4f similarity_max=%.4f pool_min=%.4f pool_max=%.4f",
            explore_min,
            explore_max,
            similarity_pool_min if similarity_pool_min is not None else float("nan"),
            similarity_pool_max if similarity_pool_max is not None else float("nan"),
        )
        for item in candidates:
            item[1]["debug_explore_empty"] = True

    explore_pool = _apply_jitter(explore_pool, jitter_window)
    exploit_pool = _apply_jitter(exploit_pool, jitter_window)
    limit = size if size is not None and size > 0 else len(candidates)
    return _mix_by_ratio(explore_pool, exploit_pool, explore_ratio, limit)


def score_and_rank_list(
    candidates: list[dict[str, Any]],
    config: dict[str, Any],
    layer_name: str | None = None,
    now_ms_value: int | None = None,
) -> list[dict[str, Any]]:
    """Handle score and rank list."""
    if not candidates:
        return []
    settings = build_scoring_settings(config)
    if now_ms_value is None:
        now_ms_value = now_ms()
    scored: list[tuple[str | None, dict[str, Any]]] = []
    for candidate in candidates:
        score_candidate(candidate, settings, layer_name=layer_name, now_ms_value=now_ms_value)
        scored.append((layer_name, candidate))
    ranked = rank_scored_candidates(scored, config, size=len(scored))
    for index, item in enumerate(ranked):
        item[1]["debug_rank_after"] = index + 1
    return [item[1] for item in ranked]


def _extract_similarity(candidate: dict[str, Any]) -> float:
    """Handle extract similarity."""
    raw = candidate.get("similarity_score")
    if raw is None:
        raw = candidate.get("score")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0
    if not math.isfinite(value):
        return 0.0
    if value < 0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _freshness_score(
    published_at: int | None, now_ms_value: int, settings: ScoringSettings
) -> float:
    """Handle freshness score."""
    if not published_at:
        return 0.0
    age_ms = max(now_ms_value - int(published_at), 0)
    age_days = age_ms / (1000 * 60 * 60 * 24)
    half_life = settings.freshness_half_life_days
    if half_life <= 0:
        return 0.0
    return 0.5 ** (age_days / half_life)


def _popularity_score(
    views: int | None, likes: int | None, settings: ScoringSettings
) -> float:
    """Handle popularity score."""
    view_count = max(int(views or 0), 0)
    like_count = max(int(likes or 0), 0)
    weighted = (
        settings.popularity_view_weight * view_count
        + settings.popularity_like_weight * like_count
    )
    if weighted <= 0:
        return 0.0
    scaled = math.log1p(weighted)
    return scaled / (scaled + 1.0)


def _apply_jitter(
    items: list[tuple[str | None, dict[str, Any]]], window: int
) -> list[tuple[str | None, dict[str, Any]]]:
    """Handle apply jitter."""
    if window <= 1 or len(items) <= 1:
        return list(items)
    jittered: list[tuple[str | None, dict[str, Any]]] = []
    for index in range(0, len(items), window):
        chunk = list(items[index : index + window])
        random.shuffle(chunk)
        jittered.extend(chunk)
    return jittered


def _mix_by_ratio(
    explore_pool: Iterable[tuple[str | None, dict[str, Any]]],
    exploit_pool: Iterable[tuple[str | None, dict[str, Any]]],
    ratio: float,
    limit: int,
) -> list[tuple[str | None, dict[str, Any]]]:
    """Handle mix by ratio."""
    if ratio <= 0:
        return list(exploit_pool)[:limit]
    if ratio >= 1:
        return list(explore_pool)[:limit]

    explore_list = list(explore_pool)
    exploit_list = list(exploit_pool)
    output: list[tuple[str | None, dict[str, Any]]] = []
    explore_idx = 0
    exploit_idx = 0
    while len(output) < limit and (explore_idx < len(explore_list) or exploit_idx < len(exploit_list)):
        desired_explore = int(round((len(output) + 1) * ratio))
        if explore_idx < len(explore_list) and desired_explore > explore_idx:
            output.append(explore_list[explore_idx])
            explore_idx += 1
            continue
        if exploit_idx < len(exploit_list):
            output.append(exploit_list[exploit_idx])
            exploit_idx += 1
            continue
        if explore_idx < len(explore_list):
            output.append(explore_list[explore_idx])
            explore_idx += 1
    return output
