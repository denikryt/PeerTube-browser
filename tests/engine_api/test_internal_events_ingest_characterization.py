"""Characterize Engine /internal/events/ingest handler response behavior."""
from __future__ import annotations

from handlers.internal_events import handle_internal_events_ingest

from conftest import CapturingHandler


def _event(event_id: str = "evt-1") -> dict:
    """Build a valid Like event payload for handler-level ingest tests."""
    return {
        "event_id": event_id,
        "event_type": "Like",
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


def test_single_event_ingest_response_shape(engine_event_server) -> None:
    """A single valid event returns the current ok/count/results response contract."""
    handler = CapturingHandler(_event())

    handled = handle_internal_events_ingest(handler, engine_event_server)
    body = handler.parsed_body()

    assert handled is True
    assert handler.status == 200
    assert body["ok"] is True
    assert body["count"] == 1
    assert body["ingested"] == 1
    assert body["duplicates"] == 0
    assert body["results"] == [
        {"ok": True, "duplicate": False, "event_id": "evt-1", "event_type": "Like"}
    ]


def test_batch_ingest_reports_duplicate_counts(engine_event_server) -> None:
    """Batch ingest must preserve idempotent duplicate accounting in the response."""
    handler = CapturingHandler({"events": [_event(), _event()]})

    handle_internal_events_ingest(handler, engine_event_server)
    body = handler.parsed_body()

    assert handler.status == 200
    assert body["count"] == 2
    assert body["ingested"] == 1
    assert body["duplicates"] == 1


def test_empty_events_payload_is_rejected(engine_event_server) -> None:
    """Empty batch payloads currently produce a controlled Missing events error."""
    handler = CapturingHandler({"events": []})

    handle_internal_events_ingest(handler, engine_event_server)
    body = handler.parsed_body()

    assert handler.status == 400
    assert body == {"error": "Missing events"}
