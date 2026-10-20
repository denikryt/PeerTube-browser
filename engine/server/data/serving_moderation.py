"""Provide serving moderation runtime helpers."""

from __future__ import annotations

# Shared serving-time moderation helper used by API handlers and tests.


import logging
from dataclasses import dataclass
from typing import Any

from data.moderation import ModerationFilterStats, filter_rows_by_moderation
from data.parent_health_visibility import build_parent_visibility_sql, filter_rows_by_parent_health


@dataclass(frozen=True)
class ServingVisibility:
    """SQL-visible serving policy evaluated before pagination or aggregation."""

    apply_instance_filter: bool = True
    apply_channel_filter: bool = True


def serving_visibility_from_server(server: Any) -> ServingVisibility:
    """Freeze Engine runtime moderation settings into one query policy object."""
    return ServingVisibility(
        apply_instance_filter=bool(getattr(server, "enable_instance_ignore", True)),
        apply_channel_filter=bool(getattr(server, "enable_channel_blocklist", True)),
    )


def build_serving_visibility_sql(
    alias: str,
    flags: ServingVisibility,
    *,
    schema: str = "main",
) -> str:
    """Build canonical visibility predicates for one trusted video-table alias.

    ``schema`` is deliberately limited to the two namespaces used by runtime
    queries.  Random attaches the canonical DB as ``canonical`` while ordinary
    providers query the main Engine connection.
    """
    if schema not in {"main", "canonical"}:
        raise ValueError("Unsupported serving visibility schema")

    # Parent failures are independent of runtime moderation configuration.
    clauses = [f"{alias}.invalid_reason IS NULL", build_parent_visibility_sql(alias, schema=schema)]
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
    return " AND ".join(f"({clause})" for clause in clauses)


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

    # Cached recommendation rows may have been materialized before parent
    # health changed; enforce the same gate even with moderation disabled.
    with server.db_lock:
        filtered_rows = filter_rows_by_parent_health(server.db, rows)
        filtered_stats: ModerationFilterStats | None = None
        if apply_instance_filter or apply_channel_filter:
            filtered_rows, filtered_stats = filter_rows_by_moderation(
                server.db,
                filtered_rows,
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
