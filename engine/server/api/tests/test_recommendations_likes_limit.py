"""Tests for recommendations likes count limit handling."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


API_DIR = Path(__file__).resolve().parents[1]
SERVER_DIR = API_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from handlers import similar  # noqa: E402


class _DummySimilarHandler:
    """Minimal handler double used to call SimilarHandler methods in isolation."""

    def __init__(self, path: str) -> None:
        """Initialize the test handler with route path and basic request fields."""
        self.path = path
        self.headers = {"content-length": "128"}
        self.server = SimpleNamespace(use_client_likes=True)
        self.handled = False

    def _rate_limit_check(self, _path: str) -> bool:
        """Allow all requests for tests."""
        return True

    def _handle_similar(self, _params: dict[str, list[str]]) -> None:
        """Mark request as handled without touching real recommendation logic."""
        self.handled = True


class RecommendationsLikesLimitTests(unittest.TestCase):
    """Validate explicit 400 contract for oversized recommendations likes payloads."""

    def test_recommendations_rejects_more_likes_than_allowed(self) -> None:
        """Return 400 with machine-readable fields when likes exceed configured max."""
        over_limit = similar.DEFAULT_CLIENT_LIKES_MAX + 1
        body = {
            "likes": [
                {"uuid": f"video-{idx}", "host": "example.com"} for idx in range(over_limit)
            ]
        }
        handler = _DummySimilarHandler("/recommendations")
        with (
            patch.object(similar, "read_json_body", return_value=body),
            patch.object(similar, "respond_json") as respond_json_mock,
            patch.object(similar, "set_request_client_likes") as set_likes_mock,
            patch.object(similar, "clear_request_context") as clear_context_mock,
        ):
            similar.SimilarHandler._handle_similar_request(handler, method="POST")

        respond_json_mock.assert_called_once_with(
            handler,
            400,
            {
                "error": "Too many likes in request body",
                "max_allowed": similar.DEFAULT_CLIENT_LIKES_MAX,
                "received": over_limit,
            },
        )
        set_likes_mock.assert_not_called()
        clear_context_mock.assert_not_called()
        self.assertFalse(handler.handled)

    def test_recommendations_allows_likes_at_limit(self) -> None:
        """Keep existing flow unchanged when likes count is within allowed maximum."""
        at_limit = similar.DEFAULT_CLIENT_LIKES_MAX
        body = {
            "likes": [
                {"uuid": f"video-{idx}", "host": "example.com"} for idx in range(at_limit)
            ]
        }
        handler = _DummySimilarHandler("/recommendations")
        with (
            patch.object(similar, "read_json_body", return_value=body),
            patch.object(similar, "respond_json") as respond_json_mock,
            patch.object(similar, "_parse_client_likes", return_value=[]) as parse_likes_mock,
            patch.object(similar, "_resolve_client_likes", return_value=[]),
            patch.object(similar, "set_request_client_likes") as set_likes_mock,
            patch.object(similar, "clear_request_context") as clear_context_mock,
        ):
            similar.SimilarHandler._handle_similar_request(handler, method="POST")

        respond_json_mock.assert_not_called()
        parse_likes_mock.assert_called_once_with(body)
        set_likes_mock.assert_called_once_with([], True)
        clear_context_mock.assert_called_once()
        self.assertTrue(handler.handled)

    def test_recommendations_rejects_invalid_likes_item_format(self) -> None:
        """Return 400 when likes item has invalid uuid/host format."""
        body = {"likes": [{"uuid": "   ", "host": "example.com"}]}
        handler = _DummySimilarHandler("/recommendations")
        with (
            patch.object(similar, "read_json_body", return_value=body),
            patch.object(similar, "respond_json") as respond_json_mock,
            patch.object(similar, "set_request_client_likes") as set_likes_mock,
            patch.object(similar, "clear_request_context") as clear_context_mock,
        ):
            similar.SimilarHandler._handle_similar_request(handler, method="POST")

        respond_json_mock.assert_called_once_with(
            handler,
            400,
            {
                "error": "Invalid likes payload",
                "reason": "likes.uuid must be a non-empty string",
                "index": 0,
            },
        )
        set_likes_mock.assert_not_called()
        clear_context_mock.assert_not_called()
        self.assertFalse(handler.handled)


if __name__ == "__main__":
    unittest.main()
