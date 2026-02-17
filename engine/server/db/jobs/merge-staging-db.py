#!/usr/bin/env python3
"""Merge staging SQLite content into production DB using rule-driven strategies."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[2]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from scripts.cli_format import CompactHelpFormatter


def parse_args() -> argparse.Namespace:
    repo_root = script_dir.parents[4]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH

    parser = argparse.ArgumentParser(
        description="Merge staging DB into production DB with merge_rules.json.",
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument(
        "--prod-db",
        default=str((repo_root / DEFAULT_DB_PATH).resolve()),
        help="Path to production database.",
    )
    parser.add_argument(
        "--staging-db",
        required=True,
        help="Path to staging database.",
    )
    parser.add_argument(
        "--rules",
        default=str((script_dir / "merge_rules.json").resolve()),
        help="Path to merge rules JSON.",
    )
    return parser.parse_args()


def table_exists(conn: sqlite3.Connection, table: str, schema: str) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table: str, schema: str) -> list[str]:
    return [
        row[1]
        for row in conn.execute(f"PRAGMA {schema}.table_info({table})").fetchall()
    ]


def count_rows(conn: sqlite3.Connection, schema: str, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {schema}.{table}").fetchone()[0])


def load_rules(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tables = payload.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ValueError("merge rules must contain non-empty 'tables' list")
    return tables


def build_upsert_sql(
    table: str,
    columns: list[str],
    keys: list[str],
    update_columns: list[str],
) -> str:
    update_expr = ", ".join([f"{col} = excluded.{col}" for col in update_columns])
    cols = ", ".join(columns)
    key_expr = ", ".join(keys)
    return (
        f"INSERT INTO main.{table} ({cols}) "
        f"SELECT {cols} FROM stage.{table} "
        f"ON CONFLICT({key_expr}) DO UPDATE SET {update_expr}"
    )


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    prod_db = Path(args.prod_db).resolve()
    staging_db = Path(args.staging_db).resolve()
    rules_path = Path(args.rules).resolve()

    if not prod_db.exists():
        raise FileNotFoundError(f"Production DB not found: {prod_db}")
    if not staging_db.exists():
        raise FileNotFoundError(f"Staging DB not found: {staging_db}")
    if not rules_path.exists():
        raise FileNotFoundError(f"Rules file not found: {rules_path}")

    rules = load_rules(rules_path)
    conn = sqlite3.connect(prod_db.as_posix())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("ATTACH DATABASE ? AS stage", (staging_db.as_posix(),))

    try:
        conn.execute("BEGIN IMMEDIATE")
        for rule in rules:
            table = str(rule.get("name", "")).strip()
            strategy = str(rule.get("strategy", "")).strip().upper()
            keys = [str(key) for key in rule.get("keys", [])]
            if not table:
                raise ValueError("merge rule table name is empty")
            if not keys:
                raise ValueError(f"merge rule for '{table}' has no keys")
            if strategy not in {"INSERT_ONLY", "INSERT_OR_REPLACE", "UPSERT"}:
                raise ValueError(
                    f"unsupported strategy '{strategy}' for table '{table}'"
                )
            if not table_exists(conn, table, "main"):
                raise ValueError(f"table missing in prod DB: {table}")
            if not table_exists(conn, table, "stage"):
                raise ValueError(f"table missing in staging DB: {table}")

            prod_columns = table_columns(conn, table, "main")
            stage_columns = set(table_columns(conn, table, "stage"))
            if any(key not in prod_columns for key in keys):
                raise ValueError(
                    f"keys {keys} are not present in prod table '{table}'"
                )
            if any(key not in stage_columns for key in keys):
                raise ValueError(
                    f"keys {keys} are not present in staging table '{table}'"
                )
            merge_columns = [column for column in prod_columns if column in stage_columns]
            if not merge_columns:
                raise ValueError(f"no common columns to merge for table '{table}'")
            if any(key not in merge_columns for key in keys):
                raise ValueError(
                    f"keys {keys} are missing from common columns for table '{table}'"
                )

            before = count_rows(conn, "main", table)
            cols = ", ".join(merge_columns)
            if strategy == "INSERT_ONLY":
                sql = (
                    f"INSERT OR IGNORE INTO main.{table} ({cols}) "
                    f"SELECT {cols} FROM stage.{table}"
                )
            elif strategy == "INSERT_OR_REPLACE":
                sql = (
                    f"INSERT OR REPLACE INTO main.{table} ({cols}) "
                    f"SELECT {cols} FROM stage.{table}"
                )
            else:
                requested_update = rule.get("update_columns") or []
                if requested_update:
                    update_columns = [
                        col
                        for col in requested_update
                        if col in merge_columns and col not in keys
                    ]
                else:
                    update_columns = [col for col in merge_columns if col not in keys]
                if not update_columns:
                    sql = (
                        f"INSERT OR IGNORE INTO main.{table} ({cols}) "
                        f"SELECT {cols} FROM stage.{table}"
                    )
                else:
                    sql = build_upsert_sql(table, merge_columns, keys, update_columns)

            conn.execute(sql)
            affected = int(conn.execute("SELECT changes()").fetchone()[0])
            after = count_rows(conn, "main", table)
            logging.info(
                "merged table=%s strategy=%s rows_before=%d rows_after=%d affected=%d",
                table,
                strategy,
                before,
                after,
                affected,
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("DETACH DATABASE stage")
        conn.close()

    logging.info("merge completed")


if __name__ == "__main__":
    main()
