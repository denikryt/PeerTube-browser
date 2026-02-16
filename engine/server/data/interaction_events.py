from __future__ import annotations

import json
import sqlite3
from typing import Any

from data.time import now_ms

ALLOWED_EVENT_TYPES = {"Like", "UndoLike", "Comment"}


def ensure_interaction_event_schema(conn: sqlite3.Connection) -> None:
    """Create raw/aggregated interaction event tables if missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS interaction_raw_events (
          event_id TEXT PRIMARY KEY,
          event_type TEXT NOT NULL,
          actor_id TEXT,
          video_uuid TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          canonical_url TEXT,
          source_instance TEXT,
          published_at INTEGER NOT NULL,
          raw_payload_json TEXT,
          ingested_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS interaction_raw_events_video_idx
          ON interaction_raw_events (video_uuid, instance_domain, published_at DESC);

        CREATE TABLE IF NOT EXISTS interaction_signals (
          video_uuid TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          likes_count INTEGER NOT NULL DEFAULT 0,
          undo_likes_count INTEGER NOT NULL DEFAULT 0,
          comments_count INTEGER NOT NULL DEFAULT 0,
          signal_score REAL NOT NULL DEFAULT 0,
          updated_at INTEGER NOT NULL,
          PRIMARY KEY (video_uuid, instance_domain)
        );
        """
    )
    conn.commit()


def ingest_interaction_event(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    """Insert one event idempotently and update aggregated interaction signals."""
    event = normalize_event_payload(payload)
    ingested_at = now_ms()
    cursor = conn.execute(
        """
        INSERT INTO interaction_raw_events (
          event_id,
          event_type,
          actor_id,
          video_uuid,
          instance_domain,
          canonical_url,
          source_instance,
          published_at,
          raw_payload_json,
          ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO NOTHING
        """,
        (
            event["event_id"],
            event["event_type"],
            event["actor_id"],
            event["video_uuid"],
            event["instance_domain"],
            event["canonical_url"],
            event["source_instance"],
            event["published_at"],
            json.dumps(event["raw_payload"], ensure_ascii=False),
            ingested_at,
        ),
    )
    inserted = int(cursor.rowcount or 0) > 0
    if not inserted:
        conn.commit()
        return {
            "ok": True,
            "duplicate": True,
            "event_id": event["event_id"],
            "event_type": event["event_type"],
        }

    deltas = _event_deltas(event["event_type"])
    conn.execute(
        """
        INSERT INTO interaction_signals (
          video_uuid,
          instance_domain,
          likes_count,
          undo_likes_count,
          comments_count,
          signal_score,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_uuid, instance_domain) DO UPDATE SET
          likes_count = MAX(0, interaction_signals.likes_count + excluded.likes_count),
          undo_likes_count = MAX(0, interaction_signals.undo_likes_count + excluded.undo_likes_count),
          comments_count = MAX(0, interaction_signals.comments_count + excluded.comments_count),
          signal_score = MAX(0.0, interaction_signals.signal_score + excluded.signal_score),
          updated_at = excluded.updated_at
        """,
        (
            event["video_uuid"],
            event["instance_domain"],
            deltas["likes_count"],
            deltas["undo_likes_count"],
            deltas["comments_count"],
            deltas["signal_score"],
            ingested_at,
        ),
    )
    conn.commit()
    return {
        "ok": True,
        "duplicate": False,
        "event_id": event["event_id"],
        "event_type": event["event_type"],
    }


def normalize_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize bridge event payload."""
    event_id = _clean_text(payload.get("event_id"))
    event_type = _clean_text(payload.get("event_type"))
    actor_id = _clean_text(payload.get("actor_id"))
    if not event_id:
        raise ValueError("Missing event_id")
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError("Unsupported event_type")

    obj = payload.get("object")
    if not isinstance(obj, dict):
        raise ValueError("Missing object")
    video_uuid = _clean_text(obj.get("video_uuid"))
    instance_domain = _clean_text(obj.get("instance_domain"))
    canonical_url = _clean_text(obj.get("canonical_url"))
    if not video_uuid:
        raise ValueError("Missing object.video_uuid")
    if not instance_domain:
        raise ValueError("Missing object.instance_domain")

    published_raw = payload.get("published_at")
    try:
        published_at = int(published_raw)
    except (TypeError, ValueError):
        published_at = now_ms()

    return {
        "event_id": event_id,
        "event_type": event_type,
        "actor_id": actor_id,
        "video_uuid": video_uuid,
        "instance_domain": instance_domain,
        "canonical_url": canonical_url,
        "published_at": published_at,
        "source_instance": _clean_text(payload.get("source_instance")),
        "raw_payload": payload.get("raw_payload") if isinstance(payload.get("raw_payload"), dict) else {},
    }


def _event_deltas(event_type: str) -> dict[str, float]:
    if event_type == "Like":
        return {
            "likes_count": 1,
            "undo_likes_count": 0,
            "comments_count": 0,
            "signal_score": 1.0,
        }
    if event_type == "UndoLike":
        return {
            "likes_count": -1,
            "undo_likes_count": 1,
            "comments_count": 0,
            "signal_score": -1.0,
        }
    return {
        "likes_count": 0,
        "undo_likes_count": 0,
        "comments_count": 1,
        "signal_score": 0.25,
    }


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized else None
