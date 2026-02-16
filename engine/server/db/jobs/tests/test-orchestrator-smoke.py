#!/usr/bin/env python3
"""Smoke-test the staging orchestrator on a lightweight prod DB copy."""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

script_dir = Path(__file__).resolve().parent
jobs_dir = script_dir.parent
repo_root = script_dir.parents[4]
server_dir = script_dir.parents[2]
api_dir = repo_root / "engine" / "server" / "api"
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))

from scripts.cli_format import CompactHelpFormatter
from server_config import DEFAULT_DB_PATH, DEFAULT_INDEX_PATH, DEFAULT_SIMILARITY_DB_PATH


def parse_args() -> argparse.Namespace:
    default_source_db = (repo_root / DEFAULT_DB_PATH).resolve()
    default_workdir = repo_root / "tmp" / "orchestrator-smoke"
    default_instances_json = (script_dir / "test-instances.json").resolve()

    parser = argparse.ArgumentParser(
        description="Run orchestrator smoke-test against a temporary mini prod DB.",
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument("--source-db", default=str(default_source_db), help="Source prod DB.")
    parser.add_argument(
        "--workdir",
        default=str(default_workdir),
        help="Workspace directory where smoke artifacts are created.",
    )
    parser.add_argument(
        "--python-bin", default=sys.executable, help="Python executable for jobs."
    )
    parser.add_argument("--node-bin", default="node", help="Node executable for crawler CLIs.")
    parser.add_argument(
        "--service-name",
        default="peertube-browser",
        help="Systemd service name for orchestrator runs when --use-systemctl is enabled.",
    )
    parser.add_argument(
        "--instances-json",
        default=str(default_instances_json),
        help=(
            "Path to JSON with static test instances list "
            "(default: engine/server/db/jobs/tests/test-instances.json)."
        ),
    )
    parser.add_argument(
        "--max-instances",
        type=int,
        default=3,
        help="Max instances for smoke run (also used to build local whitelist).",
    )
    parser.add_argument(
        "--max-channels",
        type=int,
        default=30,
        help="Max channels for smoke run.",
    )
    parser.add_argument(
        "--max-videos-pages",
        type=int,
        default=1,
        help="Max video pages per channel for smoke run.",
    )
    parser.add_argument(
        "--seed-videos-limit",
        type=int,
        default=2000,
        help="Keep at most N videos in mini prod seed DB (0 = no limit).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Orchestrator crawler concurrency.",
    )
    parser.add_argument("--timeout-ms", type=int, default=5000, help="Crawler timeout in ms.")
    parser.add_argument("--max-retries", type=int, default=2, help="Crawler retries.")
    parser.add_argument(
        "--nlist",
        type=int,
        default=256,
        help="ANN nlist for smoke run (keep <= embedding count in mini DB).",
    )
    parser.add_argument(
        "--videos-stop-after-full-pages",
        type=int,
        default=1,
        help="Stop-after-full-pages value for videos crawl.",
    )
    accel_group = parser.add_mutually_exclusive_group()
    accel_group.add_argument(
        "--gpu",
        dest="use_gpu",
        action="store_true",
        help="Run worker in GPU mode (default).",
    )
    accel_group.add_argument(
        "--cpu",
        dest="use_gpu",
        action="store_false",
        help="Run worker in CPU mode.",
    )
    parser.set_defaults(use_gpu=True)
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Keep smoke workspace after run.",
    )
    parser.add_argument(
        "--skip-failure-checks",
        action="store_true",
        help="Skip failure-injection checks (faster, less coverage).",
    )
    parser.add_argument(
        "--use-systemctl",
        action="store_true",
        help="Run worker with real systemctl stop/start (default uses --skip-systemctl).",
    )
    return parser.parse_args()


def setup_logging(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "smoke.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, "a")],
    )
    return log_path


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not table_exists(conn, table):
        return False
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def db_metrics(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path.as_posix())
    try:
        metrics: dict[str, int] = {
            "instances": count_rows(conn, "instances"),
            "channels": count_rows(conn, "channels"),
            "videos": count_rows(conn, "videos"),
            "video_embeddings": count_rows(conn, "video_embeddings"),
        }
        if column_exists(conn, "videos", "popularity"):
            metrics["videos_popularity_non_null"] = int(
                conn.execute("SELECT COUNT(*) FROM videos WHERE popularity IS NOT NULL").fetchone()[0]
            )
        else:
            metrics["videos_popularity_non_null"] = 0
        return metrics
    finally:
        conn.close()


def create_table_and_indexes_from_source(
    dst_conn: sqlite3.Connection, table: str
) -> None:
    row = dst_conn.execute(
        "SELECT sql FROM src.sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if not row or not row[0]:
        raise RuntimeError(f"Table schema not found in source DB: {table}")
    dst_conn.execute(row[0])

    index_rows = dst_conn.execute(
        """
        SELECT sql
        FROM src.sqlite_master
        WHERE type='index'
          AND tbl_name=?
          AND sql IS NOT NULL
        """,
        (table,),
    ).fetchall()
    for index_row in index_rows:
        dst_conn.execute(index_row[0])


def copy_and_prune_prod(
    source_db: Path,
    mini_prod_db: Path,
    max_instances: int,
    seed_channels_limit: int,
    seed_videos_limit: int,
    preferred_hosts: list[str],
) -> list[str]:
    mini_prod_db.parent.mkdir(parents=True, exist_ok=True)
    if mini_prod_db.exists():
        mini_prod_db.unlink()
    conn = sqlite3.connect(mini_prod_db.as_posix())
    try:
        conn.execute("PRAGMA temp_store=2")
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("ATTACH DATABASE ? AS src", (source_db.as_posix(),))

        existing_hosts = {
            row[0] for row in conn.execute("SELECT host FROM src.instances").fetchall()
        }
        hosts: list[str] = []
        if preferred_hosts:
            capped_hosts = (
                preferred_hosts[:max_instances]
                if max_instances > 0
                else preferred_hosts
            )
            hosts = [host for host in capped_hosts if host in existing_hosts]
        if not hosts:
            instances_limit = max_instances if max_instances > 0 else 10
            hosts = [
                row[0]
                for row in conn.execute(
                    "SELECT host FROM src.instances ORDER BY host ASC LIMIT ?",
                    (instances_limit,),
                ).fetchall()
            ]
        if not hosts:
            raise RuntimeError("No instances found in source DB.")

        for table in ("instances", "channels", "videos", "video_embeddings"):
            create_table_and_indexes_from_source(conn, table)

        placeholders = ", ".join(["?"] * len(hosts))
        conn.execute(
            f"INSERT INTO instances SELECT * FROM src.instances WHERE host IN ({placeholders})",
            hosts,
        )
        if table_exists(conn, "channels") and table_exists(conn, "instances"):
            if seed_channels_limit > 0:
                conn.execute(
                    f"""
                    INSERT INTO channels
                    SELECT *
                    FROM (
                      SELECT *
                      FROM src.channels
                      WHERE instance_domain IN ({placeholders})
                      ORDER BY rowid DESC
                      LIMIT ?
                    )
                    """,
                    [*hosts, seed_channels_limit],
                )
            else:
                conn.execute(
                    f"""
                    INSERT INTO channels
                    SELECT *
                    FROM src.channels
                    WHERE instance_domain IN ({placeholders})
                    """,
                    hosts,
                )
        if table_exists(conn, "videos") and table_exists(conn, "instances"):
            if seed_videos_limit > 0:
                conn.execute(
                    f"""
                    INSERT INTO videos
                    SELECT *
                    FROM (
                      SELECT *
                      FROM src.videos
                      WHERE instance_domain IN ({placeholders})
                      ORDER BY rowid DESC
                      LIMIT ?
                    )
                    """,
                    [*hosts, seed_videos_limit],
                )
            else:
                conn.execute(
                    f"""
                    INSERT INTO videos
                    SELECT *
                    FROM src.videos
                    WHERE instance_domain IN ({placeholders})
                    """,
                    hosts,
                )
        if table_exists(conn, "video_embeddings") and table_exists(conn, "videos"):
            conn.execute(
                """
                INSERT INTO video_embeddings
                SELECT e.*
                FROM src.video_embeddings e
                WHERE EXISTS (
                  SELECT 1
                  FROM videos v
                  WHERE v.video_id = e.video_id
                    AND v.instance_domain = e.instance_domain
                )
                """
            )
        conn.commit()
        conn.execute("DETACH DATABASE src")
        return hosts
    finally:
        conn.close()


def load_hosts_from_json(instances_json: Path, max_instances: int) -> list[str]:
    if not instances_json.exists():
        logging.warning("instances JSON not found, fallback to DB selection: %s", instances_json)
        return []
    payload = json.loads(instances_json.read_text(encoding="utf-8"))
    raw_instances: list[Any] = []
    if isinstance(payload, dict):
        # Support both local test format {"instances":[...]} and JoinPeerTube format {"data":[...]}.
        if isinstance(payload.get("instances"), list):
            raw_instances = payload["instances"]
        elif isinstance(payload.get("data"), list):
            raw_instances = payload["data"]
    elif isinstance(payload, list):
        raw_instances = payload
    hosts: list[str] = []
    seen: set[str] = set()
    if isinstance(raw_instances, list):
        for item in raw_instances:
            host: str | None = None
            if isinstance(item, dict):
                maybe_host = item.get("host")
                if isinstance(maybe_host, str):
                    host = maybe_host
            elif isinstance(item, str):
                host = item
            if not host or not host.strip():
                continue
            normalized = host.strip().lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            hosts.append(normalized)
    if max_instances > 0:
        return hosts[:max_instances]
    return hosts


def find_free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def start_whitelist_server(
    python_bin: str, whitelist_dir: Path, port: int, log_path: Path
) -> tuple[subprocess.Popen[Any], Any]:
    log_file = open(log_path, "a", encoding="utf-8")
    process = subprocess.Popen(
        [python_bin, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=whitelist_dir,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, log_file


def run_orchestrator(
    args: argparse.Namespace,
    paths: dict[str, Path],
    whitelist_url: str,
    extra_flags: list[str] | None = None,
    expect_success: bool = True,
) -> dict[str, int]:
    cmd = [
        args.python_bin,
        (jobs_dir / "updater-worker.py").as_posix(),
        "--prod-db",
        paths["prod_db"].as_posix(),
        "--staging-db",
        paths["staging_db"].as_posix(),
        "--index-path",
        paths["index_path"].as_posix(),
        "--index-meta-path",
        paths["index_meta_path"].as_posix(),
        "--similarity-db",
        paths["similarity_db"].as_posix(),
        "--merge-rules",
        (jobs_dir / "merge_rules.json").as_posix(),
        "--crawler-dir",
        (repo_root / "engine" / "crawler").as_posix(),
        "--logs",
        paths["worker_log"].as_posix(),
        "--lock-file",
        paths["lock_file"].as_posix(),
        "--whitelist-url",
        whitelist_url,
        "--node-bin",
        args.node_bin,
        "--python-bin",
        args.python_bin,
        "--concurrency",
        str(args.concurrency),
        "--timeout-ms",
        str(args.timeout_ms),
        "--max-retries",
        str(args.max_retries),
        "--videos-stop-after-full-pages",
        str(args.videos_stop_after_full_pages),
        "--max-instances",
        str(args.max_instances),
        "--max-channels",
        str(args.max_channels),
        "--max-videos-pages",
        str(args.max_videos_pages),
        "--nlist",
        str(args.nlist),
        "--service-name",
        args.service_name,
    ]
    if not args.use_systemctl:
        cmd.append("--skip-systemctl")
    cmd.append("--gpu" if args.use_gpu else "--cpu")
    if extra_flags:
        cmd.extend(extra_flags)

    logging.info("run worker: %s", " ".join(cmd))
    started = time.monotonic()
    result = subprocess.run(cmd, check=False, cwd=repo_root)
    duration_ms = int((time.monotonic() - started) * 1000)
    if expect_success and result.returncode != 0:
        raise RuntimeError(f"worker failed rc={result.returncode} flags={extra_flags or []}")
    if not expect_success and result.returncode == 0:
        raise RuntimeError(f"worker unexpectedly succeeded flags={extra_flags or []}")
    return {"rc": int(result.returncode), "duration_ms": duration_ms}


def assert_worker_log(worker_log: Path) -> str:
    text = worker_log.read_text(encoding="utf-8")
    required_markers = [
        "instances-cli.js",
        "channels-cli.js",
        "videos-cli.js",
        "channels-videos-count-cli.js",
        "build-video-embeddings.py",
        "merge-staging-db.py",
        "recompute-popularity.py",
        "precompute-similar-ann.py",
        "build-ann-index.py",
        "worker completed",
    ]
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        raise RuntimeError(f"Worker log is missing required markers: {missing}")
    return text


def parse_stage_durations(worker_log_text: str) -> dict[str, int]:
    marker_to_stage = {
        "instances-cli.js": "instances_crawl",
        "channels-cli.js": "channels_crawl",
        "videos-cli.js": "videos_crawl",
        "channels-videos-count-cli.js": "channels_videos_count",
        "build-video-embeddings.py": "embeddings_build",
        "merge-staging-db.py": "merge_db",
        "recompute-popularity.py": "popularity_recompute",
        "build-ann-index.py": "ann_build",
        "precompute-similar-ann.py": "similarity_precompute",
    }
    pending: list[str] = []
    durations: dict[str, int] = {}
    for line in worker_log_text.splitlines():
        if " run: " in line:
            stage = next((v for k, v in marker_to_stage.items() if k in line), None)
            if stage is not None:
                pending.append(stage)
            continue
        if " done: " in line and pending:
            match = re.search(r"\((\d+)ms\)", line)
            if match:
                durations[pending.pop(0)] = int(match.group(1))
    return durations


def assert_test_paths(paths: dict[str, Path], run_dir: Path) -> None:
    prod_path = (repo_root / DEFAULT_DB_PATH).resolve()
    guarded_keys = (
        "prod_db",
        "staging_db",
        "index_path",
        "index_meta_path",
        "similarity_db",
        "worker_log",
        "http_log",
        "lock_file",
        "before_snapshot_db",
    )
    for key in guarded_keys:
        if key not in paths:
            continue
        path = paths[key].resolve()
        if run_dir != path and run_dir not in path.parents:
            raise RuntimeError(f"Unsafe path for {key}: {path} (outside run_dir={run_dir})")
    if paths["prod_db"].resolve() == prod_path:
        raise RuntimeError(f"Unsafe prod DB path points to real prod DB: {prod_path}")


def load_merge_rules(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise RuntimeError(f"Invalid merge_rules format: {path}")
    normalized: list[dict[str, Any]] = []
    for item in tables:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        strategy = item.get("strategy")
        keys = item.get("keys")
        if not isinstance(name, str) or not isinstance(strategy, str) or not isinstance(keys, list):
            continue
        normalized.append({"name": name, "strategy": strategy, "keys": keys})
    return normalized


def table_columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA {schema}.table_info({table})").fetchall()]


def count_new_rows_by_keys(base_db: Path, stage_db: Path, table: str, keys: list[str]) -> int:
    if not keys:
        return 0
    conn = sqlite3.connect(base_db.as_posix())
    try:
        conn.execute("ATTACH DATABASE ? AS stage", (stage_db.as_posix(),))
        stage_cols = set(table_columns(conn, "stage", table))
        base_cols = set(table_columns(conn, "main", table))
        if not stage_cols or not base_cols:
            return 0
        if any(k not in stage_cols or k not in base_cols for k in keys):
            return 0
        join_sql = " AND ".join([f"s.{k} = b.{k}" for k in keys])
        missing_probe = f"b.{keys[0]} IS NULL"
        query = (
            f"SELECT COUNT(*) FROM stage.{table} s "
            f"LEFT JOIN main.{table} b ON {join_sql} WHERE {missing_probe}"
        )
        return int(conn.execute(query).fetchone()[0])
    finally:
        conn.execute("DETACH DATABASE stage")
        conn.close()


def count_duplicate_groups(db_path: Path, table: str, keys: list[str]) -> int:
    if not keys:
        return 0
    conn = sqlite3.connect(db_path.as_posix())
    try:
        cols = set(table_columns(conn, "main", table))
        if not cols or any(k not in cols for k in keys):
            return 0
        keys_sql = ", ".join(keys)
        query = (
            f"SELECT COUNT(*) FROM ("
            f"SELECT {keys_sql}, COUNT(*) c FROM {table} "
            f"GROUP BY {keys_sql} HAVING c > 1)"
        )
        return int(conn.execute(query).fetchone()[0])
    finally:
        conn.close()


def count_insert_only_changed_rows(
    before_db: Path,
    after_db: Path,
    table: str,
    keys: list[str],
    ignore_columns: set[str] | None = None,
) -> int:
    if not keys:
        return 0
    conn = sqlite3.connect(after_db.as_posix())
    try:
        conn.execute("ATTACH DATABASE ? AS before", (before_db.as_posix(),))
        after_cols = set(table_columns(conn, "main", table))
        before_cols = set(table_columns(conn, "before", table))
        if not after_cols or not before_cols:
            return 0
        if any(k not in after_cols or k not in before_cols for k in keys):
            return 0
        ignore = ignore_columns or set()
        non_key_cols = [
            col
            for col in table_columns(conn, "main", table)
            if col not in set(keys) and col not in ignore
        ]
        if not non_key_cols:
            return 0
        join_sql = " AND ".join([f"a.{k} = b.{k}" for k in keys])
        diff_sql = " OR ".join([f"NOT (a.{c} IS b.{c})" for c in non_key_cols])
        query = (
            f"SELECT COUNT(*) FROM main.{table} a "
            f"JOIN before.{table} b ON {join_sql} WHERE {diff_sql}"
        )
        return int(conn.execute(query).fetchone()[0])
    finally:
        conn.execute("DETACH DATABASE before")
        conn.close()


def count_stage_overlap_by_keys(
    before_db: Path, stage_db: Path, table: str, keys: list[str]
) -> int:
    if not keys:
        return 0
    conn = sqlite3.connect(before_db.as_posix())
    try:
        conn.execute("ATTACH DATABASE ? AS stage", (stage_db.as_posix(),))
        before_cols = set(table_columns(conn, "main", table))
        stage_cols = set(table_columns(conn, "stage", table))
        if not before_cols or not stage_cols:
            return 0
        if any(k not in before_cols or k not in stage_cols for k in keys):
            return 0
        join_sql = " AND ".join([f"s.{k} = b.{k}" for k in keys])
        query = f"SELECT COUNT(*) FROM stage.{table} s JOIN main.{table} b ON {join_sql}"
        return int(conn.execute(query).fetchone()[0])
    finally:
        conn.execute("DETACH DATABASE stage")
        conn.close()


def count_stage_after_mismatch_rows(
    stage_db: Path, after_db: Path, table: str, keys: list[str]
) -> int:
    if not keys:
        return 0
    conn = sqlite3.connect(after_db.as_posix())
    try:
        conn.execute("ATTACH DATABASE ? AS stage", (stage_db.as_posix(),))
        after_cols = set(table_columns(conn, "main", table))
        stage_cols = set(table_columns(conn, "stage", table))
        if not after_cols or not stage_cols:
            return 0
        if any(k not in after_cols or k not in stage_cols for k in keys):
            return 0
        non_key_cols = [
            col for col in table_columns(conn, "main", table) if col not in set(keys)
        ]
        if not non_key_cols:
            return 0
        join_sql = " AND ".join([f"a.{k} = s.{k}" for k in keys])
        diff_sql = " OR ".join([f"NOT (a.{c} IS s.{c})" for c in non_key_cols])
        query = (
            f"SELECT COUNT(*) FROM main.{table} a "
            f"JOIN stage.{table} s ON {join_sql} WHERE {diff_sql}"
        )
        return int(conn.execute(query).fetchone()[0])
    finally:
        conn.execute("DETACH DATABASE stage")
        conn.close()


def assert_lock_released(lock_file: Path) -> None:
    if lock_file.exists():
        raise RuntimeError(f"Worker lock file was not released: {lock_file}")


def assert_db_integrity(db_path: Path) -> None:
    conn = sqlite3.connect(db_path.as_posix())
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if not row or row[0] != "ok":
            raise RuntimeError(f"SQLite integrity_check failed for {db_path}: {row}")
    finally:
        conn.close()


def validate_outputs(
    paths: dict[str, Path],
    before: dict[str, int],
    after: dict[str, int],
    before_snapshot: Path,
    expect_replace_overlap: bool,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    if not paths["staging_db"].exists():
        raise RuntimeError("staging DB is missing after worker run.")
    if not paths["index_path"].exists():
        raise RuntimeError("ANN index file was not created.")
    if not paths["index_meta_path"].exists():
        raise RuntimeError("ANN index metadata file was not created.")
    if not paths["similarity_db"].exists():
        raise RuntimeError("Similarity DB file was not created.")

    meta = json.loads(paths["index_meta_path"].read_text(encoding="utf-8"))
    meta_total = int(meta.get("total", -1))
    if meta_total != after["video_embeddings"]:
        raise RuntimeError(
            "ANN meta total does not match video_embeddings count: "
            f"meta.total={meta_total} db={after['video_embeddings']}"
        )
    checks["ann_meta_total"] = meta_total

    metric_key = {
        "instances": "instances",
        "channels": "channels",
        "videos": "videos",
        "video_embeddings": "video_embeddings",
    }
    merge_rules = load_merge_rules(jobs_dir / "merge_rules.json")
    for rule in merge_rules:
        table = str(rule["name"])
        strategy = str(rule["strategy"])
        keys = [str(key) for key in list(rule["keys"])]

        duplicates = count_duplicate_groups(paths["prod_db"], table, keys)
        checks[f"duplicates.{table}"] = duplicates
        if duplicates != 0:
            raise RuntimeError(f"Duplicate keys found in {table}: groups={duplicates}")

        if table in metric_key:
            expected_new = count_new_rows_by_keys(
                base_db=before_snapshot,
                stage_db=paths["staging_db"],
                table=table,
                keys=keys,
            )
            actual_delta = after[metric_key[table]] - before[metric_key[table]]
            checks[f"delta.{table}"] = {"expected": expected_new, "actual": actual_delta}
            if expected_new != actual_delta:
                raise RuntimeError(
                    f"Delta mismatch for {table}: expected={expected_new} actual={actual_delta}"
                )

        if strategy == "INSERT_ONLY":
            ignore_columns: set[str] = set()
            # Popularity is recalculated after merge by a separate job and may
            # legitimately change existing video rows.
            if table == "videos":
                ignore_columns.add("popularity")
            changed = count_insert_only_changed_rows(
                before_db=before_snapshot,
                after_db=paths["prod_db"],
                table=table,
                keys=keys,
                ignore_columns=ignore_columns,
            )
            checks[f"insert_only_changed.{table}"] = changed
            if changed != 0:
                raise RuntimeError(
                    f"INSERT_ONLY violation in {table}: changed existing rows={changed}"
                )

        if strategy == "INSERT_OR_REPLACE":
            overlap = count_stage_overlap_by_keys(
                before_db=before_snapshot,
                stage_db=paths["staging_db"],
                table=table,
                keys=keys,
            )
            mismatch = count_stage_after_mismatch_rows(
                stage_db=paths["staging_db"],
                after_db=paths["prod_db"],
                table=table,
                keys=keys,
            )
            checks[f"replace_overlap.{table}"] = overlap
            checks[f"replace_mismatch.{table}"] = mismatch
            if mismatch != 0:
                raise RuntimeError(
                    f"INSERT_OR_REPLACE mismatch in {table}: rows not matching stage={mismatch}"
                )
            if expect_replace_overlap and table == "video_embeddings" and overlap <= 0:
                raise RuntimeError(
                    "Expected at least one overlapping key in video_embeddings for replace check."
                )

    return checks


def copy_db(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def run_failure_scenarios(
    args: argparse.Namespace,
    run_dir: Path,
    before_snapshot: Path,
    whitelist_url: str,
) -> dict[str, Any]:
    scenarios = [
        ("before_merge", "--fail-before-merge", True),
        ("during_ann_build", "--fail-during-ann-build", False),
        ("after_merge_before_similarity", "--fail-after-merge-before-similarity", False),
    ]
    results: dict[str, Any] = {}

    for name, fail_flag, expect_unchanged in scenarios:
        scenario_dir = run_dir / f"failure-{name}"
        paths = {
            "prod_db": scenario_dir / "prod-mini.db",
            "staging_db": scenario_dir / "staging.db",
            "index_path": scenario_dir / Path(DEFAULT_INDEX_PATH).name,
            "index_meta_path": scenario_dir / (Path(DEFAULT_INDEX_PATH).name + ".json"),
            "similarity_db": scenario_dir / Path(DEFAULT_SIMILARITY_DB_PATH).name,
            "worker_log": scenario_dir / "worker.log",
            "http_log": scenario_dir / "whitelist-http.log",
            "lock_file": scenario_dir / "worker.lock",
        }
        scenario_dir.mkdir(parents=True, exist_ok=True)
        copy_db(before_snapshot, paths["prod_db"])
        before_metrics = db_metrics(paths["prod_db"])

        run_info = run_orchestrator(
            args=args,
            paths=paths,
            whitelist_url=whitelist_url,
            extra_flags=[fail_flag],
            expect_success=False,
        )
        assert_lock_released(paths["lock_file"])
        assert_db_integrity(paths["prod_db"])
        after_metrics = db_metrics(paths["prod_db"])
        unchanged = after_metrics == before_metrics
        if expect_unchanged and not unchanged:
            raise RuntimeError(
                f"Failure scenario {name} changed DB unexpectedly: "
                f"before={before_metrics} after={after_metrics}"
            )
        results[name] = {
            "rc": run_info["rc"],
            "duration_ms": run_info["duration_ms"],
            "db_unchanged": unchanged,
            "lock_released": True,
        }
    return results


def main() -> None:
    args = parse_args()
    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.workdir).resolve() / run_id
    setup_logging(run_dir)
    latest_report_path = Path(args.workdir).resolve() / "last-report.json"

    source_db = Path(args.source_db).resolve()
    instances_json = Path(args.instances_json).resolve()
    if not source_db.exists():
        raise FileNotFoundError(f"Source DB not found: {source_db}")

    paths = {
        "run_dir": run_dir,
        "prod_db": run_dir / "prod-mini.db",
        "staging_db": run_dir / "staging.db",
        "index_path": run_dir / Path(DEFAULT_INDEX_PATH).name,
        "index_meta_path": run_dir / (Path(DEFAULT_INDEX_PATH).name + ".json"),
        "similarity_db": run_dir / Path(DEFAULT_SIMILARITY_DB_PATH).name,
        "worker_log": run_dir / "worker.log",
        "http_log": run_dir / "whitelist-http.log",
        "lock_file": run_dir / "worker.lock",
        "before_snapshot_db": run_dir / "prod-before.db",
        "report_path": run_dir / "report.json",
    }
    assert_test_paths(paths, run_dir)

    report: dict[str, Any] = {
        "run_id": run_id,
        "status": "running",
        "artifacts": {k: v.as_posix() for k, v in paths.items()},
        "timings_ms": {},
        "checks": {},
        "failure_scenarios": {},
    }

    logging.info("workspace: %s", run_dir)
    try:
        preferred_hosts = load_hosts_from_json(instances_json, args.max_instances)
        if preferred_hosts:
            logging.info(
                "using instances JSON: %s hosts=%d",
                instances_json,
                len(preferred_hosts),
            )
        else:
            logging.info("instances JSON empty/unavailable; fallback to DB host sampling")

        hosts = copy_and_prune_prod(
            source_db=source_db,
            mini_prod_db=paths["prod_db"],
            max_instances=args.max_instances,
            seed_channels_limit=args.max_channels,
            seed_videos_limit=args.seed_videos_limit,
            preferred_hosts=preferred_hosts,
        )
        logging.info("mini prod prepared hosts=%d", len(hosts))
        report["host_count"] = len(hosts)

        before = db_metrics(paths["prod_db"])
        copy_db(paths["prod_db"], paths["before_snapshot_db"])
        logging.info("before metrics: %s", before)

        whitelist_dir = run_dir / "whitelist"
        whitelist_dir.mkdir(parents=True, exist_ok=True)
        whitelist_path = whitelist_dir / "whitelist.json"
        whitelist_payload = {
            "total": len(hosts),
            "data": [{"host": host} for host in hosts],
        }
        whitelist_path.write_text(
            json.dumps(whitelist_payload, indent=2) + "\n",
            encoding="utf-8",
        )

        port = find_free_port()
        server, http_log_file = start_whitelist_server(
            python_bin=args.python_bin,
            whitelist_dir=whitelist_dir,
            port=port,
            log_path=paths["http_log"],
        )

        try:
            whitelist_url = f"http://127.0.0.1:{port}/whitelist.json"
            success_run = run_orchestrator(
                args=args,
                paths=paths,
                whitelist_url=whitelist_url,
                extra_flags=["--inject-replace-embedding-for-test"],
                expect_success=True,
            )
            report["timings_ms"]["worker_total"] = success_run["duration_ms"]
            if args.skip_failure_checks:
                report["failure_scenarios"] = {"skipped": True}
            else:
                report["failure_scenarios"] = run_failure_scenarios(
                    args=args,
                    run_dir=run_dir,
                    before_snapshot=paths["before_snapshot_db"],
                    whitelist_url=whitelist_url,
                )
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
            http_log_file.close()

        worker_log_text = assert_worker_log(paths["worker_log"])
        report["timings_ms"]["stages"] = parse_stage_durations(worker_log_text)
        after = db_metrics(paths["prod_db"])
        staging = db_metrics(paths["staging_db"])
        checks = validate_outputs(
            paths=paths,
            before=before,
            after=after,
            before_snapshot=paths["before_snapshot_db"],
            expect_replace_overlap=True,
        )
        assert_lock_released(paths["lock_file"])
        assert_db_integrity(paths["prod_db"])
        checks["main.lock_released"] = True
        checks["main.integrity_check"] = "ok"

        report["checks"] = checks
        report["metrics"] = {"before": before, "after": after, "staging": staging}
        report["status"] = "pass"
        logging.info("after metrics: %s", after)
        logging.info("staging metrics: %s", staging)
        logging.info("smoke PASS run_dir=%s", run_dir)
    except Exception as exc:
        report["status"] = "fail"
        report["error"] = str(exc)
        logging.exception("smoke FAIL")
        raise
    finally:
        paths["report_path"].write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        latest_report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if report.get("status") == "pass" and not args.keep_workdir:
            shutil.rmtree(run_dir, ignore_errors=True)
            logging.info("workspace removed (use --keep-workdir to keep artifacts)")


if __name__ == "__main__":
    main()
