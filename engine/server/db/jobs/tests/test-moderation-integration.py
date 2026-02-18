#!/usr/bin/env python3
"""Moderation integration regression test on isolated SQLite fixtures.

Can run on:
- deterministic synthetic fixtures (default),
- sampled real data copied from production DB (`--sample-from-prod`).
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

script_dir = Path(__file__).resolve().parent
repo_root = script_dir.parents[4]
server_dir = script_dir.parents[2]
api_dir = repo_root / "engine" / "server" / "api"
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from scripts.cli_format import CompactHelpFormatter
from server_config import DEFAULT_DB_PATH
from data.moderation import (
    ensure_moderation_schema,
    list_active_denied_hosts,
    normalize_host,
    now_ms,
    purge_host_data,
    purge_similarity_for_host,
)
from data.serving_moderation import apply_serving_moderation_filters


@dataclass(frozen=True)
class VideoRef:
    """Minimal video identity used by moderation assertions."""

    video_id: str
    video_uuid: str
    channel_id: str
    host: str


@dataclass(frozen=True)
class FixtureContext:
    """Selected hosts/videos used by the integration scenario."""

    allowed_host: str
    deny_host: str
    ignored_host: str
    stale_host: str
    allowed: VideoRef
    blocked: VideoRef
    deny: VideoRef
    ignored: VideoRef
    stale: VideoRef


def parse_args() -> argparse.Namespace:
    """Handle parse args."""
    parser = argparse.ArgumentParser(
        description="Run moderation integration test against temporary fixture DBs.",
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument(
        "--workdir",
        default=str((repo_root / "tmp" / "moderation-integration").resolve()),
        help="Temp directory for fixture databases.",
    )
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Keep fixture files after run.",
    )
    parser.add_argument(
        "--sample-from-prod",
        action="store_true",
        help="Build fixtures from sampled real rows in source DB instead of synthetic seed.",
    )
    parser.add_argument(
        "--source-db",
        default=str((repo_root / DEFAULT_DB_PATH).resolve()),
        help="Source production DB path for --sample-from-prod mode.",
    )
    parser.add_argument(
        "--sample-hosts",
        type=int,
        default=4,
        help="Number of hosts to sample from source DB (minimum 4).",
    )
    parser.add_argument(
        "--sample-channels-per-host",
        type=int,
        default=3,
        help="Max channels sampled per host.",
    )
    parser.add_argument(
        "--sample-videos-per-host",
        type=int,
        default=8,
        help="Max videos sampled per host.",
    )
    parser.add_argument(
        "--target-host",
        default="",
        help=(
            "Optional host to include in sampled fixtures as the deny/purge target "
            "(requires --sample-from-prod)."
        ),
    )
    return parser.parse_args()


def connect(path: Path) -> sqlite3.Connection:
    """Handle connect."""
    conn = sqlite3.connect(path.as_posix())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def connect_ro(path: Path) -> sqlite3.Connection:
    """Handle connect ro."""
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    """Handle count rows."""
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def ensure_main_schema(conn: sqlite3.Connection) -> None:
    """Handle ensure main schema."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS instances (
          host TEXT PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS channels (
          channel_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          channel_name TEXT,
          PRIMARY KEY (channel_id, instance_domain)
        );
        CREATE TABLE IF NOT EXISTS videos (
          video_id TEXT NOT NULL,
          video_uuid TEXT,
          instance_domain TEXT NOT NULL,
          channel_id TEXT,
          title TEXT,
          PRIMARY KEY (video_id, instance_domain)
        );
        CREATE TABLE IF NOT EXISTS video_embeddings (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          embedding BLOB,
          embedding_dim INTEGER,
          model_name TEXT,
          created_at TEXT,
          PRIMARY KEY (video_id, instance_domain)
        );
        CREATE TABLE IF NOT EXISTS instance_crawl_progress (
          host TEXT PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS channel_crawl_progress (
          instance_domain TEXT PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS video_crawl_progress (
          instance_domain TEXT PRIMARY KEY
        );
        """
    )


def ensure_similarity_schema(conn: sqlite3.Connection) -> None:
    """Handle ensure similarity schema."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS similarity_sources (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          computed_at INTEGER NOT NULL,
          PRIMARY KEY (video_id, instance_domain)
        );
        CREATE TABLE IF NOT EXISTS similarity_items (
          source_video_id TEXT NOT NULL,
          source_instance_domain TEXT NOT NULL,
          similar_video_id TEXT NOT NULL,
          similar_instance_domain TEXT NOT NULL,
          score REAL,
          rank INTEGER NOT NULL,
          PRIMARY KEY (
            source_video_id,
            source_instance_domain,
            similar_video_id,
            similar_instance_domain
          )
        );
        """
    )


def assert_eq(actual: object, expected: object, message: str) -> None:
    """Handle assert eq."""
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected} actual={actual}")


def _insert_similarity_seed(
    similarity_conn: sqlite3.Connection,
    ctx: FixtureContext,
    ts: int,
) -> None:
    """Handle insert similarity seed."""
    with similarity_conn:
        similarity_conn.executemany(
            """
            INSERT OR REPLACE INTO similarity_sources(video_id, instance_domain, computed_at)
            VALUES (?, ?, ?)
            """,
            [
                (ctx.allowed.video_id, ctx.allowed.host, ts),
                (ctx.deny.video_id, ctx.deny.host, ts),
                (ctx.ignored.video_id, ctx.ignored.host, ts),
                (ctx.stale.video_id, ctx.stale.host, ts),
            ],
        )
        similarity_conn.executemany(
            """
            INSERT OR REPLACE INTO similarity_items(
              source_video_id,
              source_instance_domain,
              similar_video_id,
              similar_instance_domain,
              score,
              rank
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (ctx.allowed.video_id, ctx.allowed.host, ctx.deny.video_id, ctx.deny.host, 0.91, 1),
                (
                    ctx.allowed.video_id,
                    ctx.allowed.host,
                    ctx.blocked.video_id,
                    ctx.blocked.host,
                    0.85,
                    2,
                ),
                (ctx.deny.video_id, ctx.deny.host, ctx.allowed.video_id, ctx.allowed.host, 0.82, 1),
                (
                    ctx.ignored.video_id,
                    ctx.ignored.host,
                    ctx.allowed.video_id,
                    ctx.allowed.host,
                    0.81,
                    1,
                ),
                (ctx.stale.video_id, ctx.stale.host, ctx.allowed.video_id, ctx.allowed.host, 0.80, 1),
            ],
        )


def _insert_moderation_seed(main_conn: sqlite3.Connection, ctx: FixtureContext, ts: int) -> None:
    """Handle insert moderation seed."""
    with main_conn:
        main_conn.execute(
            """
            INSERT INTO instance_denylist(host, is_active, reason, note, created_at, updated_at)
            VALUES (?, 1, ?, ?, ?, ?)
            ON CONFLICT(host) DO UPDATE SET
              is_active = 1,
              reason = excluded.reason,
              note = excluded.note,
              updated_at = excluded.updated_at
            """,
            (ctx.deny_host, "test deny", "task35", ts, ts),
        )
        main_conn.execute(
            """
            INSERT INTO instance_denylist(host, is_active, reason, note, created_at, updated_at)
            VALUES (?, 1, ?, ?, ?, ?)
            ON CONFLICT(host) DO UPDATE SET
              is_active = 1,
              reason = excluded.reason,
              note = excluded.note,
              updated_at = excluded.updated_at
            """,
            (ctx.ignored_host, "test ignore", "task32", ts, ts),
        )
        main_conn.execute(
            """
            INSERT INTO channel_moderation(
              channel_id,
              instance_domain,
              status,
              reason,
              source_video_url,
              created_at,
              updated_at
            )
            VALUES (?, ?, 'blocked', ?, ?, ?, ?)
            ON CONFLICT(channel_id, instance_domain) DO UPDATE SET
              status = excluded.status,
              reason = excluded.reason,
              source_video_url = excluded.source_video_url,
              updated_at = excluded.updated_at
            """,
            (
                ctx.blocked.channel_id,
                ctx.blocked.host,
                "test blocked",
                f"https://{ctx.blocked.host}/videos/watch/{ctx.blocked.video_uuid}",
                ts,
                ts,
            ),
        )


def seed_synthetic_fixtures(main_db: Path, similarity_db: Path) -> FixtureContext:
    """Handle seed synthetic fixtures."""
    logging.info("[seed] mode=synthetic main_db=%s similarity_db=%s", main_db, similarity_db)

    ctx = FixtureContext(
        allowed_host="allowed.example",
        deny_host="deny.example",
        ignored_host="ignored.example",
        stale_host="stale.example",
        allowed=VideoRef("v_allowed", "uuid-allowed", "ch_allowed", "allowed.example"),
        blocked=VideoRef("v_blocked", "uuid-blocked", "ch_blocked", "allowed.example"),
        deny=VideoRef("v_deny", "uuid-deny", "ch_deny", "deny.example"),
        ignored=VideoRef("v_ignored", "uuid-ignored", "ch_ignored", "ignored.example"),
        stale=VideoRef("v_stale", "uuid-stale", "ch_stale", "stale.example"),
    )
    ts = now_ms()

    with connect(main_db) as conn:
        ensure_main_schema(conn)
        ensure_moderation_schema(conn)
        with conn:
            hosts = [ctx.allowed_host, ctx.deny_host, ctx.ignored_host, ctx.stale_host]
            conn.executemany(
                "INSERT OR IGNORE INTO instances(host) VALUES (?)",
                [(host,) for host in hosts],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO instance_crawl_progress(host) VALUES (?)",
                [(host,) for host in hosts],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO channel_crawl_progress(instance_domain) VALUES (?)",
                [(host,) for host in hosts],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO video_crawl_progress(instance_domain) VALUES (?)",
                [(host,) for host in hosts],
            )

            channels = [
                (ctx.allowed.channel_id, ctx.allowed.host, "Allowed Channel"),
                (ctx.blocked.channel_id, ctx.blocked.host, "Blocked Channel"),
                (ctx.deny.channel_id, ctx.deny.host, "Deny Channel"),
                (ctx.ignored.channel_id, ctx.ignored.host, "Ignored Channel"),
                (ctx.stale.channel_id, ctx.stale.host, "Stale Channel"),
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO channels(channel_id, instance_domain, channel_name) VALUES (?, ?, ?)",
                channels,
            )

            videos = [
                (
                    ctx.allowed.video_id,
                    ctx.allowed.video_uuid,
                    ctx.allowed.host,
                    ctx.allowed.channel_id,
                    "Allowed video",
                ),
                (
                    ctx.blocked.video_id,
                    ctx.blocked.video_uuid,
                    ctx.blocked.host,
                    ctx.blocked.channel_id,
                    "Blocked channel video",
                ),
                (ctx.deny.video_id, ctx.deny.video_uuid, ctx.deny.host, ctx.deny.channel_id, "Denied host video"),
                (
                    ctx.ignored.video_id,
                    ctx.ignored.video_uuid,
                    ctx.ignored.host,
                    ctx.ignored.channel_id,
                    "Ignored host video",
                ),
                (ctx.stale.video_id, ctx.stale.video_uuid, ctx.stale.host, ctx.stale.channel_id, "Stale host video"),
            ]
            conn.executemany(
                """
                INSERT OR REPLACE INTO videos(video_id, video_uuid, instance_domain, channel_id, title)
                VALUES (?, ?, ?, ?, ?)
                """,
                videos,
            )
            conn.executemany(
                """
                INSERT OR REPLACE INTO video_embeddings(
                  video_id,
                  instance_domain,
                  embedding,
                  embedding_dim,
                  model_name,
                  created_at
                )
                VALUES (?, ?, ?, 3, 'test-model', 'now')
                """,
                [
                    (ctx.allowed.video_id, ctx.allowed.host, b"a"),
                    (ctx.blocked.video_id, ctx.blocked.host, b"b"),
                    (ctx.deny.video_id, ctx.deny.host, b"c"),
                    (ctx.ignored.video_id, ctx.ignored.host, b"d"),
                    (ctx.stale.video_id, ctx.stale.host, b"e"),
                ],
            )
        _insert_moderation_seed(conn, ctx, ts)
        logging.info(
            "[seed][main] instances=%d channels=%d videos=%d embeddings=%d denylist=%d channel_moderation=%d",
            count_rows(conn, "instances"),
            count_rows(conn, "channels"),
            count_rows(conn, "videos"),
            count_rows(conn, "video_embeddings"),
            count_rows(conn, "instance_denylist"),
            count_rows(conn, "channel_moderation"),
        )

    with connect(similarity_db) as conn:
        ensure_similarity_schema(conn)
        _insert_similarity_seed(conn, ctx, ts)
        logging.info(
            "[seed][similarity] sources=%d items=%d",
            count_rows(conn, "similarity_sources"),
            count_rows(conn, "similarity_items"),
        )

    return ctx


def _host_candidates(
    src: sqlite3.Connection,
    *,
    required_hosts: int,
    min_videos_per_host: int,
) -> list[str]:
    """Handle host candidates."""
    rows = src.execute(
        """
        SELECT
          v.instance_domain AS host,
          COUNT(*) AS videos_count,
          COUNT(DISTINCT v.channel_id) AS channels_count
        FROM videos v
        JOIN video_embeddings e
          ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
        WHERE v.channel_id IS NOT NULL
          AND TRIM(v.channel_id) != ''
        GROUP BY v.instance_domain
        HAVING COUNT(*) >= ?
           AND COUNT(DISTINCT v.channel_id) >= 2
        ORDER BY videos_count DESC
        LIMIT ?
        """,
        (min_videos_per_host, max(required_hosts * 4, required_hosts)),
    ).fetchall()
    return [str(row["host"]).strip().lower() for row in rows if row["host"]]


def _host_is_eligible(
    src: sqlite3.Connection,
    host: str,
    *,
    min_videos_per_host: int,
) -> bool:
    """Handle host is eligible."""
    row = src.execute(
        """
        SELECT
          COUNT(*) AS videos_count,
          COUNT(DISTINCT v.channel_id) AS channels_count
        FROM videos v
        JOIN video_embeddings e
          ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
        WHERE v.instance_domain = ?
          AND v.channel_id IS NOT NULL
          AND TRIM(v.channel_id) != ''
        """,
        (host,),
    ).fetchone()
    if row is None:
        return False
    return int(row["videos_count"] or 0) >= min_videos_per_host and int(
        row["channels_count"] or 0
    ) >= 2


def _sample_channels_for_host(
    src: sqlite3.Connection,
    host: str,
    limit: int,
) -> list[dict[str, str]]:
    """Handle sample channels for host."""
    rows = src.execute(
        """
        SELECT
          v.channel_id AS channel_id,
          COALESCE(c.channel_name, MAX(v.channel_name), v.channel_id) AS channel_name,
          COUNT(*) AS videos_count
        FROM videos v
        JOIN video_embeddings e
          ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
        LEFT JOIN channels c
          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain
        WHERE v.instance_domain = ?
          AND v.channel_id IS NOT NULL
          AND TRIM(v.channel_id) != ''
        GROUP BY v.channel_id
        ORDER BY videos_count DESC, v.channel_id ASC
        LIMIT ?
        """,
        (host, limit),
    ).fetchall()
    return [
        {
            "channel_id": str(row["channel_id"]),
            "channel_name": str(row["channel_name"] or row["channel_id"]),
        }
        for row in rows
    ]


def _sample_videos_for_host(
    src: sqlite3.Connection,
    host: str,
    channel_ids: list[str],
    limit: int,
) -> list[dict[str, str]]:
    """Handle sample videos for host."""
    if not channel_ids:
        return []
    selected: list[dict[str, str]] = []
    selected_keys: set[tuple[str, str]] = set()

    def _append_row(row: sqlite3.Row) -> None:
        """Handle append row."""
        key = (str(row["video_id"]), str(row["instance_domain"]))
        if key in selected_keys:
            return
        selected.append(
            {
                "video_id": str(row["video_id"]),
                "video_uuid": str(row["video_uuid"]),
                "instance_domain": str(row["instance_domain"]),
                "channel_id": str(row["channel_id"]),
                "title": str(row["title"] or row["video_id"]),
            }
        )
        selected_keys.add(key)

    for channel_id in channel_ids:
        row = src.execute(
            """
            SELECT
              v.video_id,
              COALESCE(v.video_uuid, v.video_id) AS video_uuid,
              v.instance_domain,
              v.channel_id,
              COALESCE(v.title, v.video_id) AS title
            FROM videos v
            JOIN video_embeddings e
              ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
            WHERE v.instance_domain = ?
              AND v.channel_id = ?
            ORDER BY v.rowid DESC
            LIMIT 1
            """,
            (host, channel_id),
        ).fetchone()
        if row is not None:
            _append_row(row)
        if len(selected) >= limit:
            return selected[:limit]

    placeholders = ", ".join(["?"] * len(channel_ids))
    rows = src.execute(
        f"""
        SELECT
          v.video_id,
          COALESCE(v.video_uuid, v.video_id) AS video_uuid,
          v.instance_domain,
          v.channel_id,
          COALESCE(v.title, v.video_id) AS title
        FROM videos v
        JOIN video_embeddings e
          ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
        WHERE v.instance_domain = ?
          AND v.channel_id IN ({placeholders})
        ORDER BY v.rowid DESC
        LIMIT ?
        """,
        (host, *channel_ids, max(limit * 6, limit)),
    ).fetchall()
    for row in rows:
        _append_row(row)
        if len(selected) >= limit:
            break
    return selected[:limit]


def _sample_embeddings_for_videos(
    src: sqlite3.Connection,
    host: str,
    video_ids: list[str],
) -> list[tuple[object, ...]]:
    """Handle sample embeddings for videos."""
    if not video_ids:
        return []
    placeholders = ", ".join(["?"] * len(video_ids))
    rows = src.execute(
        f"""
        SELECT
          e.video_id,
          e.instance_domain,
          e.embedding,
          e.embedding_dim,
          e.model_name,
          e.created_at
        FROM video_embeddings e
        WHERE e.instance_domain = ?
          AND e.video_id IN ({placeholders})
        """,
        (host, *video_ids),
    ).fetchall()
    out: list[tuple[object, ...]] = []
    for row in rows:
        out.append(
            (
                str(row["video_id"]),
                str(row["instance_domain"]),
                row["embedding"],
                int(row["embedding_dim"] or 0),
                str(row["model_name"] or "sampled-model"),
                str(row["created_at"] or "sampled"),
            )
        )
    return out


def _pick_video_for_channel(videos: list[dict[str, str]], channel_id: str) -> VideoRef:
    """Handle pick video for channel."""
    for video in videos:
        if video["channel_id"] == channel_id:
            return VideoRef(
                video_id=video["video_id"],
                video_uuid=video["video_uuid"],
                channel_id=video["channel_id"],
                host=video["instance_domain"],
            )
    raise RuntimeError(f"No videos found for channel {channel_id}")


def _pick_any_video(videos: list[dict[str, str]]) -> VideoRef:
    """Handle pick any video."""
    if not videos:
        raise RuntimeError("Host sample has no videos")
    v = videos[0]
    return VideoRef(
        video_id=v["video_id"],
        video_uuid=v["video_uuid"],
        channel_id=v["channel_id"],
        host=v["instance_domain"],
    )


def seed_prod_sample_fixtures(
    main_db: Path,
    similarity_db: Path,
    source_db: Path,
    *,
    sample_hosts: int,
    sample_channels_per_host: int,
    sample_videos_per_host: int,
    target_host: str | None = None,
) -> FixtureContext:
    """Handle seed prod sample fixtures."""
    if sample_hosts < 4:
        raise RuntimeError("--sample-hosts must be >= 4")
    if sample_channels_per_host < 2:
        raise RuntimeError("--sample-channels-per-host must be >= 2")
    if sample_videos_per_host < 2:
        raise RuntimeError("--sample-videos-per-host must be >= 2")
    if not source_db.exists():
        raise FileNotFoundError(f"Source DB not found: {source_db}")

    logging.info(
        "[seed] mode=prod-sample source_db=%s main_db=%s similarity_db=%s target_host=%s",
        source_db,
        main_db,
        similarity_db,
        target_host or "",
    )

    with connect_ro(source_db) as src:
        hosts = _host_candidates(
            src,
            required_hosts=sample_hosts,
            min_videos_per_host=max(sample_videos_per_host, 4),
        )
        if len(hosts) < 4:
            raise RuntimeError(
                "Not enough source hosts with >=2 channels and embedded videos for prod sampling"
            )
        if target_host:
            normalized_target = normalize_host(target_host)
            if not normalized_target:
                raise RuntimeError(f"Invalid --target-host value: {target_host!r}")
            if not _host_is_eligible(
                src,
                normalized_target,
                min_videos_per_host=max(sample_videos_per_host, 4),
            ):
                raise RuntimeError(
                    f"Target host {normalized_target} is not eligible "
                    "(needs >=2 channels with embeddings and enough videos)"
                )
            other_hosts = [host for host in hosts if host != normalized_target]
            if len(other_hosts) < 3:
                raise RuntimeError(
                    "Not enough additional hosts for fixture roles; increase --sample-hosts"
                )
            role_hosts = [
                other_hosts[0],      # allowed
                normalized_target,   # deny (target for block/purge)
                other_hosts[1],      # ignored
                other_hosts[2],      # stale
            ]
        else:
            role_hosts = hosts[:4]
        logging.info(
            "[seed][prod-sample] selected_hosts=%s",
            role_hosts,
        )

        sampled: dict[str, dict[str, object]] = {}
        with connect(main_db) as dst:
            ensure_main_schema(dst)
            ensure_moderation_schema(dst)
            with dst:
                for host in role_hosts:
                    channels = _sample_channels_for_host(src, host, sample_channels_per_host)
                    if len(channels) < 2:
                        raise RuntimeError(f"Host {host} has <2 sampled channels")
                    channel_ids = [entry["channel_id"] for entry in channels]
                    videos = _sample_videos_for_host(src, host, channel_ids, sample_videos_per_host)
                    if len(videos) < 2:
                        raise RuntimeError(f"Host {host} has <2 sampled videos")

                    kept_channel_ids = {video["channel_id"] for video in videos}
                    channels = [entry for entry in channels if entry["channel_id"] in kept_channel_ids]
                    if len(channels) < 2:
                        raise RuntimeError(f"Host {host} has <2 channels with sampled videos")

                    embeddings = _sample_embeddings_for_videos(
                        src,
                        host,
                        [video["video_id"] for video in videos],
                    )
                    if len(embeddings) < len(videos):
                        logging.warning(
                            "[seed][prod-sample] host=%s embeddings=%d videos=%d (continuing with available embeddings)",
                            host,
                            len(embeddings),
                            len(videos),
                        )

                    dst.execute("INSERT OR IGNORE INTO instances(host) VALUES (?)", (host,))
                    dst.execute(
                        "INSERT OR IGNORE INTO instance_crawl_progress(host) VALUES (?)",
                        (host,),
                    )
                    dst.execute(
                        "INSERT OR IGNORE INTO channel_crawl_progress(instance_domain) VALUES (?)",
                        (host,),
                    )
                    dst.execute(
                        "INSERT OR IGNORE INTO video_crawl_progress(instance_domain) VALUES (?)",
                        (host,),
                    )

                    dst.executemany(
                        "INSERT OR REPLACE INTO channels(channel_id, instance_domain, channel_name) VALUES (?, ?, ?)",
                        [
                            (entry["channel_id"], host, entry["channel_name"]) for entry in channels
                        ],
                    )
                    dst.executemany(
                        """
                        INSERT OR REPLACE INTO videos(video_id, video_uuid, instance_domain, channel_id, title)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                video["video_id"],
                                video["video_uuid"],
                                video["instance_domain"],
                                video["channel_id"],
                                video["title"],
                            )
                            for video in videos
                        ],
                    )
                    dst.executemany(
                        """
                        INSERT OR REPLACE INTO video_embeddings(
                          video_id,
                          instance_domain,
                          embedding,
                          embedding_dim,
                          model_name,
                          created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        embeddings,
                    )

                    sampled[host] = {
                        "channels": channels,
                        "videos": videos,
                    }

                    logging.info(
                        "[seed][prod-sample] host=%s channels=%d videos=%d embeddings=%d",
                        host,
                        len(channels),
                        len(videos),
                        len(embeddings),
                    )

                allowed_host, deny_host, ignored_host, stale_host = role_hosts
                allowed_channels = sampled[allowed_host]["channels"]
                allowed_videos = sampled[allowed_host]["videos"]
                deny_videos = sampled[deny_host]["videos"]
                ignored_videos = sampled[ignored_host]["videos"]
                stale_videos = sampled[stale_host]["videos"]

                allowed_channel_id = str(allowed_channels[0]["channel_id"])
                blocked_channel_id = str(allowed_channels[1]["channel_id"])
                allowed_ref = _pick_video_for_channel(allowed_videos, allowed_channel_id)
                blocked_ref = _pick_video_for_channel(allowed_videos, blocked_channel_id)

                ctx = FixtureContext(
                    allowed_host=allowed_host,
                    deny_host=deny_host,
                    ignored_host=ignored_host,
                    stale_host=stale_host,
                    allowed=allowed_ref,
                    blocked=blocked_ref,
                    deny=_pick_any_video(deny_videos),
                    ignored=_pick_any_video(ignored_videos),
                    stale=_pick_any_video(stale_videos),
                )

                ts = now_ms()
                _insert_moderation_seed(dst, ctx, ts)

            logging.info(
                "[seed][main] instances=%d channels=%d videos=%d embeddings=%d denylist=%d channel_moderation=%d",
                count_rows(dst, "instances"),
                count_rows(dst, "channels"),
                count_rows(dst, "videos"),
                count_rows(dst, "video_embeddings"),
                count_rows(dst, "instance_denylist"),
                count_rows(dst, "channel_moderation"),
            )

    with connect(similarity_db) as sim_conn:
        ensure_similarity_schema(sim_conn)
        _insert_similarity_seed(sim_conn, ctx, now_ms())
        logging.info(
            "[seed][similarity] sources=%d items=%d",
            count_rows(sim_conn, "similarity_sources"),
            count_rows(sim_conn, "similarity_items"),
        )

    logging.info(
        "[seed][prod-sample] roles allowed=%s deny=%s ignored=%s stale=%s",
        ctx.allowed_host,
        ctx.deny_host,
        ctx.ignored_host,
        ctx.stale_host,
    )
    logging.info(
        "[seed][prod-sample] videos allowed=%s blocked=%s deny=%s ignored=%s stale=%s",
        ctx.allowed.video_id,
        ctx.blocked.video_id,
        ctx.deny.video_id,
        ctx.ignored.video_id,
        ctx.stale.video_id,
    )

    return ctx


def run_test(main_db: Path, similarity_db: Path, ctx: FixtureContext) -> None:
    """Handle run test."""
    logging.info("[test] start moderation integration")

    # Step 1: purge ignored host data.
    logging.info("[test][step1] purge ignored host=%s", ctx.ignored_host)
    with connect(main_db) as conn:
        ignored_counts = purge_host_data(conn, ctx.ignored_host, dry_run=False)
        logging.info("[test][step1][main] purge counts=%s", ignored_counts)
        if int(ignored_counts.get("videos", 0)) <= 0:
            raise AssertionError("Expected ignored host purge to remove videos")
    with connect(similarity_db) as sim_conn:
        ignored_sim_counts = purge_similarity_for_host(sim_conn, ctx.ignored_host, dry_run=False)
        logging.info("[test][step1][similarity] purge counts=%s", ignored_sim_counts)
        if int(ignored_sim_counts.get("similarity_sources", 0)) <= 0:
            raise AssertionError("Expected ignored host purge to remove similarity_sources")

    # Step 2: strict host reconciliation with denylist subtraction.
    logging.info("[test][step2] reconcile hosts with denylist subtraction")
    with connect(main_db) as conn:
        join_hosts = {ctx.allowed_host, ctx.deny_host, "new.sample.host"}
        denied_hosts = list_active_denied_hosts(conn)
        effective_hosts = join_hosts - denied_hosts
        current_hosts = {
            str(row[0]).strip().lower()
            for row in conn.execute("SELECT host FROM instances").fetchall()
        }
        stale_hosts = current_hosts - effective_hosts
        logging.info(
            "[test][step2] join_hosts=%s denied_hosts=%s effective_hosts=%s current_hosts=%s stale_hosts=%s",
            sorted(join_hosts),
            sorted(denied_hosts),
            sorted(effective_hosts),
            sorted(current_hosts),
            sorted(stale_hosts),
        )

    for host in sorted(stale_hosts):
        logging.info("[test][step2] purge stale host=%s", host)
        with connect(main_db) as conn:
            stale_main_counts = purge_host_data(conn, host, dry_run=False)
            logging.info("[test][step2][main] host=%s counts=%s", host, stale_main_counts)
        with connect(similarity_db) as sim_conn:
            stale_sim_counts = purge_similarity_for_host(sim_conn, host, dry_run=False)
            logging.info(
                "[test][step2][similarity] host=%s counts=%s",
                host,
                stale_sim_counts,
            )

    # Step 3: serving guarantees via the same helper as server response path.
    logging.info("[test][step3] validate serving moderation filter")
    with connect(main_db) as conn:
        rows = [
            {
                "video_id": ctx.allowed.video_id,
                "instance_domain": ctx.allowed.host,
                "channel_id": ctx.allowed.channel_id,
            },
            {
                "video_id": ctx.blocked.video_id,
                "instance_domain": ctx.blocked.host,
                "channel_id": ctx.blocked.channel_id,
            },
            {
                "video_id": ctx.deny.video_id,
                "instance_domain": ctx.deny.host,
                "channel_id": ctx.deny.channel_id,
            },
        ]

        class _ServerStub:
            """Represent server stub behavior."""
            def __init__(self, db: sqlite3.Connection) -> None:
                """Initialize the instance."""
                self.db = db
                self.db_lock = threading.Lock()
                self.enable_instance_ignore = True
                self.enable_channel_blocklist = True

        filtered, stats = apply_serving_moderation_filters(
            _ServerStub(conn), rows, request_id="moderation-test"
        )
        logging.info(
            "[test][step3] input_rows=%d output_rows=%d kept_ids=%s stats=%s",
            len(rows),
            len(filtered),
            [str(row.get("video_id")) for row in filtered],
            {
                "filtered_by_denylist": (stats.filtered_by_denylist if stats else None),
                "filtered_by_blocked_channel": (
                    stats.filtered_by_blocked_channel if stats else None
                ),
            },
        )
        assert_eq(len(filtered), 1, "Serving filter must keep only one allowed row")
        assert_eq(
            str(filtered[0]["video_id"]),
            ctx.allowed.video_id,
            "Unexpected allowed row",
        )
        if stats is None:
            raise AssertionError("Expected moderation stats from serving filter")
        assert_eq(stats.filtered_by_denylist, 1, "filtered_by_denylist mismatch")
        assert_eq(stats.filtered_by_blocked_channel, 1, "filtered_by_blocked_channel mismatch")

        remaining_hosts = {
            str(row[0]).strip().lower()
            for row in conn.execute("SELECT host FROM instances ORDER BY host").fetchall()
        }
        logging.info("[test][step3] remaining_hosts=%s", sorted(remaining_hosts))
        assert_eq(
            remaining_hosts,
            {ctx.allowed_host},
            "Unexpected instances after reconcile/purge",
        )

        removed_hosts = (ctx.deny_host, ctx.ignored_host, ctx.stale_host)
        placeholders = ", ".join(["?"] * len(removed_hosts))
        removed_host_videos = int(
            conn.execute(
                f"SELECT COUNT(*) FROM videos WHERE instance_domain IN ({placeholders})",
                removed_hosts,
            ).fetchone()[0]
        )
        logging.info("[test][step3] removed_host_videos=%d", removed_host_videos)
        assert_eq(removed_host_videos, 0, "Purged hosts still present in videos table")

    # Step 4: similarity integrity.
    logging.info("[test][step4] validate similarity DB has no blocked host links")
    with connect(similarity_db) as sim_conn:
        removed_hosts = (ctx.deny_host, ctx.ignored_host, ctx.stale_host)
        placeholders = ", ".join(["?"] * len(removed_hosts))
        dangling_similarity = int(
            sim_conn.execute(
                f"""
                SELECT COUNT(*)
                FROM similarity_items
                WHERE source_instance_domain IN ({placeholders})
                   OR similar_instance_domain IN ({placeholders})
                """,
                (*removed_hosts, *removed_hosts),
            ).fetchone()[0]
        )
        logging.info("[test][step4] dangling_similarity=%d", dangling_similarity)
        assert_eq(dangling_similarity, 0, "Similarity rows for purged hosts still exist")

    # Step 5: idempotency replay.
    logging.info("[test][step5] idempotency purge replay")
    for host in (ctx.deny_host, ctx.ignored_host, ctx.stale_host):
        with connect(main_db) as conn:
            replay_main_counts = purge_host_data(conn, host, dry_run=False)
        with connect(similarity_db) as sim_conn:
            replay_sim_counts = purge_similarity_for_host(sim_conn, host, dry_run=False)
        logging.info(
            "[test][step5] host=%s replay_main=%s replay_similarity=%s",
            host,
            replay_main_counts,
            replay_sim_counts,
        )
    logging.info("[test] completed successfully")


def main() -> None:
    """Handle main."""
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.target_host and not args.sample_from_prod:
        raise RuntimeError("--target-host requires --sample-from-prod")

    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    main_db = workdir / "moderation-main.db"
    similarity_db = workdir / "moderation-similarity.db"

    for candidate in (main_db, similarity_db):
        if candidate.exists():
            candidate.unlink()

    if args.sample_from_prod:
        context = seed_prod_sample_fixtures(
            main_db,
            similarity_db,
            Path(args.source_db).resolve(),
            sample_hosts=args.sample_hosts,
            sample_channels_per_host=args.sample_channels_per_host,
            sample_videos_per_host=args.sample_videos_per_host,
            target_host=args.target_host or None,
        )
    else:
        context = seed_synthetic_fixtures(main_db, similarity_db)

    run_test(main_db, similarity_db, context)
    print("Moderation integration test: PASS")

    if not args.keep_workdir:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
