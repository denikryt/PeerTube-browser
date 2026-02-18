"""Provide serving moderation runtime helpers."""

from __future__ import annotations

# Shared serving-time moderation helper used by API handlers and tests.


import logging
from typing import Any

from data.moderation import ModerationFilterStats, filter_rows_by_moderation


def apply_serving_moderation_filters(
    server: Any,
    rows: list[dict[str, Any]],
    *,
    request_id: str | None = None,
) -> tuple[list[dict[str, Any]], ModerationFilterStats | None]:
    """Apply moderation filters exactly as server response path does."""
    apply_instance_filter = bool(getattr(server, "enable_instance_ignore", True))
    apply_channel_filter = bool(getattr(server, "enable_channel_blocklist", True))

    filtered_rows: list[dict[str, Any]] = rows
    filtered_stats: ModerationFilterStats | None = None
    if apply_instance_filter or apply_channel_filter:
        with server.db_lock:
            filtered_rows, filtered_stats = filter_rows_by_moderation(
                server.db,
                rows,
                apply_instance_filter=apply_instance_filter,
                apply_channel_filter=apply_channel_filter,
            )

    if (
        request_id
        and filtered_stats is not None
        and filtered_stats.total_filtered > 0
    ):
        logging.info(
            "[similar-server][%s] moderation filtered_by_denylist=%d filtered_by_blocked_channel=%d total=%d",
            request_id,
            filtered_stats.filtered_by_denylist,
            filtered_stats.filtered_by_blocked_channel,
            filtered_stats.total_filtered,
        )

    return filtered_rows, filtered_stats
