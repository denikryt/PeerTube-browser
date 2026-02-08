"""Popularity score helpers shared by batch jobs and API updates."""
from __future__ import annotations

from data.time import now_ms


def compute_popularity(
    views: int | None,
    likes: int | None,
    published_at: int | None,
    like_weight: float,
    now_ms_value: int | None = None,
) -> float:
    """Compute a popularity score using views/likes and age decay."""
    view_count = max(int(views or 0), 0)
    like_count = max(int(likes or 0), 0)
    if now_ms_value is None:
        now_ms_value = now_ms()
    if not published_at:
        age_days = 3650.0
    else:
        age_ms = max(int(now_ms_value) - int(published_at), 0)
        age_days = age_ms / 86_400_000.0
    return (view_count + (like_weight * like_count)) / (1.0 + (age_days / 30.0))
