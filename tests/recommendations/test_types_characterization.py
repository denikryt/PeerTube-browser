"""Characterize internal recommendation boundary dataclasses."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from recommendations.debug import attach_debug_info  # noqa: E402
from recommendations.types import RecommendationRequest, RecommendationResult  # noqa: E402


def test_recommendation_request_preserves_route_service_fields() -> None:
    """The internal request object records current fields without schema redesign."""
    request = RecommendationRequest(
        path="/recommendations",
        method="POST",
        params={},
        body={"likes": [{"uuid": "uuid-1", "host": "example.org"}], "mode": "home"},
        user_id="local-user",
        limit=48,
        mode="home",
        debug=False,
        refresh=False,
    )

    assert request.path == "/recommendations"
    assert request.body == {"likes": [{"uuid": "uuid-1", "host": "example.org"}], "mode": "home"}
    assert request.user_id == "local-user"
    assert request.limit == 48
    assert request.debug is False


def test_recommendation_result_preserves_response_adapter_fields() -> None:
    """Result conversion emits the current primitive Engine response contract."""
    result = RecommendationResult(
        rows=({"video_id": "v1", "title": "Example"},),
        seed={"mode": "home"},
        generated_at=123,
    )

    assert result.to_response() == {
        "generatedAt": 123,
        "total": 1,
        "count": 1,
        "seed": {"mode": "home"},
        "rows": [{"video_id": "v1", "title": "Example"}],
    }


def test_recommendation_result_can_preserve_existing_embedding_total() -> None:
    """Route adapters can keep reporting total embeddings instead of row count."""
    result = RecommendationResult(
        rows=({"video_id": "v1"},),
        seed={"id": "seed"},
        generated_at=123,
        total=999,
    )

    assert result.to_response()["total"] == 999
    assert result.to_response()["count"] == 1


def test_debug_metadata_remains_dictionary_based_and_publicly_compatible() -> None:
    """Stage 5 leaves debug source dictionaries adaptable to current public keys."""
    rows = attach_debug_info(
        [{"video_id": "v1"}],
        [
            {
                "score": 0.9,
                "similarity_score": 0.8,
                "debug_layer": "exploit",
                "debug_rank_before": 1,
                "debug_rank_after": 1,
                "debug_profile": "home",
            }
        ],
    )

    assert rows[0]["debug"]["score"] == 0.9
    assert rows[0]["debug"]["similarity_score"] == 0.8
    assert rows[0]["debug"]["layer"] == "exploit"
    assert rows[0]["debug"]["profile"] == "home"
