#!/usr/bin/env python3
"""Contract test for Engine interaction bridge ingest idempotency/signals."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[2]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from data.interaction_events import ensure_interaction_event_schema, ingest_interaction_event


def assert_eq(actual: object, expected: object, message: str) -> None:
    """Handle assert eq."""
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected} actual={actual}")


def main() -> None:
    """Handle main."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_interaction_event_schema(conn)

    base = {
        "actor_id": "user-1",
        "object": {
            "video_uuid": "video-uuid-1",
            "instance_domain": "example.com",
            "canonical_url": "https://example.com/videos/watch/video-uuid-1",
        },
        "published_at": 1739700000000,
        "source_instance": "example.com",
        "raw_payload": {"source": "test"},
    }

    first = ingest_interaction_event(
        conn,
        {
            **base,
            "event_id": "evt-like-1",
            "event_type": "Like",
        },
    )
    duplicate = ingest_interaction_event(
        conn,
        {
            **base,
            "event_id": "evt-like-1",
            "event_type": "Like",
        },
    )

    assert_eq(first.get("duplicate"), False, "first ingest should not be duplicate")
    assert_eq(duplicate.get("duplicate"), True, "second ingest should be duplicate")

    raw_count = conn.execute(
        "SELECT COUNT(*) AS c FROM interaction_raw_events WHERE event_id = ?",
        ("evt-like-1",),
    ).fetchone()["c"]
    assert_eq(raw_count, 1, "duplicate event_id must be idempotent")

    undo = ingest_interaction_event(
        conn,
        {
            **base,
            "event_id": "evt-unlike-1",
            "event_type": "UndoLike",
        },
    )
    comment = ingest_interaction_event(
        conn,
        {
            **base,
            "event_id": "evt-comment-1",
            "event_type": "Comment",
        },
    )
    assert_eq(undo.get("duplicate"), False, "undo event should ingest")
    assert_eq(comment.get("duplicate"), False, "comment event should ingest")

    row = conn.execute(
        """
        SELECT likes_count, undo_likes_count, comments_count, signal_score
        FROM interaction_signals
        WHERE video_uuid = ? AND instance_domain = ?
        """,
        ("video-uuid-1", "example.com"),
    ).fetchone()
    assert_eq(int(row["likes_count"]), 0, "likes_count should account for undo")
    assert_eq(int(row["undo_likes_count"]), 1, "undo_likes_count should increment")
    assert_eq(int(row["comments_count"]), 1, "comments_count should increment")
    assert_eq(float(row["signal_score"]), 0.25, "signal_score should combine deltas")

    print("ok: interaction ingest idempotency and signal aggregation")


if __name__ == "__main__":
    main()
