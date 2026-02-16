#!/usr/bin/env python3
import argparse
import logging
import sqlite3
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.append(str(script_dir.parents[2]))

from data.popularity import compute_popularity
from data.time import now_ms
from scripts.cli_format import CompactHelpFormatter


def ensure_popularity_schema(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(videos)")}
    if "popularity" not in columns:
        conn.execute("ALTER TABLE videos ADD COLUMN popularity REAL NOT NULL DEFAULT 0")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_videos_popularity ON videos (popularity DESC)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recompute popularity for all videos.",
        formatter_class=CompactHelpFormatter,
    )
    repo_root = script_dir.parents[4]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH, DEFAULT_POPULARITY_LIKE_WEIGHT

    default_db = (repo_root / DEFAULT_DB_PATH).resolve()
    default_db_display = DEFAULT_DB_PATH
    parser.add_argument(
        "--db",
        default=str(default_db),
        metavar="PATH",
        help=f"Path to database (default: {default_db_display})",
    )
    parser.add_argument(
        "--like-weight",
        type=float,
        default=float(DEFAULT_POPULARITY_LIKE_WEIGHT),
        metavar="N",
        help=f"Like multiplier in popularity formula (default: {DEFAULT_POPULARITY_LIKE_WEIGHT}).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Overwrite popularity values for all rows.",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Update only rows that likely were not scored yet "
            "(popularity IS NULL or popularity = 0)."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log progress counter while updating rows.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    conn = sqlite3.connect(str(Path(args.db)))
    conn.row_factory = sqlite3.Row
    ensure_popularity_schema(conn)

    now_ms_value = now_ms()
    if args.reset:
        cursor = conn.execute(
            "SELECT video_id, instance_domain, title, views, likes, published_at, popularity "
            "FROM videos"
        )
    elif args.incremental:
        cursor = conn.execute(
            "SELECT video_id, instance_domain, title, views, likes, published_at, popularity "
            "FROM videos WHERE popularity IS NULL OR popularity = 0"
        )
    else:
        cursor = conn.execute(
            "SELECT video_id, instance_domain, title, views, likes, published_at, popularity "
            "FROM videos"
        )
    updates: list[tuple[float, str, str]] = []
    total_rows = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    processed = 0
    for row in cursor:
        if not args.reset and not args.incremental and row["popularity"] is not None:
            continue
        score = compute_popularity(
            row["views"],
            row["likes"],
            row["published_at"],
            float(args.like_weight),
            now_ms_value=now_ms_value,
        )
        updates.append((score, row["video_id"], row["instance_domain"]))
        processed += 1
        if args.verbose:
            logging.info("%d/%d", processed, total_rows)

    if updates:
        conn.executemany(
            "UPDATE videos SET popularity = ? WHERE video_id = ? AND instance_domain = ?",
            updates,
        )
        conn.commit()
    logging.info("popularity updated rows=%d", len(updates))


if __name__ == "__main__":
    main()
