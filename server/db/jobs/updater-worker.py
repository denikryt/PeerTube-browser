#!/usr/bin/env python3
"""Background-style worker: crawl into staging, merge into prod, rebuild ANN."""

from __future__ import annotations

import argparse
import logging
import os
import shlex
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from scripts.cli_format import CompactHelpFormatter


def parse_args() -> argparse.Namespace:
    repo_root = script_dir.parents[2]
    api_dir = repo_root / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import (
        DEFAULT_DB_PATH,
        DEFAULT_INDEX_PATH,
        DEFAULT_SIMILARITY_DB_PATH,
    )

    default_prod = (repo_root / DEFAULT_DB_PATH).resolve()
    default_stage = (repo_root / "server/db/staging-worker.db").resolve()
    default_index = (repo_root / DEFAULT_INDEX_PATH).resolve()
    default_index_meta = default_index.with_suffix(default_index.suffix + ".json")
    default_similarity = (repo_root / DEFAULT_SIMILARITY_DB_PATH).resolve()
    default_rules = (script_dir / "merge_rules.json").resolve()
    default_logs = (repo_root / "server/db/updater-worker.log").resolve()
    default_lock = Path("/tmp/peertube-browser-staging-sync.lock")

    parser = argparse.ArgumentParser(
        description=(
            "Run staging ingest pipeline: crawl -> embeddings -> stop service -> "
            "merge -> incremental jobs -> full ANN rebuild -> start service."
        ),
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument("--prod-db", default=str(default_prod), help="Path to prod DB.")
    parser.add_argument(
        "--staging-db", default=str(default_stage), help="Path to staging DB."
    )
    parser.add_argument(
        "--resume-staging",
        action="store_true",
        help=(
            "Reuse existing staging DB and crawler progress tables instead of "
            "recreating staging from scratch."
        ),
    )
    parser.add_argument(
        "--index-path", default=str(default_index), help="Path to ANN index file."
    )
    parser.add_argument(
        "--index-meta-path",
        default=str(default_index_meta),
        help="Path to ANN metadata json file.",
    )
    parser.add_argument(
        "--similarity-db",
        default=str(default_similarity),
        help="Path to similarity cache DB.",
    )
    parser.add_argument(
        "--merge-rules",
        default=str(default_rules),
        help="Path to merge_rules.json.",
    )
    parser.add_argument(
        "--service-name",
        default="peertube-browser",
        help="Systemd service name to stop/start during merge.",
    )
    parser.add_argument(
        "--skip-systemctl",
        action="store_true",
        help="Do not stop/start service automatically.",
    )
    parser.add_argument("--logs", default=str(default_logs), help="Path to log file.")
    parser.add_argument(
        "--lock-file",
        default=str(default_lock),
        help="Lock file path to prevent overlapping runs.",
    )
    parser.add_argument(
        "--crawler-dir",
        default=str((repo_root / "crawler").resolve()),
        help="Path to crawler directory (must contain dist/*.js CLIs).",
    )
    parser.add_argument("--node-bin", default="node", help="Node executable.")
    parser.add_argument(
        "--python-bin", default=sys.executable, help="Python executable for DB jobs."
    )
    parser.add_argument("--concurrency", type=int, default=4, help="Crawler concurrency.")
    parser.add_argument("--timeout-ms", type=int, default=5000, help="HTTP timeout in ms.")
    parser.add_argument("--max-retries", type=int, default=3, help="HTTP retries.")
    parser.add_argument(
        "--videos-stop-after-full-pages",
        type=int,
        default=2,
        help="Early-stop threshold for videos CLI in new-only mode.",
    )
    parser.add_argument(
        "--max-instances",
        type=int,
        default=0,
        help="Test-only cap for number of instances processed by crawler CLIs (0 = no limit).",
    )
    parser.add_argument(
        "--max-channels",
        type=int,
        default=0,
        help="Test-only cap for number of channels processed by crawler CLIs (0 = no limit).",
    )
    parser.add_argument(
        "--max-videos-pages",
        type=int,
        default=0,
        help="Test-only cap for pages fetched per channel in videos crawl (0 = no limit).",
    )
    parser.add_argument(
        "--whitelist-url",
        default="https://instances.joinpeertube.org/api/v1/instances/hosts?count=5000&healthy=true",
        help="Whitelist URL for instances crawl.",
    )
    parser.add_argument(
        "--skip-local-dead",
        action="store_true",
        help=(
            "Before channels crawl, drop staging instances that are marked "
            "non-ok in local prod DB (instances.health_status != 'ok')."
        ),
    )
    parser.add_argument(
        "--nlist",
        type=int,
        default=4096,
        help="FAISS nlist for ANN build step.",
    )
    parser.add_argument(
        "--inject-replace-embedding-for-test",
        action="store_true",
        help=(
            "Test-only: inject one overlapping video_embeddings row into staging "
            "to validate INSERT_OR_REPLACE merge behavior."
        ),
    )
    parser.add_argument(
        "--fail-before-merge",
        action="store_true",
        help="Test-only: inject failure before merge stage.",
    )
    parser.add_argument(
        "--fail-during-ann-build",
        action="store_true",
        help="Test-only: inject failure at ANN build stage.",
    )
    parser.add_argument(
        "--fail-after-merge-before-similarity",
        action="store_true",
        help="Test-only: inject failure after merge/ANN and before similarity precompute.",
    )
    accel_group = parser.add_mutually_exclusive_group()
    accel_group.add_argument(
        "--gpu",
        dest="use_gpu",
        action="store_true",
        help=(
            "Run embeddings + FAISS build in GPU mode. "
            "No CPU fallback: command fails on GPU error."
        ),
    )
    accel_group.add_argument(
        "--cpu",
        dest="use_gpu",
        action="store_false",
        help="Run embeddings + FAISS build in CPU mode only.",
    )
    parser.set_defaults(use_gpu=True)
    return parser.parse_args()


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, "a")]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def single_run_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    try:
        try:
            fd = os.open(lock_path.as_posix(), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            stale_pid = None
            try:
                stale_pid = int(lock_path.read_text(encoding="utf-8").strip())
            except Exception:
                stale_pid = None

            if stale_pid is not None and not _pid_alive(stale_pid):
                logging.warning(
                    "removing stale lock file: %s (pid %d not running)",
                    lock_path,
                    stale_pid,
                )
                lock_path.unlink(missing_ok=True)
                fd = os.open(lock_path.as_posix(), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            else:
                owner = f"pid={stale_pid}" if stale_pid is not None else "unknown pid"
                raise RuntimeError(
                    f"Another updater run is active ({owner}); lock exists at {lock_path}"
                )
        os.write(fd, str(os.getpid()).encode("utf-8"))
        yield
    finally:
        if fd is not None:
            os.close(fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    start = time.monotonic()
    display = " ".join(shlex.quote(part) for part in cmd)
    logging.info("run: %s", display)
    subprocess.run(cmd, cwd=cwd, check=True)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logging.info("done: %s (%dms)", cmd[0], elapsed_ms)


def remove_db_with_sidecars(path: Path) -> None:
    for candidate in (
        path,
        path.with_suffix(path.suffix + "-wal"),
        path.with_suffix(path.suffix + "-shm"),
    ):
        if candidate.exists():
            candidate.unlink()


def init_staging_db(staging_db: Path, schema_path: Path) -> None:
    remove_db_with_sidecars(staging_db)
    schema_sql = schema_path.read_text(encoding="utf-8")
    conn = sqlite3.connect(staging_db.as_posix())
    try:
        conn.executescript(schema_sql)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crawl_state (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def shared_columns(
    conn: sqlite3.Connection, left_schema: str, left_table: str, right_schema: str, right_table: str
) -> list[str]:
    main_cols = [row[1] for row in conn.execute(f"PRAGMA {left_schema}.table_info({left_table})")]
    stage_cols = {
        row[1] for row in conn.execute(f"PRAGMA {right_schema}.table_info({right_table})")
    }
    return [col for col in main_cols if col in stage_cols]


def seed_staging_from_prod(prod_db: Path, staging_db: Path) -> None:
    conn = sqlite3.connect(staging_db.as_posix())
    attached = False
    try:
        conn.execute("ATTACH DATABASE ? AS prod", (prod_db.as_posix(),))
        attached = True
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT OR IGNORE INTO instances(host) SELECT host FROM prod.instances")

        channel_cols = shared_columns(conn, "main", "channels", "prod", "channels")
        channel_cols_sql = ", ".join(channel_cols)
        conn.execute(
            f"INSERT OR IGNORE INTO channels({channel_cols_sql}) "
            f"SELECT {channel_cols_sql} FROM prod.channels"
        )

        conn.execute(
            """
            INSERT INTO crawl_state(key, value)
            VALUES ('stage_seeded_at', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(int(time.time() * 1000)),),
        )
        conn.execute(
            """
            INSERT INTO crawl_state(key, value)
            VALUES ('stage_seeded_from', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (prod_db.as_posix(),),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if attached:
            conn.execute("DETACH DATABASE prod")
        conn.close()


def count_staging_deltas(prod_db: Path, staging_db: Path) -> dict[str, int]:
    conn = sqlite3.connect(prod_db.as_posix())
    try:
        conn.execute("ATTACH DATABASE ? AS stage", (staging_db.as_posix(),))
        instances_new = conn.execute(
            """
            SELECT COUNT(*)
            FROM stage.instances s
            LEFT JOIN main.instances p ON p.host = s.host
            WHERE p.host IS NULL
            """
        ).fetchone()[0]
        channels_new = conn.execute(
            """
            SELECT COUNT(*)
            FROM stage.channels s
            LEFT JOIN main.channels p
              ON p.channel_id = s.channel_id
             AND p.instance_domain = s.instance_domain
            WHERE p.channel_id IS NULL
            """
        ).fetchone()[0]
        videos_new = conn.execute(
            """
            SELECT COUNT(*)
            FROM stage.videos s
            LEFT JOIN main.videos p
              ON p.video_id = s.video_id
             AND p.instance_domain = s.instance_domain
            WHERE p.video_id IS NULL
            """
        ).fetchone()[0]
        embeddings_new = conn.execute(
            """
            SELECT COUNT(*)
            FROM stage.video_embeddings s
            LEFT JOIN main.video_embeddings p
              ON p.video_id = s.video_id
             AND p.instance_domain = s.instance_domain
            WHERE p.video_id IS NULL
            """
        ).fetchone()[0]
        return {
            "instances_new": int(instances_new),
            "channels_new": int(channels_new),
            "videos_new": int(videos_new),
            "embeddings_new": int(embeddings_new),
        }
    finally:
        conn.execute("DETACH DATABASE stage")
        conn.close()


def prune_staging_local_non_ok_instances(prod_db: Path, staging_db: Path) -> dict[str, int]:
    """Drop staging instances marked as non-ok by local health_status in prod DB."""
    conn = sqlite3.connect(staging_db.as_posix())
    attached = False
    try:
        conn.execute("ATTACH DATABASE ? AS prod", (prod_db.as_posix(),))
        attached = True

        rows = conn.execute(
            """
            SELECT LOWER(TRIM(p.health_status)) AS status, COUNT(*) AS cnt
            FROM main.instances s
            JOIN prod.instances p ON p.host = s.host
            WHERE p.health_status IS NOT NULL
              AND LOWER(TRIM(p.health_status)) <> 'ok'
            GROUP BY LOWER(TRIM(p.health_status))
            ORDER BY cnt DESC
            """
        ).fetchall()
        non_ok_count = int(sum(int(row[1]) for row in rows))
        conn.execute(
            """
            DELETE FROM main.instances
            WHERE host IN (
                SELECT s.host
                FROM main.instances s
                JOIN prod.instances p ON p.host = s.host
                WHERE p.health_status IS NOT NULL
                  AND LOWER(TRIM(p.health_status)) <> 'ok'
            )
            """
        )
        conn.commit()

        summary = ", ".join(f"{row[0]}={row[1]}" for row in rows) if rows else "none"
        remaining = int(conn.execute("SELECT COUNT(*) FROM main.instances").fetchone()[0])
        logging.info(
            "staging local-health filter removed=%d remaining=%d statuses=%s",
            non_ok_count,
            remaining,
            summary,
        )
        return {
            "removed": non_ok_count,
            "remaining": remaining,
        }
    finally:
        if attached:
            conn.execute("DETACH DATABASE prod")
        conn.close()


def inject_replace_embedding_for_test(prod_db: Path, staging_db: Path) -> bool:
    """Insert one overlapping embedding row into staging with modified payload."""
    conn = sqlite3.connect(staging_db.as_posix())
    attached = False
    try:
        conn.execute("ATTACH DATABASE ? AS prod", (prod_db.as_posix(),))
        attached = True
        row = conn.execute(
            """
            SELECT video_id, instance_domain, embedding, embedding_dim, model_name
            FROM prod.video_embeddings
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            logging.warning("test inject: no prod video_embeddings row available")
            return False

        video_id, instance_domain, embedding, embedding_dim, model_name = row
        payload = bytes(embedding) if embedding is not None else b"\x00"
        if payload:
            first = bytes([payload[0] ^ 0xFF])
            mutated = first + payload[1:]
        else:
            mutated = b"\x01"

        conn.execute(
            """
            INSERT OR REPLACE INTO video_embeddings
              (video_id, instance_domain, embedding, embedding_dim, model_name, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                video_id,
                instance_domain,
                mutated,
                embedding_dim,
                model_name,
            ),
        )
        conn.commit()
        logging.info(
            "test inject: staged replacement embedding for %s@%s",
            video_id,
            instance_domain,
        )
        return True
    finally:
        if attached:
            conn.execute("DETACH DATABASE prod")
        conn.close()


def main() -> None:
    args = parse_args()
    setup_logging(Path(args.logs).resolve())

    repo_root = script_dir.parents[2]
    crawler_dir = Path(args.crawler_dir).resolve()
    crawler_dist = crawler_dir / "dist"
    schema_path = (crawler_dir / "schema.sql").resolve()

    prod_db = Path(args.prod_db).resolve()
    staging_db = Path(args.staging_db).resolve()
    index_path = Path(args.index_path).resolve()
    index_meta_path = Path(args.index_meta_path).resolve()
    similarity_db = Path(args.similarity_db).resolve()
    merge_rules = Path(args.merge_rules).resolve()
    lock_file = Path(args.lock_file).resolve()

    for required in (
        prod_db,
        schema_path,
        merge_rules,
        crawler_dist / "instances-cli.js",
        crawler_dist / "channels-cli.js",
        crawler_dist / "videos-cli.js",
        crawler_dist / "channels-videos-count-cli.js",
        script_dir / "merge-staging-db.py",
        script_dir / "build-video-embeddings.py",
        script_dir / "recompute-popularity.py",
        script_dir / "precompute-similar-ann.py",
        script_dir / "build-ann-index.py",
    ):
        if not required.exists():
            raise FileNotFoundError(f"Required file is missing: {required}")

    logging.info("worker start prod_db=%s staging_db=%s", prod_db, staging_db)
    service_stopped = False
    pipeline_start = time.monotonic()

    with single_run_lock(lock_file):
        if args.resume_staging and staging_db.exists():
            logging.info("staging reused from previous run: %s", staging_db)
        else:
            init_staging_db(staging_db, schema_path)
            logging.info("staging initialized")

            seed_staging_from_prod(prod_db, staging_db)
            logging.info("staging seeded from prod (instances + channels)")

        run_cmd(
            [
                args.node_bin,
                (crawler_dist / "instances-cli.js").as_posix(),
                "--db",
                staging_db.as_posix(),
                "--whitelist-url",
                args.whitelist_url,
                "--resume",
                "--max-instances",
                str(args.max_instances),
                "--concurrency",
                str(args.concurrency),
                "--timeout",
                str(args.timeout_ms),
                "--max-retries",
                str(args.max_retries),
            ],
            cwd=crawler_dir,
        )
        if args.skip_local_dead:
            prune_staging_local_non_ok_instances(prod_db=prod_db, staging_db=staging_db)
        run_cmd(
            [
                args.node_bin,
                (crawler_dist / "channels-cli.js").as_posix(),
                "--db",
                staging_db.as_posix(),
                "--resume",
                "--new-channels",
                "--max-instances",
                str(args.max_instances),
                "--max-channels",
                str(args.max_channels),
                "--concurrency",
                str(args.concurrency),
                "--timeout",
                str(args.timeout_ms),
                "--max-retries",
                str(args.max_retries),
            ],
            cwd=crawler_dir,
        )
        run_cmd(
            [
                args.node_bin,
                (crawler_dist / "videos-cli.js").as_posix(),
                "--db",
                staging_db.as_posix(),
                "--existing-db",
                prod_db.as_posix(),
                "--resume",
                "--new-videos",
                "--sort",
                "-publishedAt",
                "--max-instances",
                str(args.max_instances),
                "--max-channels",
                str(args.max_channels),
                "--max-videos-pages",
                str(args.max_videos_pages),
                "--stop-after-full-pages",
                str(args.videos_stop_after_full_pages),
                "--concurrency",
                str(args.concurrency),
                "--timeout",
                str(args.timeout_ms),
                "--max-retries",
                str(args.max_retries),
            ],
            cwd=crawler_dir,
        )
        run_cmd(
            [
                args.node_bin,
                (crawler_dist / "channels-videos-count-cli.js").as_posix(),
                "--db",
                staging_db.as_posix(),
                "--resume",
                "--concurrency",
                str(args.concurrency),
                "--timeout",
                str(args.timeout_ms),
                "--max-retries",
                str(args.max_retries),
            ],
            cwd=crawler_dir,
        )

        embeddings_cmd = [
            args.python_bin,
            (script_dir / "build-video-embeddings.py").as_posix(),
            "--db-path",
            staging_db.as_posix(),
        ]
        if args.use_gpu:
            embeddings_cmd.append("--gpu")
        run_cmd(embeddings_cmd, cwd=repo_root)
        if args.inject_replace_embedding_for_test:
            inject_replace_embedding_for_test(prod_db=prod_db, staging_db=staging_db)

        deltas = count_staging_deltas(prod_db, staging_db)
        logging.info(
            "staging delta instances=%d channels=%d videos=%d embeddings=%d",
            deltas["instances_new"],
            deltas["channels_new"],
            deltas["videos_new"],
            deltas["embeddings_new"],
        )

        if args.fail_before_merge:
            raise RuntimeError("Injected failure: before merge stage")

        try:
            if not args.skip_systemctl:
                run_cmd(["systemctl", "stop", args.service_name])
                service_stopped = True

            run_cmd(
                [
                    args.python_bin,
                    (script_dir / "merge-staging-db.py").as_posix(),
                    "--prod-db",
                    prod_db.as_posix(),
                    "--staging-db",
                    staging_db.as_posix(),
                    "--rules",
                    merge_rules.as_posix(),
                ],
                cwd=repo_root,
            )
            run_cmd(
                [
                    args.python_bin,
                    (script_dir / "recompute-popularity.py").as_posix(),
                    "--db",
                    prod_db.as_posix(),
                    "--incremental",
                ],
                cwd=repo_root,
            )
            if args.fail_during_ann_build:
                raise RuntimeError("Injected failure: ANN build stage")
            ann_cmd = [
                args.python_bin,
                (script_dir / "build-ann-index.py").as_posix(),
                "--db-path",
                prod_db.as_posix(),
                "--index-path",
                index_path.as_posix(),
                "--meta-path",
                index_meta_path.as_posix(),
                "--normalize",
                "--nlist",
                str(args.nlist),
            ]
            if args.use_gpu:
                ann_cmd.append("--gpu")
            run_cmd(ann_cmd, cwd=repo_root)
            if args.fail_after_merge_before_similarity:
                raise RuntimeError(
                    "Injected failure: after merge/ANN and before similarity precompute"
                )
            run_cmd(
                [
                    args.python_bin,
                    (script_dir / "precompute-similar-ann.py").as_posix(),
                    "--db",
                    prod_db.as_posix(),
                    "--index",
                    index_path.as_posix(),
                    "--out",
                    similarity_db.as_posix(),
                    "--incremental",
                ],
                cwd=repo_root,
            )
        finally:
            if service_stopped and not args.skip_systemctl:
                run_cmd(["systemctl", "start", args.service_name])
                service_stopped = False

    total_ms = int((time.monotonic() - pipeline_start) * 1000)
    logging.info("worker completed in %dms", total_ms)


if __name__ == "__main__":
    main()
