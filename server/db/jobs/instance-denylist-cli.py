#!/usr/bin/env python3
"""CLI for persistent instance denylist management."""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))
api_dir = server_dir / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from server_config import DEFAULT_DB_PATH, DEFAULT_SIMILARITY_DB_PATH
from data.moderation import (
    collect_similarity_host_stats,
    ensure_moderation_schema,
    ensure_similarity_purge_indexes,
    normalize_host,
    now_ms,
    purge_host_data,
    purge_similarity_for_host,
)


class DenylistHelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawTextHelpFormatter,
):
    """Readable multiline help for command synopsis and notes."""


def parse_args() -> argparse.Namespace:
    repo_root = script_dir.parents[2]
    help_overview = (
        "Commands:\n"
        "  block --host HOST [--reason TEXT] [--note TEXT] [--purge-now] [--dry-run] [--yes]\n"
        "    Add host to denylist (is_active=1).\n"
        "    --purge-now: also purge host rows from main/similarity DBs.\n"
        "    --dry-run: preview purge counters only (no row deletion).\n"
        "    --yes: required for destructive purge when --purge-now is used.\n"
        "    Note: denylist block is still written even with --dry-run.\n"
        "\n"
        "  unblock --host HOST\n"
        "    Mark host as unblocked in denylist (is_active=0).\n"
        "\n"
        "  list [--active-only]\n"
        "    Print denylist rows; --active-only shows only blocked hosts.\n"
        "\n"
        "Run '<command> --help' for command-specific flags."
    )
    parser = argparse.ArgumentParser(
        description=(
            "Manage persistent instance denylist. "
            "Host is set in subcommands: block --host HOST / unblock --host HOST."
        ),
        formatter_class=DenylistHelpFormatter,
        epilog=help_overview,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=(repo_root / DEFAULT_DB_PATH).resolve(),
        help="Path to main SQLite DB.",
    )
    parser.add_argument(
        "--similarity-db",
        type=Path,
        default=(repo_root / DEFAULT_SIMILARITY_DB_PATH).resolve(),
        help="Path to similarity cache DB (used by --purge-now).",
    )

    sub = parser.add_subparsers(dest="command", required=True, title="commands")

    block = sub.add_parser(
        "block",
        help="Block host in denylist (requires --host).",
        description=(
            "Add host to denylist. "
            "By default it only blocks new serving/ingest flows. "
            "Use --purge-now to remove existing host rows from DB."
        ),
        formatter_class=DenylistHelpFormatter,
    )
    block.add_argument("--host", required=True, help="Instance host.")
    block.add_argument("--reason", default=None, help="Optional reason.")
    block.add_argument("--note", default=None, help="Optional note.")
    block.add_argument("--purge-now", action="store_true", help="Purge host-linked rows now.")
    block.add_argument("--dry-run", action="store_true", help="Only print purge counters.")
    block.add_argument("--yes", action="store_true", help="Confirm destructive purge.")

    unblock = sub.add_parser("unblock", help="Unblock host in denylist (requires --host).")
    unblock.add_argument("--host", required=True, help="Instance host.")

    list_cmd = sub.add_parser("list", help="List denylist rows.")
    list_cmd.add_argument("--active-only", action="store_true", help="Show only active rows.")

    return parser.parse_args()


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.as_posix())
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_fields(**fields: object) -> str:
    parts: list[str] = []
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    return " ".join(parts)


def log_info(event: str, **fields: object) -> None:
    if fields:
        print(f"INFO [{event}] {_fmt_fields(**fields)}")
    else:
        print(f"INFO [{event}]")


def log_info_block(event: str, **fields: object) -> None:
    print(f"INFO [{event}]")
    for key, value in fields.items():
        if isinstance(value, dict):
            print(f"  {key}:")
            for inner_key, inner_value in value.items():
                print(f"    {inner_key}={inner_value}")
        else:
            print(f"  {key}={value}")


def require_host(value: str) -> str:
    host = normalize_host(value)
    if not host:
        raise SystemExit(f"Invalid host: {value}")
    return host


def upsert_block(conn: sqlite3.Connection, host: str, reason: str | None, note: str | None) -> None:
    ts = now_ms()
    conn.execute(
        """
        INSERT INTO instance_denylist (host, is_active, reason, note, created_at, updated_at)
        VALUES (?, 1, ?, ?, ?, ?)
        ON CONFLICT(host)
        DO UPDATE SET
          is_active = 1,
          reason = excluded.reason,
          note = excluded.note,
          updated_at = excluded.updated_at
        """,
        (host, reason, note, ts, ts),
    )


def upsert_unblock(conn: sqlite3.Connection, host: str) -> None:
    ts = now_ms()
    conn.execute(
        """
        INSERT INTO instance_denylist (host, is_active, reason, note, created_at, updated_at)
        VALUES (?, 0, NULL, NULL, ?, ?)
        ON CONFLICT(host)
        DO UPDATE SET
          is_active = 0,
          updated_at = excluded.updated_at
        """,
        (host, ts, ts),
    )


def collect_post_check_counts(
    main_conn: sqlite3.Connection,
    similarity_conn: sqlite3.Connection | None,
    host: str,
) -> dict[str, int]:
    counts = purge_host_data(main_conn, host, dry_run=True)
    if similarity_conn is None:
        counts.update(
            {
                "similarity_items_as_source": -1,
                "similarity_items_as_similar": -1,
                "similarity_items_total_mentions": -1,
                "similarity_sources": -1,
            }
        )
        return counts
    counts.update(collect_similarity_host_stats(similarity_conn, host))
    return counts


def run_purge(args: argparse.Namespace, host: str) -> None:
    if args.purge_now and not args.dry_run and not args.yes:
        raise SystemExit("Refusing destructive purge without --yes.")

    started_at = time.monotonic()
    log_info(
        "purge-start",
        host=host,
        dry_run=bool(args.dry_run),
        main_db=Path(args.db).resolve(),
        similarity_db=Path(args.similarity_db).resolve(),
    )

    main_counts: dict[str, int]
    pre_main_counts: dict[str, int]
    with connect(Path(args.db).resolve()) as conn:
        pre_main_counts = purge_host_data(conn, host, dry_run=True)
        log_info_block("precheck-main", host=host, counts=pre_main_counts)
        if args.dry_run:
            main_counts = dict(pre_main_counts)
        else:
            main_counts = purge_host_data(
                conn,
                host,
                dry_run=False,
                precomputed_counts=pre_main_counts,
            )

    similarity_counts: dict[str, int] = {}
    pre_similarity_counts: dict[str, int] = {}
    sim_path = Path(args.similarity_db).resolve()
    sim_exists = sim_path.exists()
    sim_conn_for_postcheck: sqlite3.Connection | None = None
    if sim_path.exists():
        with connect(sim_path) as sim_conn:
            indexes_ready = ensure_similarity_purge_indexes(sim_conn)
            if not indexes_ready:
                log_info(
                    "similarity-indexes-skip",
                    host=host,
                    reason="index-create-failed-continue-without-indexes",
                )
            pre_similarity_counts = collect_similarity_host_stats(sim_conn, host)
            log_info_block(
                "precheck-similarity",
                host=host,
                similarity_items_as_source=pre_similarity_counts["similarity_items_as_source"],
                similarity_items_as_similar=pre_similarity_counts["similarity_items_as_similar"],
                similarity_items_total_mentions=pre_similarity_counts[
                    "similarity_items_total_mentions"
                ],
                similarity_sources=pre_similarity_counts["similarity_sources"],
            )
            similarity_counts = {
                "similarity_items": pre_similarity_counts["similarity_items"],
                "similarity_sources": pre_similarity_counts["similarity_sources"],
            }
            if not args.dry_run:
                similarity_counts = purge_similarity_for_host(
                    sim_conn,
                    host,
                    dry_run=False,
                    precomputed_counts=similarity_counts,
                )
    else:
        log_info("precheck-similarity-skip", host=host, reason="similarity-db-not-found")

    log_info_block(
        "purge-finish",
        host=host,
        dry_run=bool(args.dry_run),
        main_deleted=main_counts,
        similarity_deleted=similarity_counts,
    )

    if args.dry_run:
        log_info("postcheck-skip", host=host, reason="dry-run")
    else:
        log_info("postcheck-start", host=host)
        main_conn = connect(Path(args.db).resolve())
        try:
            if sim_exists:
                sim_conn_for_postcheck = connect(sim_path)
            post_counts = collect_post_check_counts(main_conn, sim_conn_for_postcheck, host)
        finally:
            main_conn.close()
            if sim_conn_for_postcheck is not None:
                sim_conn_for_postcheck.close()
        log_info_block("postcheck-finish", host=host, counts=post_counts)

    mode = "dry-run" if args.dry_run else "applied"
    print(f"purge ({mode}) host={host}")
    print("main_db_removed:", main_counts)
    print("similarity_db_removed:", similarity_counts)
    log_info(
        "purge-done",
        host=host,
        duration_ms=int((time.monotonic() - started_at) * 1000),
    )


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if args.command == "list":
        with connect(db_path) as conn:
            ensure_moderation_schema(conn)
            where = "WHERE is_active = 1" if args.active_only else ""
            rows = conn.execute(
                f"""
                SELECT host, is_active, reason, note, created_at, updated_at
                FROM instance_denylist
                {where}
                ORDER BY host ASC
                """
            ).fetchall()
        for row in rows:
            print(
                "\t".join(
                    [
                        str(row["host"]),
                        "active" if int(row["is_active"]) == 1 else "inactive",
                        str(row["reason"] or ""),
                        str(row["note"] or ""),
                        str(row["created_at"]),
                        str(row["updated_at"]),
                    ]
                )
            )
        return

    host = require_host(args.host)
    log_info(
        "command-start",
        command=args.command,
        host=host,
        purge_now=bool(getattr(args, "purge_now", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    with connect(db_path) as conn:
        with conn:
            ensure_moderation_schema(conn)
            if args.command == "block":
                upsert_block(conn, host, args.reason, args.note)
            elif args.command == "unblock":
                upsert_unblock(conn, host)
            else:
                raise SystemExit(f"Unknown command: {args.command}")

    if args.command == "block":
        log_info("host-blocked", host=host)
    elif args.command == "unblock":
        log_info("host-unblocked", host=host)

    print(f"{args.command} host={host}")
    if args.command == "block" and args.purge_now:
        run_purge(args, host)


if __name__ == "__main__":
    main()
