"""Provide moderation runtime helpers."""

from __future__ import annotations

# Shared moderation primitives for deny/block/ignore flows.
#
# This module centralizes:
# - moderation schema creation,
# - host normalization,
# - serving-time row filtering (denylist + blocked channels),
# - purge helpers for host-linked rows in main/similarity databases.


import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse


@dataclass(frozen=True)
class ModerationFilterStats:
    """Counters for serving-time moderation filtering."""

    filtered_by_denylist: int = 0
    filtered_by_blocked_channel: int = 0

    @property
    def total_filtered(self) -> int:
        """Handle total filtered."""
        return self.filtered_by_denylist + self.filtered_by_blocked_channel


def now_ms() -> int:
    """Return current UTC epoch time in milliseconds."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def normalize_host(value: str | None) -> str | None:
    """Normalize host input (lower, strip protocol/path, trim dots/spaces)."""
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None

    candidate = raw
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return None
    host = host.strip(".")
    if not host:
        return None
    # Reject clearly invalid hosts.
    if re.search(r"\s", host):
        return None
    return host


def ensure_moderation_schema(conn: sqlite3.Connection) -> None:
    """Create moderation tables used by denylist and channel blocking flows."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS instance_denylist (
          host TEXT PRIMARY KEY,
          is_active INTEGER NOT NULL DEFAULT 1,
          reason TEXT,
          note TEXT,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_instance_denylist_active
          ON instance_denylist (is_active, host);

        CREATE TABLE IF NOT EXISTS channel_moderation (
          channel_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('blocked', 'allowed')),
          reason TEXT,
          source_video_url TEXT,
          updated_at INTEGER NOT NULL,
          created_at INTEGER NOT NULL,
          PRIMARY KEY (channel_id, instance_domain)
        );
        CREATE INDEX IF NOT EXISTS idx_channel_moderation_status_instance
          ON channel_moderation (status, instance_domain);
        """
    )


def list_active_denied_hosts(conn: sqlite3.Connection) -> set[str]:
    """Return active deny hosts from canonical denylist."""
    denied: set[str] = set()
    if _table_exists(conn, "instance_denylist"):
        rows = conn.execute(
            "SELECT host FROM instance_denylist WHERE is_active = 1"
        ).fetchall()
        denied.update(_row_value(rows, "host"))
    return {host.lower() for host in denied if isinstance(host, str) and host}


def filter_rows_by_moderation(
    conn: sqlite3.Connection,
    rows: list[dict[str, object]],
    *,
    apply_instance_filter: bool = True,
    apply_channel_filter: bool = True,
) -> tuple[list[dict[str, object]], ModerationFilterStats]:
    """Filter API output rows by denylisted hosts and blocked channels."""
    if not rows:
        return rows, ModerationFilterStats()

    hosts: set[str] = set()
    channel_pairs: set[tuple[str, str]] = set()
    for row in rows:
        host = _row_host(row)
        if host:
            hosts.add(host)
        channel_id = _row_channel_id(row)
        if host and channel_id:
            channel_pairs.add((channel_id, host))

    denied_hosts = _lookup_denied_hosts(conn, hosts) if apply_instance_filter else set()
    blocked_channels = (
        _lookup_blocked_channels(conn, channel_pairs) if apply_channel_filter else set()
    )

    filtered: list[dict[str, object]] = []
    deny_count = 0
    blocked_count = 0
    for row in rows:
        host = _row_host(row)
        if host and host in denied_hosts:
            deny_count += 1
            continue
        channel_id = _row_channel_id(row)
        if host and channel_id and (channel_id, host) in blocked_channels:
            blocked_count += 1
            continue
        filtered.append(row)

    return filtered, ModerationFilterStats(
        filtered_by_denylist=deny_count,
        filtered_by_blocked_channel=blocked_count,
    )


def purge_host_data(
    conn: sqlite3.Connection,
    host: str,
    *,
    dry_run: bool = False,
    precomputed_counts: dict[str, int] | None = None,
) -> dict[str, int]:
    """Delete host-linked rows from the main DB and return per-table counters."""
    normalized = normalize_host(host)
    if not normalized:
        raise ValueError(f"Invalid host: {host}")

    table_column_pairs = _host_table_column_pairs()
    counts: dict[str, int]
    if precomputed_counts is None:
        counts = _count_host_rows(conn, normalized, table_column_pairs)
    else:
        counts = {
            table: int(precomputed_counts.get(table, 0))
            for table, _ in table_column_pairs
            if _table_exists(conn, table)
        }

    if dry_run:
        return counts

    with conn:
        for table, column in table_column_pairs:
            if not _table_exists(conn, table):
                continue
            conn.execute(
                f"DELETE FROM {table} WHERE {column} = ?",
                (normalized,),
            )
    return counts


def purge_similarity_for_host(
    conn: sqlite3.Connection,
    host: str,
    *,
    dry_run: bool = False,
    precomputed_counts: dict[str, int] | None = None,
) -> dict[str, int]:
    """Delete similarity-cache rows referencing host as source or similar."""
    normalized = normalize_host(host)
    if not normalized:
        raise ValueError(f"Invalid host: {host}")

    ensure_similarity_purge_indexes(conn)

    if precomputed_counts is None:
        stats = collect_similarity_host_stats(conn, normalized)
    else:
        stats = {
            "similarity_items": int(precomputed_counts.get("similarity_items", 0)),
            "similarity_sources": int(precomputed_counts.get("similarity_sources", 0)),
            "similarity_items_as_source": int(
                precomputed_counts.get("similarity_items_as_source", 0)
            ),
            "similarity_items_as_similar": int(
                precomputed_counts.get("similarity_items_as_similar", 0)
            ),
            "similarity_items_total_mentions": int(
                precomputed_counts.get("similarity_items_total_mentions", 0)
            ),
        }
    counts = {
        "similarity_items": int(stats.get("similarity_items", 0)),
        "similarity_sources": int(stats.get("similarity_sources", 0)),
    }

    if dry_run:
        return counts

    with conn:
        if _table_exists(conn, "similarity_items"):
            conn.execute(
                """
                DELETE FROM similarity_items
                WHERE source_instance_domain = ? OR similar_instance_domain = ?
                """,
                (normalized, normalized),
            )
        if _table_exists(conn, "similarity_sources"):
            conn.execute(
                "DELETE FROM similarity_sources WHERE instance_domain = ?",
                (normalized,),
            )
    return counts


def collect_similarity_host_stats(
    conn: sqlite3.Connection, host: str
) -> dict[str, int]:
    """Return detailed similarity stats for a host in one pass where possible."""
    normalized = normalize_host(host)
    if not normalized:
        raise ValueError(f"Invalid host: {host}")

    stats = {
        "similarity_items": 0,
        "similarity_sources": 0,
        "similarity_items_as_source": 0,
        "similarity_items_as_similar": 0,
        "similarity_items_total_mentions": 0,
    }
    if _table_exists(conn, "similarity_items"):
        row = conn.execute(
            """
            SELECT
              SUM(CASE WHEN source_instance_domain = ? THEN 1 ELSE 0 END) AS as_source,
              SUM(CASE WHEN similar_instance_domain = ? THEN 1 ELSE 0 END) AS as_similar,
              COUNT(*) AS deletable
            FROM similarity_items
            WHERE source_instance_domain = ? OR similar_instance_domain = ?
            """,
            (normalized, normalized, normalized, normalized),
        ).fetchone()
        as_source = int((row["as_source"] if row else 0) or 0)
        as_similar = int((row["as_similar"] if row else 0) or 0)
        stats["similarity_items_as_source"] = as_source
        stats["similarity_items_as_similar"] = as_similar
        stats["similarity_items_total_mentions"] = as_source + as_similar
        stats["similarity_items"] = int((row["deletable"] if row else 0) or 0)
    if _table_exists(conn, "similarity_sources"):
        stats["similarity_sources"] = int(
            conn.execute(
                "SELECT COUNT(*) FROM similarity_sources WHERE instance_domain = ?",
                (normalized,),
            ).fetchone()[0]
        )
    return stats


def ensure_similarity_purge_indexes(conn: sqlite3.Connection) -> bool:
    """Create indexes used by similarity host purge/count queries (best effort)."""
    statements: list[str] = []
    if _table_exists(conn, "similarity_items"):
        statements.append(
            """
            CREATE INDEX IF NOT EXISTS idx_similarity_items_source_instance_domain
              ON similarity_items (source_instance_domain);
            """
        )
        statements.append(
            """
            CREATE INDEX IF NOT EXISTS idx_similarity_items_similar_instance_domain
              ON similarity_items (similar_instance_domain);
            """
        )
    if _table_exists(conn, "similarity_sources"):
        statements.append(
            """
            CREATE INDEX IF NOT EXISTS idx_similarity_sources_instance_domain
              ON similarity_sources (instance_domain);
            """
        )
    if not statements:
        return True
    try:
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.executescript("\n".join(statements))
    except sqlite3.OperationalError:
        return False
    return True


def _host_table_column_pairs() -> list[tuple[str, str]]:
    """Handle host table column pairs."""
    return [
        ("video_embeddings", "instance_domain"),
        ("videos", "instance_domain"),
        ("channels", "instance_domain"),
        ("instances", "host"),
        ("video_crawl_progress", "instance_domain"),
        ("channel_crawl_progress", "instance_domain"),
        ("instance_crawl_progress", "host"),
    ]


def _count_host_rows(
    conn: sqlite3.Connection,
    normalized_host: str,
    table_column_pairs: list[tuple[str, str]],
) -> dict[str, int]:
    """Handle count host rows."""
    counts: dict[str, int] = {}
    for table, column in table_column_pairs:
        if not _table_exists(conn, table):
            continue
        counts[table] = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",
                (normalized_host,),
            ).fetchone()[0]
        )
    return counts


def _lookup_denied_hosts(
    conn: sqlite3.Connection, hosts: set[str]
) -> set[str]:
    """Handle lookup denied hosts."""
    if not hosts:
        return set()

    placeholders = ", ".join(["?"] * len(hosts))
    params = tuple(sorted(hosts))
    denied: set[str] = set()

    if _table_exists(conn, "instance_denylist"):
        rows = conn.execute(
            f"""
            SELECT host
            FROM instance_denylist
            WHERE is_active = 1
              AND host IN ({placeholders})
            """,
            params,
        ).fetchall()
        denied.update(_row_value(rows, "host"))
    return {host.lower() for host in denied if isinstance(host, str) and host}


def _lookup_blocked_channels(
    conn: sqlite3.Connection,
    pairs: set[tuple[str, str]],
) -> set[tuple[str, str]]:
    """Handle lookup blocked channels."""
    if not pairs or not _table_exists(conn, "channel_moderation"):
        return set()

    conditions = " OR ".join(
        ["(channel_id = ? AND instance_domain = ?)"] * len(pairs)
    )
    params: list[str] = []
    for channel_id, host in sorted(pairs):
        params.extend([channel_id, host])
    rows = conn.execute(
        f"""
        SELECT channel_id, instance_domain
        FROM channel_moderation
        WHERE status = 'blocked'
          AND ({conditions})
        """,
        params,
    ).fetchall()
    return {
        (str(row["channel_id"]), str(row["instance_domain"]).lower()) for row in rows
    }


def _row_host(row: dict[str, object]) -> str | None:
    """Handle row host."""
    raw = row.get("instance_domain")
    if raw is None:
        raw = row.get("instanceDomain")
    if not isinstance(raw, str):
        return None
    normalized = normalize_host(raw)
    return normalized


def _row_channel_id(row: dict[str, object]) -> str | None:
    """Handle row channel id."""
    raw = row.get("channel_id")
    if raw is None:
        raw = row.get("channelId")
    if isinstance(raw, str) and raw:
        return raw
    return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Handle table exists."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _row_value(rows: list[sqlite3.Row], key: str) -> set[object]:
    """Handle row value."""
    values: set[object] = set()
    for row in rows:
        values.add(row[key])
    return values
