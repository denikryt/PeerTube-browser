"""JoinPeerTube sync, denylist, and purge helpers for updater runs."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

from .paths import SERVER_DIR

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.moderation import (  # noqa: E402
    ensure_moderation_schema,
    list_active_denied_hosts,
    purge_host_data,
    purge_similarity_for_host,
)


def fetch_join_hosts(url: str) -> set[str]:
    """Fetch JoinPeerTube hosts, accepting the existing list and data shapes."""

    request = Request(url, headers={"User-Agent": "PeerTubeBrowserUpdater/1.0"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - URL is user-configured CLI input.
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("data", [])
    else:
        rows = payload
    hosts: set[str] = set()
    for row in rows:
        if isinstance(row, str):
            host = row
        elif isinstance(row, dict):
            host = row.get("host") or row.get("domain") or row.get("name") or ""
        else:
            host = ""
        host = str(host).strip().lower()
        if host:
            hosts.add(host)
    return hosts


def list_prod_hosts(db_path: Path) -> set[str]:
    """Return normalized instance hosts currently present in the prod DB."""

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT host FROM instances").fetchall()
    return {str(row[0]).strip().lower() for row in rows if row[0]}


def load_denied_hosts(db_path: Path) -> set[str]:
    """Load active moderation denylist hosts from the prod DB."""

    with sqlite3.connect(db_path) as conn:
        ensure_moderation_schema(conn)
        return set(list_active_denied_hosts(conn))


def write_hosts_file(hosts: set[str], prefix: str) -> Path | None:
    """Write sorted hosts to a temp file, returning None for an empty set."""

    if not hosts:
        return None
    handle = tempfile.NamedTemporaryFile(
        "w", prefix=prefix, suffix=".txt", delete=False, encoding="utf-8"
    )
    with handle:
        for host in sorted(hosts):
            handle.write(host + "\n")
    return Path(handle.name)


def purge_hosts(
    *, prod_db: Path, similarity_db: Path | None, hosts: set[str], dry_run: bool
) -> dict[str, int]:
    """Purge or plan purging host data using the current moderation helpers."""

    aggregate: dict[str, int] = {}
    if not hosts:
        return aggregate
    with sqlite3.connect(prod_db) as conn:
        ensure_moderation_schema(conn)
        for host in sorted(hosts):
            result = purge_host_data(conn, host, dry_run=dry_run)
            for key, value in result.items():
                aggregate[key] = aggregate.get(key, 0) + int(value)
    if similarity_db is not None:
        with sqlite3.connect(similarity_db) as sim_conn:
            for host in sorted(hosts):
                result = purge_similarity_for_host(sim_conn, host, dry_run=dry_run)
                for key, value in result.items():
                    aggregate[f"similarity_{key}"] = aggregate.get(f"similarity_{key}", 0) + int(
                        value
                    )
    return aggregate


def purge_hosts_from_staging(staging_db: Path, hosts: set[str]) -> dict[str, int]:
    """Delete denylisted hosts from staging tables with current table assumptions."""

    if not hosts:
        return {}
    placeholders = ",".join("?" for _ in hosts)
    params = sorted(hosts)
    deleted: dict[str, int] = {}
    with sqlite3.connect(staging_db) as conn:
        for table, column in (
            ("videos", "host"),
            ("channels", "host"),
            ("instances", "host"),
        ):
            cur = conn.execute(
                f"DELETE FROM {table} WHERE lower({column}) IN ({placeholders})", params
            )
            deleted[table] = cur.rowcount
        conn.commit()
    return deleted
