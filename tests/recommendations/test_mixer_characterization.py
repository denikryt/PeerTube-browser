"""Characterize mixed recommendation strategy behavior."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from recommendations.mixer import MixerDeps, MixingRecommendationStrategy  # noqa: E402


class FixedGenerator:
    """Candidate generator that returns deterministic fixture rows."""

    def __init__(self, name: str, rows: list[dict[str, Any]]) -> None:
        """Store a name and fixture rows for strategy tests."""
        self.name = name
        self.rows = rows
        self.calls: list[int] = []

    def get_candidates(self, server: Any, user_id: str, limit: int, refresh_cache: bool = False, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Return copies of fixture rows while recording requested limits."""
        self.calls.append(limit)
        return [dict(row) for row in self.rows[:limit]]


def _like_key(entry: dict[str, Any]) -> str:
    """Build the same stable key for liked and candidate entries."""
    return f"{entry['video_id']}::{entry['instance_domain']}"


def test_mixing_strategy_respects_limits_soft_caps_seen_keys_and_debug_fields(monkeypatch) -> None:
    """Mixed output should preserve current scheduling and post-filter behavior."""
    monkeypatch.setattr("recommendations.mixer.now_ms", lambda: 1_000_000)
    exploit = FixedGenerator(
        "exploit",
        [
            {"video_id": "seen", "instance_domain": "example.org", "similarity_score": 1.0},
            {"video_id": "e1", "instance_domain": "example.org", "similarity_score": 0.9},
            {"video_id": "e2", "instance_domain": "example.org", "similarity_score": 0.8},
        ],
    )
    explore = FixedGenerator(
        "explore",
        [
            {"video_id": "x1", "instance_domain": "example.org", "similarity_score": 0.7},
            {"video_id": "x2", "instance_domain": "example.org", "similarity_score": 0.6},
        ],
    )
    config = {
        "profiles": {
            "home": {
                "batch_size": 4,
                "overfetch_factor": 1,
                "mixing": {"order": ["exploit", "explore"]},
                "generators": {
                    "exploit": {"enabled": True, "gather_ratio": 0.5, "mix_ratio": 0.5},
                    "explore": {"enabled": True, "gather_ratio": 0.5, "mix_ratio": 0.5},
                },
                "scoring": {"weights": {"similarity": 1.0}, "layer_weights": {}, "freshness_half_life_days": 10.0},
                "soft_caps": {"max": {"exploit": 1}},
            }
        },
        "default_profile": "home",
    }
    strategy = MixingRecommendationStrategy(
        {"exploit": exploit, "explore": explore},
        config,
        MixerDeps(_like_key, lambda _user_id, _max_likes: [{"video_id": "seen", "instance_domain": "example.org"}], 100),
    )

    rows = strategy.generate_recommendations(object(), "local-user", limit=4, mode="home")

    assert [row["video_id"] for row in rows] == ["x1", "e1", "x2"]
    assert rows[0]["debug_layer"] == "explore"
    assert rows[1]["debug_layer"] == "exploit"
    assert [row["debug_rank_after"] for row in rows] == [1, 2, 3]
    assert exploit.calls == [2]
    assert explore.calls == [2]


def test_mixing_strategy_returns_empty_when_request_limit_is_zero() -> None:
    """A zero recommendation limit currently produces no candidate work."""
    generator = FixedGenerator("random", [{"video_id": "v", "instance_domain": "example.org"}])
    strategy = MixingRecommendationStrategy(
        {"random": generator},
        {"profiles": {"home": {"generators": {"random": {"enabled": True}}}}, "default_profile": "home"},
        MixerDeps(_like_key, lambda _user_id, _max_likes: [], 100),
    )

    assert strategy.generate_recommendations(object(), "local-user", limit=0, mode="home") == []
    assert generator.calls == []
