"""Tests for recommendations likes count limit handling."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


API_DIR = Path(__file__).resolve().parents[1]
SERVER_DIR = API_DIR.parent
for path in (str(SERVER_DIR), str(API_DIR)):
    if path in sys.path:
        sys.path.remove(path)
for path in (str(SERVER_DIR), str(API_DIR)):
    sys.path.insert(0, path)
sys.modules.pop("services", None)

fake_ann = types.ModuleType("data.ann")
fake_ann.search_index = lambda *_args, **_kwargs: ([], [])
sys.modules.setdefault("data.ann", fake_ann)

from route_results import RouteResult  # noqa: E402
from services import recommendation_service as rec_service  # noqa: E402
from server_config import DEFAULT_CLIENT_LIKES_MAX  # noqa: E402


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
        server = SimpleNamespace(use_client_likes=True)

        result = rec_service.handle_similar_request(server, "/recommendations", "POST", {}, body)

        self.assertEqual(result.status, 400)
        self.assertEqual(
            result.payload,
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
        server = SimpleNamespace(use_client_likes=True)
        with (
            patch.object(rec_service, "_parse_client_likes", return_value=[]) as parse_likes,
            patch.object(rec_service, "_resolve_client_likes", return_value=[]),
            patch.object(rec_service, "set_request_client_likes") as set_likes,
            patch.object(rec_service, "clear_request_context") as clear_context,
            patch.object(rec_service, "handle_similar", return_value=RouteResult(200, {})) as handle_similar,
        ):
            result = rec_service.handle_similar_request(server, "/recommendations", "POST", {}, body)

        parse_likes.assert_called_once_with(body)
        set_likes.assert_called_once_with([], True)
        handle_similar.assert_called_once_with(server, {})
        clear_context.assert_called_once()
        self.assertEqual(result.status, 200)

    def test_recommendations_rejects_invalid_likes_item_format(self) -> None:
        """Return 400 when likes item has invalid uuid/host format."""
        body = {"likes": [{"uuid": "   ", "host": "example.com"}]}
        server = SimpleNamespace(use_client_likes=True)
        with (
            patch.object(rec_service, "set_request_client_likes") as set_likes,
            patch.object(rec_service, "clear_request_context") as clear_context,
        ):
            result = rec_service.handle_similar_request(server, "/recommendations", "POST", {}, body)

        self.assertEqual(result.status, 400)
        self.assertEqual(
            result.payload,
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
