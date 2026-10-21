#!/usr/bin/env python3
"""Merge staging SQLite content into production DB using rule-driven strategies."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from scripts.cli_format import CompactHelpFormatter
from data.prepared_discovery import invalidate_prepared_discovery
try:
    from engine.server.db.jobs.updater.staging import assert_video_availability_staging_semantics_conn
    from engine.server.db.jobs.updater.availability_publish import apply_existing_video_availability_conn
except ModuleNotFoundError:  # Direct script execution has only server/jobs roots.
    sys.path.insert(0, str(script_dir))
    from updater.staging import assert_video_availability_staging_semantics_conn
    from updater.availability_publish import apply_existing_video_availability_conn


def parse_args() -> argparse.Namespace:
    """Handle parse args."""
    repo_root = script_dir.parents[3]
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
    parser.add_argument(
        "--parent-health-hosts-file",
        help="Frozen normalized host scope for this invocation; absent or empty publishes no parent health.",
    )
    parser.add_argument(
        "--availability-sweep-report-json",
        help="Completed same-run availability summary; apply with staging merge in one transaction.",
    )
    return parser.parse_args()


def table_exists(conn: sqlite3.Connection, table: str, schema: str) -> bool:
    """Handle table exists."""
    row = conn.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table: str, schema: str) -> list[str]:
    """Handle table columns."""
    return [
        row[1]
        for row in conn.execute(f"PRAGMA {schema}.table_info({table})").fetchall()
    ]


def count_rows(conn: sqlite3.Connection, schema: str, table: str) -> int:
    """Handle count rows."""
    return int(conn.execute(f"SELECT COUNT(*) FROM {schema}.{table}").fetchone()[0])


def load_rules(path: Path) -> list[dict[str, Any]]:
    """Handle load rules."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    tables = payload.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ValueError("merge rules must contain non-empty 'tables' list")
    return tables


def validate_merge_schema(
    conn: sqlite3.Connection,
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate every merge rule before any production DML can execute."""
    prepared: list[dict[str, Any]] = []
    for rule in rules:
        table = str(rule.get("name", "")).strip()
        strategy = str(rule.get("strategy", "")).strip().upper()
        keys = [str(key) for key in rule.get("keys", [])]
        if not table:
            raise ValueError("merge rule table name is empty")
        if not keys:
            raise ValueError(f"merge rule for '{table}' has no keys")
        if strategy not in {"INSERT_ONLY", "INSERT_OR_REPLACE", "UPSERT"}:
            raise ValueError(f"unsupported strategy '{strategy}' for table '{table}'")
        if not table_exists(conn, table, "main"):
            raise ValueError(f"table missing in prod DB: {table}")
        if not table_exists(conn, table, "stage"):
            raise ValueError(f"table missing in staging DB: {table}")

        prod_columns = table_columns(conn, table, "main")
        stage_columns_list = table_columns(conn, table, "stage")
        stage_columns = set(stage_columns_list)
        if any(key not in prod_columns for key in keys):
            raise ValueError(f"keys {keys} are not present in prod table '{table}'")
        if any(key not in stage_columns for key in keys):
            raise ValueError(f"keys {keys} are not present in staging table '{table}'")

        stage_only = sorted(stage_columns - set(prod_columns))
        if stage_only:
            raise RuntimeError(
                f"staging table '{table}' has columns missing from production: "
                f"{', '.join(stage_only)}. Run migrate-whitelist.py before merge."
            )
        merge_columns = [column for column in prod_columns if column in stage_columns]
        if not merge_columns or any(key not in merge_columns for key in keys):
            raise ValueError(f"keys {keys} are missing from merge columns for table '{table}'")
        prepared.append(
            {
                "rule": rule,
                "table": table,
                "strategy": strategy,
                "keys": keys,
                "merge_columns": merge_columns,
            }
        )
    return prepared


def build_upsert_sql(
    table: str,
    columns: list[str],
    keys: list[str],
    update_columns: list[str],
) -> str:
    """Handle build upsert sql."""
    update_expr = ", ".join([f"{col} = excluded.{col}" for col in update_columns])
    cols = ", ".join(columns)
    key_expr = ", ".join(keys)
    return (
        f"INSERT INTO main.{table} ({cols}) "
        f"SELECT {cols} FROM stage.{table} "
        f"ON CONFLICT({key_expr}) DO UPDATE SET {update_expr}"
    )


_PARENT_HEALTH_COLUMNS = ("health_status", "health_checked_at", "health_error")
_PARENT_HEALTH_HOST_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")


def read_parent_health_scope(path: str | None) -> str:
    """Freeze explicit crawler-normalized host identities into one JSON1 argument.

    Absent and explicitly empty scopes both mean zero publication, never all
    staging rows. A malformed file is not silently widened or normalized.
    """
    if path is None:
        return "[]"
    hosts: set[str] = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        host = line.strip()
        if not host or host.startswith("#"):
            continue
        if (
            not _PARENT_HEALTH_HOST_PATTERN.fullmatch(host)
            or ".." in host
            or ".-" in host
            or "-." in host
        ):
            raise ValueError(f"Invalid normalized parent-health host: {host!r}")
        hosts.add(host)
    return json.dumps(sorted(hosts), separators=(",", ":"))


def validate_parent_health(conn: sqlite3.Connection, scope_json: str, tables: set[str]) -> None:
    """Reject invalid selected staging observations before the first production DML."""
    if scope_json == "[]":
        # There is no selected run observation to validate.
        return
    for table, host_column in (("instances", "host"), ("channels", "instance_domain")):
        if table not in tables:
            continue
        # Seeding copied production health into other staging hosts; those rows
        # are not run observations and must not participate in validation.
        rows = conn.execute(
            f"SELECT health_status,health_checked_at,health_error "
            f"FROM stage.{table} WHERE {host_column} IN (SELECT value FROM json_each(?))",
            (scope_json,),
        )
        for status, checked_at, error in rows:
            if status is None and checked_at is None and error is None:
                continue
            if (
                status not in {"ok", "error"}
                or type(checked_at) is not int
                or checked_at <= 0
                or (status == "ok" and error is not None)
                or (status == "error" and (
                    not isinstance(error, str)
                    or not error.strip()
                    or len(error) > 4096
                ))
            ):
                raise ValueError(f"Invalid selected {table} health observation")


def publish_parent_health(conn: sqlite3.Connection, scope_json: str, tables: set[str]) -> None:
    """Publish scoped verified observations without modifying parent metadata.

    Both parent metadata INSERTs must already have run. This single health
    publication path covers new and preexisting production rows and shares the
    enclosing transaction with Prepared Discovery invalidation.
    """
    if scope_json == "[]":
        return
    changed_visibility = False
    for table, host_column, pk_predicate in (
        ("instances", "host", "p.host = s.host"),
        ("channels", "instance_domain", "p.channel_id = s.channel_id AND p.instance_domain = s.instance_domain"),
    ):
        if table not in tables:
            continue
        changed_visibility = changed_visibility or conn.execute(
            f"SELECT 1 FROM main.{table} AS p "
            f"JOIN stage.{table} AS s ON {pk_predicate} "
            f"WHERE s.{host_column} IN (SELECT value FROM json_each(?)) "
            f"AND s.health_status IS NOT NULL "
            f"AND COALESCE(p.health_status = 'error', 0) != (s.health_status = 'error') "
            f"LIMIT 1",
            (scope_json,),
        ).fetchone() is not None
    # Compare *before* either UPDATE; a newly inserted parent starts at NULL.
    if changed_visibility:
        invalidate_prepared_discovery(conn)
    for table, host_column, pk_predicate in (
        ("instances", "host", "p.host = s.host"),
        ("channels", "instance_domain", "p.channel_id = s.channel_id AND p.instance_domain = s.instance_domain"),
    ):
        if table not in tables:
            continue
        conn.execute(
            f"UPDATE main.{table} AS p SET "
            f"health_status = s.health_status, "
            f"health_checked_at = s.health_checked_at, "
            f"health_error = s.health_error "
            f"FROM stage.{table} AS s "
            f"WHERE {pk_predicate} AND s.health_status IS NOT NULL "
            f"AND s.{host_column} IN (SELECT value FROM json_each(?))",
            (scope_json,),
        )


def health_neutral_parent_select(table: str, merge_columns: list[str]) -> str:
    """Import parent metadata but never a seeded health trio into new rows."""
    expressions = [
        "NULL" if column in _PARENT_HEALTH_COLUMNS else column
        for column in merge_columns
    ]
    return (
        f"INSERT OR IGNORE INTO main.{table} ({', '.join(merge_columns)}) "
        f"SELECT {', '.join(expressions)} FROM stage.{table}"
    )


def main() -> None:
    """Handle main."""
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
    scope_json = read_parent_health_scope(getattr(args, "parent_health_hosts_file", None))
    # This is a small immutable report, never a path that could be swapped
    # after the updater has selected and checked the completed work set.
    report_json = getattr(args, "availability_sweep_report_json", None)
    sweep_report = json.loads(report_json) if report_json is not None else None
    if report_json is not None and not isinstance(sweep_report, dict):
        raise ValueError("Availability report must be a JSON object")
    conn = sqlite3.connect(prod_db.as_posix())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("ATTACH DATABASE ? AS stage", (staging_db.as_posix(),))

    try:
        # Validate the complete schema boundary before acquiring the write
        # transaction. A later rule must never discover incompatible staging
        # columns after earlier tables have already been merged.
        prepared_rules = validate_merge_schema(conn, rules)
        parent_tables = {r["table"] for r in prepared_rules} & {"instances", "channels"}
        last_parent = next(
            (r["table"] for r in reversed(prepared_rules) if r["table"] in parent_tables),
            None,
        )
        # UPDATE FROM and JSON1 are part of the required merger runtime.
        # Fail before any production DML rather than hiding missing capabilities.
        if sqlite3.sqlite_version_info < (3, 33, 0):
            raise RuntimeError("SQLite >= 3.33 is required for parent-health UPDATE FROM")
        # The direct merger checks JSON1 on its own connection, not merely via
        # the updater caller; no production DML is allowed without the capability.
        if [tuple(row) for row in conn.execute("SELECT value FROM json_each(?)", ('["probe"]',))] != [
            ("probe",)
        ]:
            raise RuntimeError("SQLite json_each/JSON1 is required for parent publication")
        conn.execute("BEGIN IMMEDIATE")
        assert_video_availability_staging_semantics_conn(conn, "stage")
        validate_parent_health(conn, scope_json, parent_tables)
        for prepared in prepared_rules:
            rule = prepared["rule"]
            table = prepared["table"]
            strategy = prepared["strategy"]
            keys = prepared["keys"]
            merge_columns = prepared["merge_columns"]
            before = count_rows(conn, "main", table)
            cols = ", ".join(merge_columns)
            if strategy == "INSERT_ONLY":
                sql = (
                    health_neutral_parent_select(table, merge_columns)
                    if table in {"instances", "channels"}
                    else f"INSERT OR IGNORE INTO main.{table} ({cols}) "
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
            if table == last_parent:
                # Publish only after the final parent metadata INSERT, including
                # when a constrained merge-rule fixture contains one parent.
                publish_parent_health(conn, scope_json, parent_tables)
            if table == "videos" and affected > 0:
                # Keep invalidation in the merge transaction: failed merges
                # restore both canonical videos and the previous readiness marker.
                invalidate_prepared_discovery(conn)
            after = count_rows(conn, "main", table)
            logging.info(
                "merged table=%s strategy=%s rows_before=%d rows_after=%d affected=%d",
                table,
                strategy,
                before,
                after,
                affected,
            )

        # Apply completed existing-video evidence after all INSERT_ONLY tables;
        # a late identity or report failure rolls back merge and parent health.
        summary = (
            apply_existing_video_availability_conn(
                conn, sweep_report=sweep_report, evidence_schema="stage"
            ) if sweep_report is not None else None
        )
        conn.commit()
        if summary is not None:
            logging.info("video_availability_publication %s", json.dumps(
                summary.__dict__, sort_keys=True))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("DETACH DATABASE stage")
        conn.close()

    logging.info("merge completed")


if __name__ == "__main__":
    main()
