"""Characterize recommendation post-filter helpers."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))
sys.path.insert(0, str(ROOT / "engine" / "server"))

from recommendations.filters import apply_author_instance_caps, build_seen_keys, has_likes  # noqa: E402


def _key(entry: dict) -> str:
    """Return the current recommendation identity key used by these tests."""
    return f"{entry['video_id']}::{entry['instance_domain']}"


def test_apply_author_instance_caps_preserves_order_and_filters_seen_and_caps() -> None:
    """Per-author and per-instance limits must be applied without reordering survivors."""
    candidates = [
        {"video_id": "seen", "instance_domain": "a.org", "channel_id": "c1"},
        {"video_id": "keep-1", "instance_domain": "a.org", "channel_id": "c1"},
        {"video_id": "drop-author", "instance_domain": "a.org", "channel_id": "c1"},
        {"video_id": "drop-instance", "instance_domain": "a.org", "channel_id": "c2"},
        {"video_id": "keep-2", "instance_domain": "b.org", "channel_id": "c3"},
    ]

    filtered, seen, author_counts, instance_counts = apply_author_instance_caps(
        candidates,
        max_per_author=1,
        max_per_instance=1,
        like_key=_key,
        seen={"seen::a.org"},
    )

    assert [row["video_id"] for row in filtered] == ["keep-1", "keep-2"]
    assert seen == {"seen::a.org", "keep-1::a.org", "keep-2::b.org"}
    assert author_counts == {"c1::a.org": 1, "c3::b.org": 1}
    assert instance_counts == {"a.org": 1, "b.org": 1}


def test_build_seen_keys_and_has_likes_use_fetch_recent_likes_boundary() -> None:
    """Seen-key helpers must derive recommendation exclusions from recent likes."""
    likes = [{"video_id": "v1", "instance_domain": "example.org"}]
    fetch = lambda _user_id, _max_likes: likes

    assert build_seen_keys(object(), "user", fetch, _key, 100) == {"v1::example.org"}
    assert has_likes(object(), "user", fetch, 100) is True
