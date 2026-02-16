#!/usr/bin/env python3
"""Compare JoinPeerTube hosts with local DB and show missing/blocked hosts."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[2]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))
api_dir = server_dir / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from server_config import DEFAULT_DB_PATH
from data.moderation import ensure_moderation_schema, list_active_denied_hosts
from scripts.cli_format import CompactHelpFormatter

DEFAULT_URL = (
    "https://instances.joinpeertube.org/api/v1/instances/hosts?count=5000&healthy=true"
)


def parse_args() -> argparse.Namespace:
    repo_root = script_dir.parents[4]
    parser = argparse.ArgumentParser(
        description=(
            "Compare JoinPeerTube host list with local instances table and show "
            "hosts missing locally. Also prints local active denylist hosts."
        ),
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=(repo_root / DEFAULT_DB_PATH).resolve(),
        help="Path to local SQLite DB.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="JoinPeerTube hosts JSON URL.",
    )
    return parser.parse_args()


def fetch_hosts_from_url(url: str) -> set[str]:
    request = Request(url, headers={"User-Agent": "peertube-browser-compare/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Failed to fetch hosts from {url}: {exc}") from exc
    return hosts_from_payload(payload)


def hosts_from_payload(payload: object) -> set[str]:
    if isinstance(payload, dict) and "data" in payload:
        entries = payload["data"]
    elif isinstance(payload, list):
        entries = payload
    else:
        raise ValueError("Unexpected JoinPeerTube JSON shape.")

    hosts: set[str] = set()
    for entry in entries:
        host = entry.get("host") if isinstance(entry, dict) else entry
        if not host:
            continue
        value = str(host).strip().lower()
        if value:
            hosts.add(value)

    if not hosts:
        raise ValueError("JoinPeerTube payload contained no hosts.")
    return hosts


def load_local_hosts(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path.as_posix())
    try:
        if not table_exists(conn, "instances"):
            return set()
        rows = conn.execute("SELECT host FROM instances").fetchall()
        return {str(row[0]).strip().lower() for row in rows if row and row[0]}
    finally:
        conn.close()


def load_local_blocked_hosts(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path.as_posix())
    conn.row_factory = sqlite3.Row
    try:
        ensure_moderation_schema(conn)
        return list_active_denied_hosts(conn)
    finally:
        conn.close()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def print_list(title: str, hosts: list[str]) -> None:
    print()
    print(title)
    if not hosts:
        print("  (empty)")
        return
    for host in hosts:
        print(f"  {host}")


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    join_hosts = fetch_hosts_from_url(args.url)

    local_hosts = load_local_hosts(db_path)
    blocked_hosts = load_local_blocked_hosts(db_path)

    missing_local = sorted(join_hosts - local_hosts)
    blocked_sorted = sorted(blocked_hosts)

    print(f"db={db_path}")
    print(f"join_hosts_total={len(join_hosts)}")
    print(f"local_instances_total={len(local_hosts)}")
    print(f"local_blocked_total={len(blocked_hosts)}")
    print(f"missing_local_total={len(missing_local)}")
    print(f"missing_local_blocked_total={sum(1 for host in missing_local if host in blocked_hosts)}")

    print_list("Missing locally (present on JoinPeerTube):", missing_local)
    print_list("Local blocked hosts:", blocked_sorted)


if __name__ == "__main__":
    main()
