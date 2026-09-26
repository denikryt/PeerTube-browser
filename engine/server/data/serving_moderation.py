"""Provide serving moderation runtime helpers."""

from __future__ import annotations

# Shared serving-time moderation helper used by API handlers and tests.


import logging
from dataclasses import dataclass
from typing import Any

from data.moderation import ModerationFilterStats, filter_rows_by_moderation


@dataclass(frozen=True)
class ServingVisibility:
    """SQL-visible serving policy evaluated before pagination or aggregation."""

    error_threshold: int | None = None
    apply_instance_filter: bool = True
    apply_channel_filter: bool = True


def serving_visibility_from_server(server: Any) -> ServingVisibility:
    """Freeze Engine runtime moderation settings into one query policy object."""
    return ServingVisibility(
        error_threshold=getattr(server, "video_error_threshold", None),
        apply_instance_filter=bool(getattr(server, "enable_instance_ignore", True)),
        apply_channel_filter=bool(getattr(server, "enable_channel_blocklist", True)),
    )


def build_serving_visibility_sql(
    alias: str,
    flags: ServingVisibility,
    *,
    schema: str = "main",
) -> tuple[str, list[object]]:
    """Build canonical visibility predicates for one trusted video-table alias.

    ``schema`` is deliberately limited to the two namespaces used by runtime
    queries.  Random attaches the canonical DB as ``canonical`` while ordinary
    providers query the main Engine connection.
    """
    if schema not in {"main", "canonical"}:
        raise ValueError("Unsupported serving visibility schema")

    clauses = [f"COALESCE({alias}.invalid_reason, '') = ''"]
    params: list[object] = []
    if flags.error_threshold is not None and flags.error_threshold > 0:
        clauses.append(f"({alias}.error_count IS NULL OR {alias}.error_count < ?)")
        params.append(flags.error_threshold)
    if flags.apply_instance_filter:
        clauses.append(
            f"""NOT EXISTS (
              SELECT 1 FROM {schema}.instance_denylist AS denied
              WHERE denied.is_active = 1
                AND lower(trim(denied.host)) = lower(trim({alias}.instance_domain))
            )"""
        )
    if flags.apply_channel_filter:
        clauses.append(
            f"""NOT EXISTS (
              SELECT 1 FROM {schema}.channel_moderation AS blocked
              WHERE blocked.status = 'blocked'
                AND blocked.channel_id = {alias}.channel_id
                AND lower(trim(blocked.instance_domain)) = lower(trim({alias}.instance_domain))
            )"""
        )
    return " AND ".join(f"({clause})" for clause in clauses), params


def apply_serving_moderation_filters(
    server: Any,
    rows: list[dict[str, Any]],
    *,
    request_id: str | None = None,
) -> tuple[list[dict[str, Any]], ModerationFilterStats | None]:
    """Apply moderation filters exactly as server response path does."""
    visibility = serving_visibility_from_server(server)
    apply_instance_filter = visibility.apply_instance_filter
    apply_channel_filter = visibility.apply_channel_filter

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
