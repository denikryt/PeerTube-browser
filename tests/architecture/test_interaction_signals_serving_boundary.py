"""Static regression boundary for interaction-signal serving reads."""
from __future__ import annotations

import inspect
from pathlib import Path

from engine.server.data import random_videos


def test_serving_candidate_helpers_do_not_read_interaction_signals() -> None:
    """Positive: current serving helpers derive ranking and displayed likes from canonical videos."""
    for function in (
        random_videos.fetch_popular_page,
        random_videos.fetch_random_rows,
        random_videos.fetch_popular_videos,
    ):
        assert "interaction_signals" not in inspect.getsource(function)


def test_interaction_storage_contract_remains_present() -> None:
    """Negative boundary: removing serving reads must not remove the persisted interaction schema."""
    root = Path(__file__).resolve().parents[2]
    sql = (root / "engine/server/db/migrations/main/0001_interaction_events.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS interaction_signals" in sql
