"""Behavior tests for the materialized views-and-likes-per-hour Trending score."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1]
SERVER_DIR = API_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.popularity import compute_popularity  # noqa: E402


class TrendingScoreTests(unittest.TestCase):
    """Protect the ranking invariant used by the public Trending feed."""

    def test_younger_or_more_reacted_video_scores_higher(self) -> None:
        """Rank equal reactions by age and equal age by views plus ten-times likes."""
        now = 100 * 3_600_000
        newer = compute_popularity(100, 1, now - 3_600_000, 10.0, now)
        older = compute_popularity(100, 1, now - (10 * 3_600_000), 10.0, now)
        more_reacted = compute_popularity(110, 2, now - (10 * 3_600_000), 10.0, now)

        self.assertGreater(newer, older)
        self.assertGreater(more_reacted, older)
        self.assertEqual(newer, 55.0)


if __name__ == "__main__":
    unittest.main()
