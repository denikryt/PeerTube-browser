"""Canonical Engine SQL gate for explicit parent-health failures.

Only the crawler/updater publishes health; this read-only helper compiles the
same predicate for direct, recommendation, facet and attached-cache reads.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def build_parent_visibility_sql(alias: str, *, schema: str = "main") -> str:
    """Reject videos with an explicitly unhealthy parent, not missing/unknown parents.

    Every caller uses an existing canonical video alias and schema. Parent
    identity is the normalized crawler key: host plus channel id and host.
    """
    if schema not in {"main", "canonical"}:
        raise ValueError("Unsupported parent visibility schema")
    return f"""NOT EXISTS (
      SELECT 1 FROM {schema}.instances AS unhealthy_instance
      WHERE unhealthy_instance.host = lower(trim({alias}.instance_domain))
        AND unhealthy_instance.health_status = 'error'
    ) AND NOT EXISTS (
      SELECT 1 FROM {schema}.channels AS unhealthy_channel
      WHERE unhealthy_channel.channel_id = {alias}.channel_id
        AND unhealthy_channel.instance_domain = lower(trim({alias}.instance_domain))
        AND unhealthy_channel.health_status = 'error'
    )"""




def filter_rows_by_parent_health(
    conn: "sqlite3.Connection", rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Apply explicit parent error visibility to an already materialized batch.

    Recommendation caches can contain old rows, so availability is checked
    against canonical parents at the final response boundary. Queries use
    indexed host and channel identities and one JSON1 parameter per set.
    """
    if not rows:
        return rows
    hosts = {
        str(row["instance_domain"]).strip().lower()
        for row in rows
        if row.get("instance_domain")
    }
    if not hosts:
        return rows
    denied_hosts = {
        str(row[0])
        for row in conn.execute(
            """SELECT host FROM instances WHERE health_status = 'error'
               AND host IN (SELECT value FROM json_each(?))""",
            (json.dumps(sorted(hosts)),),
        )
    }
    pairs = {
        (str(row["channel_id"]), str(row["instance_domain"]).strip().lower())
        for row in rows
        if row.get("channel_id") and row.get("instance_domain")
    }
    denied_channels: set[tuple[str, str]] = set()
    if pairs:
        denied_channels = {
            (str(row[0]), str(row[1]))
            for row in conn.execute(
                """SELECT c.channel_id, c.instance_domain
                   FROM json_each(?) AS selected
                   JOIN channels AS c
                     ON c.channel_id = json_extract(selected.value, '$[0]')
                    AND c.instance_domain = json_extract(selected.value, '$[1]')
                   WHERE c.health_status = 'error'""",
                (json.dumps(sorted(pairs)),),
            )
        }
    return [
        row
        for row in rows
        if not row.get("instance_domain")
        or (
            str(row["instance_domain"]).strip().lower() not in denied_hosts
            and (
                str(row.get("channel_id") or ""),
                str(row["instance_domain"]).strip().lower(),
            ) not in denied_channels
        )
    ]
