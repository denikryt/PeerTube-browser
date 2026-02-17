#!/usr/bin/env python3
"""CLI for channel-level moderation (block/allow/list)."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))
api_dir = server_dir / "api"
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from scripts.cli_format import CompactHelpFormatter
from server_config import DEFAULT_DB_PATH
from data.moderation import ensure_moderation_schema, normalize_host, now_ms

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def parse_args() -> argparse.Namespace:
    repo_root = script_dir.parents[2]
    parser = argparse.ArgumentParser(
        description="Manage channel blocklist entries.",
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=(repo_root / DEFAULT_DB_PATH).resolve(),
        help="Path to main SQLite DB.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    block = sub.add_parser("block", help="Block channel by URL or id/instance pair.")
    block_source = block.add_mutually_exclusive_group(required=True)
    block_source.add_argument("--video-url", help="Video URL used to resolve channel.")
    block_source.add_argument("--channel-id", help="Channel ID.")
    block.add_argument("--instance", help="Instance host (required with --channel-id).")
    block.add_argument("--reason", default=None, help="Optional reason.")

    unblock = sub.add_parser("unblock", help="Unblock channel by id/instance pair.")
    unblock.add_argument("--channel-id", required=True, help="Channel ID.")
    unblock.add_argument("--instance", required=True, help="Instance host.")

    list_cmd = sub.add_parser("list", help="List channel moderation rows.")
    list_cmd.add_argument(
        "--status",
        choices=["blocked", "allowed"],
        default=None,
        help="Filter by status.",
    )
    list_cmd.add_argument("--instance", default=None, help="Filter by instance host.")

    return parser.parse_args()


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.as_posix())
    conn.row_factory = sqlite3.Row
    return conn


def require_host(value: str | None) -> str:
    host = normalize_host(value)
    if not host:
        raise SystemExit(f"Invalid host: {value}")
    return host


def parse_video_ref(video_url: str) -> tuple[str, str]:
    parsed = urlparse(video_url)
    host = require_host(parsed.hostname)

    query = parse_qs(parsed.query)
    candidate = None
    for key in ("v", "video", "uuid", "id"):
        raw = query.get(key, [None])[0]
        if isinstance(raw, str) and raw.strip():
            candidate = raw.strip()
            break

    parts = [part for part in parsed.path.split("/") if part]
    if candidate is None and parts:
        for idx, part in enumerate(parts):
            lowered = part.lower()
            if lowered == "watch" and idx + 1 < len(parts):
                candidate = parts[idx + 1]
                break
            if lowered == "w" and idx + 1 < len(parts):
                candidate = parts[idx + 1]
                break
        if candidate is None:
            candidate = parts[-1]

    if not candidate:
        raise SystemExit(f"Could not resolve video id/uuid from URL: {video_url}")
    return host, candidate


def resolve_channel_from_video(
    conn: sqlite3.Connection,
    *,
    video_url: str,
) -> tuple[str, str]:
    host, video_ref = parse_video_ref(video_url)

    where = "(video_uuid = ? OR video_id = ?)"
    params: list[str] = [host, video_ref, video_ref]

    # Prefer UUID lookups when URL clearly carries one.
    if UUID_RE.match(video_ref):
        where = "video_uuid = ?"
        params = [host, video_ref]

    row = conn.execute(
        f"""
        SELECT channel_id, instance_domain
        FROM videos
        WHERE instance_domain = ?
          AND {where}
        LIMIT 1
        """,
        params,
    ).fetchone()
    if row is None:
        raise SystemExit(
            f"Video not found in DB for host={host} ref={video_ref}; crawl/sync data first."
        )
    channel_id = str(row["channel_id"] or "").strip()
    instance_domain = require_host(str(row["instance_domain"] or ""))
    if not channel_id:
        raise SystemExit(
            f"Resolved video has no channel_id in DB for host={host} ref={video_ref}."
        )
    return channel_id, instance_domain


def upsert_channel_status(
    conn: sqlite3.Connection,
    *,
    channel_id: str,
    instance_domain: str,
    status: str,
    reason: str | None,
    source_video_url: str | None,
) -> None:
    ts = now_ms()
    conn.execute(
        """
        INSERT INTO channel_moderation (
          channel_id,
          instance_domain,
          status,
          reason,
          source_video_url,
          created_at,
          updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(channel_id, instance_domain)
        DO UPDATE SET
          status = excluded.status,
          reason = excluded.reason,
          source_video_url = excluded.source_video_url,
          updated_at = excluded.updated_at
        """,
        (
            channel_id,
            instance_domain,
            status,
            reason,
            source_video_url,
            ts,
            ts,
        ),
    )


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).resolve()

    if args.command == "list":
        where: list[str] = []
        params: list[str] = []
        if args.status:
            where.append("status = ?")
            params.append(args.status)
        if args.instance:
            where.append("instance_domain = ?")
            params.append(require_host(args.instance))
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        with connect(db_path) as conn:
            ensure_moderation_schema(conn)
            rows = conn.execute(
                f"""
                SELECT
                  channel_id,
                  instance_domain,
                  status,
                  reason,
                  source_video_url,
                  created_at,
                  updated_at
                FROM channel_moderation
                {where_sql}
                ORDER BY instance_domain ASC, channel_id ASC
                """,
                tuple(params),
            ).fetchall()
        for row in rows:
            print(
                "\t".join(
                    [
                        str(row["channel_id"]),
                        str(row["instance_domain"]),
                        str(row["status"]),
                        str(row["reason"] or ""),
                        str(row["source_video_url"] or ""),
                        str(row["created_at"]),
                        str(row["updated_at"]),
                    ]
                )
            )
        return

    with connect(db_path) as conn:
        with conn:
            ensure_moderation_schema(conn)
            if args.command == "block":
                if args.video_url:
                    channel_id, instance_domain = resolve_channel_from_video(
                        conn, video_url=args.video_url
                    )
                    source_video_url = args.video_url
                else:
                    if not args.instance:
                        raise SystemExit("--instance is required with --channel-id")
                    channel_id = str(args.channel_id).strip()
                    instance_domain = require_host(args.instance)
                    source_video_url = None
                if not channel_id:
                    raise SystemExit("Invalid channel id")

                upsert_channel_status(
                    conn,
                    channel_id=channel_id,
                    instance_domain=instance_domain,
                    status="blocked",
                    reason=args.reason,
                    source_video_url=source_video_url,
                )
                print(f"block channel_id={channel_id} instance={instance_domain}")
                return

            if args.command == "unblock":
                channel_id = str(args.channel_id).strip()
                instance_domain = require_host(args.instance)
                if not channel_id:
                    raise SystemExit("Invalid channel id")
                upsert_channel_status(
                    conn,
                    channel_id=channel_id,
                    instance_domain=instance_domain,
                    status="allowed",
                    reason=None,
                    source_video_url=None,
                )
                print(f"unblock channel_id={channel_id} instance={instance_domain}")
                return

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
