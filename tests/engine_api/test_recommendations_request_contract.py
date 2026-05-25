"""Characterize recommendation request parsing without importing FAISS-backed server."""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))


def _similar_module():
    """Import handlers.similar with a fake data.ann module to avoid FAISS dependency."""
    fake_ann = types.ModuleType("data.ann")
    fake_ann.search_index = lambda *_args, **_kwargs: []
    sys.modules["data.ann"] = fake_ann
    sys.modules.pop("handlers.similar", None)
    return importlib.import_module("handlers.similar")


def test_recommendations_likes_payload_error_rejects_too_many_likes() -> None:
    """Oversized Client likes payloads must preserve the current 400 error body."""
    similar = _similar_module()
    payload = {"likes": [{"uuid": str(index), "host": "example.org"} for index in range(3)]}

    error = similar._recommendations_likes_payload_error("/recommendations", payload, max_items=2)

    assert error == {"error": "Too many likes in request body", "max_allowed": 2, "received": 3}


def test_recommendations_likes_payload_error_reports_invalid_entry_index_and_reason() -> None:
    """Malformed likes entries should report current reason and index."""
    similar = _similar_module()

    not_object = similar._recommendations_likes_payload_error("/recommendations", {"likes": ["bad"]}, 10)
    missing_uuid = similar._recommendations_likes_payload_error("/recommendations", {"likes": [{"host": "example.org"}]}, 10)
    missing_host = similar._recommendations_likes_payload_error("/recommendations", {"likes": [{"uuid": "uuid"}]}, 10)

    assert not_object == {"error": "Invalid likes payload", "reason": "likes entry must be an object", "index": 0}
    assert missing_uuid == {"error": "Invalid likes payload", "reason": "likes.uuid must be a non-empty string", "index": 0}
    assert missing_host == {"error": "Invalid likes payload", "reason": "likes.host must be a non-empty string", "index": 0}


def test_parse_client_likes_normalizes_uuid_host_and_skips_invalid_items() -> None:
    """Client likes parsing keeps only valid uuid/host pairs in Engine field names."""
    similar = _similar_module()

    likes = similar._parse_client_likes(
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
