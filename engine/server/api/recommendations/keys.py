"""Provide keys runtime helpers."""

from __future__ import annotations

from typing import Any


def like_key(entry: Any) -> str:
    """Build a stable key for a video reference."""
    if isinstance(entry, dict):
        video_id = entry.get("video_id")
        instance_domain = entry.get("instance_domain")
    else:
        video_id = entry["video_id"] if "video_id" in entry.keys() else None
        instance_domain = entry["instance_domain"] if "instance_domain" in entry.keys() else None
    return f"{video_id or ''}::{instance_domain or ''}"
