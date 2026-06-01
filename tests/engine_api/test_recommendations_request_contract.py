"""Characterize recommendation request parsing without importing FAISS-backed server."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))
sys.modules.pop("services", None)

from services import recommendation_service as rec_service  # noqa: E402


def test_recommendations_likes_payload_error_rejects_too_many_likes() -> None:
    """Oversized Client likes payloads must preserve the current 400 error body."""
    payload = {"likes": [{"uuid": str(index), "host": "example.org"} for index in range(3)]}

    error = rec_service._recommendations_likes_payload_error("/recommendations", payload, max_items=2)

    assert error == {
        "error": "Too many likes in request body",
        "code": "too_many_likes",
        "max_likes": 2,
        "max_allowed": 2,
        "received": 3,
    }


def test_recommendations_likes_payload_error_reports_invalid_entry_index_and_reason() -> None:
    """Malformed likes entries should report current reason and index."""
    not_object = rec_service._recommendations_likes_payload_error("/recommendations", {"likes": ["bad"]}, 10)
    missing_uuid = rec_service._recommendations_likes_payload_error("/recommendations", {"likes": [{"host": "example.org"}]}, 10)
    missing_host = rec_service._recommendations_likes_payload_error("/recommendations", {"likes": [{"uuid": "uuid"}]}, 10)

    assert not_object == {"error": "Invalid likes payload", "reason": "likes entry must be an object", "index": 0}
    assert missing_uuid == {"error": "Invalid likes payload", "reason": "likes.uuid must be a non-empty string", "index": 0}
    assert missing_host == {"error": "Invalid likes payload", "reason": "likes.host must be a non-empty string", "index": 0}


def test_parse_client_likes_normalizes_uuid_host_and_skips_invalid_items() -> None:
    """Client likes parsing keeps only valid uuid/host pairs in Engine field names."""
    likes = rec_service._parse_client_likes(
        {
            "likes": [
                {"uuid": " uuid-1 ", "host": " example.org "},
                {"uuid": "", "host": "example.org"},
                {"uuid": "uuid-2"},
                "bad",
            ]
        }
    )

    assert likes == [{"video_uuid": "uuid-1", "instance_domain": "example.org"}]
