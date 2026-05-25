"""Characterize Engine interaction event deduplication and signal aggregation."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.interaction_events import ensure_interaction_event_schema, ingest_interaction_event  # noqa: E402


def _connect() -> sqlite3.Connection:
    """Create a row-aware in-memory database for Engine event tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_interaction_event_schema(conn)
    return conn


def _event(event_id: str = "evt-like-1", event_type: str = "Like") -> dict:
    """Build a valid event payload while letting individual tests vary type/id."""
    return {
        "event_id": event_id,
        "event_type": event_type,
        "actor_id": "user-1",
        "object": {
            "video_uuid": "uuid-1",
            "instance_domain": "example.org",
            "canonical_url": "https://example.org/videos/watch/uuid-1",
        },
        "published_at": 1739700000000,
        "source_instance": "example.org",
        "raw_payload": {"source": "test"},
    }


def test_duplicate_event_id_does_not_double_count_like_signal() -> None:
    """A duplicate raw event must be accepted as duplicate without incrementing counters."""
    conn = _connect()

    first = ingest_interaction_event(conn, _event())
    second = ingest_interaction_event(conn, _event())

    raw_count = conn.execute("SELECT COUNT(*) FROM interaction_raw_events").fetchone()[0]
    signal = conn.execute("SELECT likes_count FROM interaction_signals").fetchone()
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert raw_count == 1
    assert signal["likes_count"] == 1


def test_undo_like_without_existing_like_records_current_negative_like_count() -> None:
    """Current first UndoLike behavior records a negative like count while clamping score."""
    conn = _connect()

    result = ingest_interaction_event(conn, _event("evt-undo-1", "UndoLike"))

    signal = conn.execute(
        "SELECT likes_count, undo_likes_count, signal_score FROM interaction_signals"
    ).fetchone()
    assert result["duplicate"] is False
    assert signal["likes_count"] == -1
    assert signal["undo_likes_count"] == 1
    assert signal["signal_score"] == -1.0


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"event_type": "Like", "object": {}}, "Missing event_id"),
        ({"event_id": "evt", "event_type": "Bad", "object": {}}, "Unsupported event_type"),
        ({"event_id": "evt", "event_type": "Like"}, "Missing object"),
        ({"event_id": "evt", "event_type": "Like", "object": {"instance_domain": "example.org"}}, "Missing object.video_uuid"),
        ({"event_id": "evt", "event_type": "Like", "object": {"video_uuid": "uuid"}}, "Missing object.instance_domain"),
    ],
)
def test_invalid_payloads_raise_current_value_errors(payload: dict, message: str) -> None:
    """Validation errors are part of current ingest behavior and guard refactors."""
    conn = _connect()

    with pytest.raises(ValueError, match=message):
        ingest_interaction_event(conn, payload)
