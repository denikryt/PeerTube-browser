"""Tests for recommendations likes count limit handling."""

from __future__ import annotations

import io
import json
import sys
import types
import unittest
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


API_DIR = Path(__file__).resolve().parents[1]
SERVER_DIR = API_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

fake_ann = types.ModuleType("data.ann")
fake_ann.search_index = lambda *_args, **_kwargs: ([], [])
sys.modules.setdefault("data.ann", fake_ann)

from services import recommendation_service as rec_service  # noqa: E402
from server_config import DEFAULT_CLIENT_LIKES_MAX  # noqa: E402


class _DummyHandler:
    """Minimal handler double used to call recommendation service behavior."""

    def __init__(self, path: str, body: dict) -> None:
        """Initialize the test handler with route path and JSON request body."""
        self.path = path
        raw = json.dumps(body).encode("utf-8")
        self.rfile = io.BytesIO(raw)
        self.wfile = io.BytesIO()
        self.headers = Message()
        self.headers["content-length"] = str(len(raw))
        self.status: int | None = None
        self.response_headers: list[tuple[str, str]] = []

    def send_response(self, status: int) -> None:
        """Capture the response status sent by respond_json."""
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        """Capture response headers for handler compatibility."""
        self.response_headers.append((key, value))

    def end_headers(self) -> None:
        """Keep BaseHTTPRequestHandler response compatibility."""
        return

    def parsed_body(self) -> dict:
        """Return the JSON body written by the service."""
        self.wfile.seek(0)
        return json.loads(self.wfile.read().decode("utf-8"))


class RecommendationsLikesLimitTests(unittest.TestCase):
    """Validate explicit 400 contract for oversized recommendations likes payloads."""

    def test_recommendations_rejects_more_likes_than_allowed(self) -> None:
        """Return 400 with machine-readable fields when likes exceed configured max."""
        over_limit = DEFAULT_CLIENT_LIKES_MAX + 1
        body = {
            "likes": [
                {"uuid": f"video-{idx}", "host": "example.com"} for idx in range(over_limit)
            ]
        }
        handler = _DummyHandler("/recommendations", body)
        server = SimpleNamespace(use_client_likes=True)

        rec_service.handle_similar_request(handler, server, "/recommendations", "POST", {})

        self.assertEqual(handler.status, 400)
        self.assertEqual(
            handler.parsed_body(),
            {
                "error": "Too many likes in request body",
                "max_allowed": DEFAULT_CLIENT_LIKES_MAX,
                "received": over_limit,
            },
        )

    def test_recommendations_allows_likes_at_limit(self) -> None:
        """Keep existing flow unchanged when likes count is within allowed maximum."""
        at_limit = DEFAULT_CLIENT_LIKES_MAX
        body = {
            "likes": [
                {"uuid": f"video-{idx}", "host": "example.com"} for idx in range(at_limit)
            ]
        }
        handler = _DummyHandler("/recommendations", body)
        server = SimpleNamespace(use_client_likes=True)
        with (
            patch.object(rec_service, "_parse_client_likes", return_value=[]) as parse_likes,
            patch.object(rec_service, "_resolve_client_likes", return_value=[]),
            patch.object(rec_service, "set_request_client_likes") as set_likes,
            patch.object(rec_service, "clear_request_context") as clear_context,
            patch.object(rec_service, "handle_similar") as handle_similar,
        ):
            rec_service.handle_similar_request(handler, server, "/recommendations", "POST", {})

        parse_likes.assert_called_once_with(body)
        set_likes.assert_called_once_with([], True)
        handle_similar.assert_called_once_with(handler, server, {})
        clear_context.assert_called_once()
        self.assertIsNone(handler.status)

    def test_recommendations_rejects_invalid_likes_item_format(self) -> None:
        """Return 400 when likes item has invalid uuid/host format."""
        body = {"likes": [{"uuid": "   ", "host": "example.com"}]}
        handler = _DummyHandler("/recommendations", body)
        server = SimpleNamespace(use_client_likes=True)
        with (
            patch.object(rec_service, "set_request_client_likes") as set_likes,
            patch.object(rec_service, "clear_request_context") as clear_context,
        ):
            rec_service.handle_similar_request(handler, server, "/recommendations", "POST", {})

        self.assertEqual(handler.status, 400)
        self.assertEqual(
            handler.parsed_body(),
            {
                "error": "Invalid likes payload",
                "reason": "likes.uuid must be a non-empty string",
                "index": 0,
            },
        )
        set_likes.assert_not_called()
        clear_context.assert_not_called()


if __name__ == "__main__":
    unittest.main()
