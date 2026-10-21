"""Characterize recommendation scoring and ranking helpers."""
from __future__ import annotations

import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from recommendations.scoring import (  # noqa: E402
    ScoringSettings,
    rank_scored_candidates,
    score_and_rank_list,
    score_candidate,
)


def _settings() -> ScoringSettings:
    """Return fixed settings that make each score component observable."""
    return ScoringSettings(
        similarity_weight=1.0,
        freshness_weight=0.5,
        popularity_weight=0.25,
        layer_weights={"exploit": 0.1},
        freshness_half_life_days=10.0,
        popularity_view_weight=1.0,
        popularity_like_weight=2.0,
    )


def test_score_candidate_clamps_similarity_and_adds_debug_components() -> None:
    """Scoring mutates candidates with current score/debug fields used downstream."""
    candidate = {
        "video_id": "v1",
        "similarity_score": 1.2,
        "published_at": 1_000_000,
        "views": 1000,
        "likes": 10,
    }
    now = 1_000_000 + 10 * 86_400_000

    score = score_candidate(candidate, _settings(), layer_name="exploit", now_ms_value=now)

    expected_popularity = math.log1p(1020) / (math.log1p(1020) + 1.0)
    expected = 1.0 + (0.5 * 0.5) + (0.25 * expected_popularity) + 0.1
    assert candidate["similarity_score"] == 1.0
    assert candidate["debug_freshness_score"] == 0.5
    assert candidate["debug_popularity_score"] == expected_popularity
    assert candidate["debug_layer"] == "exploit"
    assert candidate["score"] == score
    assert score == expected


def test_score_and_rank_list_orders_by_score_and_sets_rank_debug_fields() -> None:
    """Current ranking sorts by computed score and annotates before/after ranks."""
    rows = [
        {"video_id": "low", "similarity_score": 0.1, "published_at": 1, "views": 0, "likes": 0},
        {"video_id": "high", "similarity_score": 0.9, "published_at": 1, "views": 0, "likes": 0},
    ]
    config = {"scoring": {"weights": {"similarity": 1.0}, "layer_weights": {}, "freshness_half_life_days": 10.0}, "explore": {"ratio": 0.0}}

    ranked = score_and_rank_list(rows, config, layer_name="home", now_ms_value=1)

    assert [row["video_id"] for row in ranked] == ["high", "low"]
    assert [row["debug_bucket"] for row in ranked] == ["exploit", "exploit"]
    assert [row["debug_rank_after"] for row in ranked] == [1, 2]


def test_rank_scored_candidates_mixes_explore_and_exploit_by_current_ratio() -> None:
    """Explore ratio currently interleaves candidates selected by similarity range."""
    candidates = [
        ("layer", {"video_id": "exploit-1", "score": 10.0, "similarity_score": 0.95}),
        ("layer", {"video_id": "explore-1", "score": 9.0, "similarity_score": 0.50}),
        ("layer", {"video_id": "exploit-2", "score": 8.0, "similarity_score": 0.90}),
        ("layer", {"video_id": "explore-2", "score": 7.0, "similarity_score": 0.40}),
    ]
    config = {"explore": {"ratio": 0.5, "similarity_min": 0.3, "similarity_max": 0.7, "jitter_window": 0}}

    ranked = rank_scored_candidates(candidates, config, size=4)

    assert [item[1]["video_id"] for item in ranked] == ["exploit-1", "explore-1", "explore-2", "exploit-2"]
    assert [item[1]["debug_bucket"] for item in ranked] == ["exploit", "explore", "explore", "exploit"]
