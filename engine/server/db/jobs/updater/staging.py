"""Staging database helpers for the updater pipeline.

These helpers preserve the current SQLite table assumptions while moving DB
operations out of the executable updater wrapper.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse


AVAILABILITY_SEMANTICS_KEY = "video_availability_semantics"
AVAILABILITY_SEMANTICS_VALUE = "canonical_absence_v1"


def remove_db_with_sidecars(db_path: Path) -> None:
    """Remove an SQLite DB and WAL/SHM sidecars using current file names."""

    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db_path) + suffix)
        if path.exists():
            path.unlink()


def init_staging_db(staging_db: Path, schema_path: Path) -> None:
    """Recreate DB/sidecars and stamp fresh staging with current availability semantics before returning.

    Successful initialization commits the marker; both success and failure close
    the connection. No legacy staging is upgraded in place.
    """

    remove_db_with_sidecars(staging_db)
    staging_db.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = schema_path.read_text(encoding="utf-8")
    with closing(sqlite3.connect(staging_db)) as conn, conn:
        conn.executescript(schema_sql)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS crawl_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO crawl_state(key, value) VALUES (?, ?)",
            (AVAILABILITY_SEMANTICS_KEY, AVAILABILITY_SEMANTICS_VALUE),
        )
        conn.commit()


def assert_video_availability_staging_semantics_conn(conn: sqlite3.Connection, schema: str) -> None:
    """Authorize only exact current availability-semantics evidence from the DB generation being consumed.

    Merge passes its already attached stage within its transaction; pathname
    validation is a fail-fast wrapper only. Legacy staging is never converted.
    """
    if schema not in {"main", "stage"}:
        raise ValueError("Unsupported staging semantics schema")
    error = "Unsupported legacy staging: recreate staging without --resume-staging/--retry-errors."
    try:
        row = conn.execute(
            f"SELECT value FROM {schema}.crawl_state WHERE key = ?",
            (AVAILABILITY_SEMANTICS_KEY,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        # Only absence of the store is legacy evidence; unrelated I/O/lock
        # failures retain their real SQLite diagnostic rather than being guessed.
        if "no such table" not in str(exc):
            raise
        raise RuntimeError(error) from exc
    if row is None or row[0] != AVAILABILITY_SEMANTICS_VALUE:
        raise RuntimeError(error)


def assert_video_availability_staging_semantics(staging_db: Path) -> None:
    """Fail fast on legacy resume via a read-only path, without authorizing merge."""
    conn = sqlite3.connect(staging_db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        assert_video_availability_staging_semantics_conn(conn, "main")
    finally:
        conn.close()


def _schema_contract(db_path: Path, *, schema_sql: str | None = None) -> dict[str, tuple[set[str], tuple[str, ...]]]:
    """Return crawler-owned columns and primary-key order for merge-managed tables.

    When ``schema_sql`` is provided the contract is read from an in-memory
    crawler schema. Otherwise it is read from an existing SQLite database.
    The updater uses this narrow contract instead of exact schema equality so
    Engine-owned production columns remain valid.
    """

    tables = ("instances", "channels", "videos")
    if schema_sql is None:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(":memory:")
        conn.executescript(schema_sql)
    try:
        contract: dict[str, tuple[set[str], tuple[str, ...]]] = {}
        for table in tables:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            if not rows:
                raise RuntimeError(f"Required table is missing: {table}")
            columns = {str(row[1]) for row in rows}
            primary_key = tuple(
                str(row[1])
                for row in sorted((row for row in rows if int(row[5]) > 0), key=lambda row: int(row[5]))
            )
            contract[table] = (columns, primary_key)
        return contract
    finally:
        conn.close()


def assert_production_schema_compatible(prod_db: Path, schema_path: Path) -> None:
    """Fail before updater work when prod lacks crawler-owned current-shape columns.

    Production may own additional columns such as ``videos.popularity``. The
    unsafe direction is the reverse: a staging column missing from production
    would be silently unmergeable. Production schema changes remain owned by
    ``migrate-whitelist.py`` rather than updater/crawler bootstrap code.
    """

    expected = _schema_contract(schema_path, schema_sql=schema_path.read_text(encoding="utf-8"))
    actual = _schema_contract(prod_db)
    problems: list[str] = []
    for table, (required_columns, required_pk) in expected.items():
        actual_columns, actual_pk = actual[table]
        missing = sorted(required_columns - actual_columns)
        if missing:
            problems.append(f"{table} missing columns: {', '.join(missing)}")
        if actual_pk != required_pk:
            problems.append(
                f"{table} primary key mismatch: expected {required_pk!r}, found {actual_pk!r}"
            )
    if problems:
        raise RuntimeError(
            "Production whitelist schema is older than the crawler-owned schema; "
            "run engine/server/db/jobs/migrate-whitelist.py before updater. "
            + "; ".join(problems)
        )


def shared_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Return ordered columns shared by prod main and attached staging table."""

    prod_cols = [row[1] for row in conn.execute(f"PRAGMA main.table_info({table})")]
    staging_cols = [row[1] for row in conn.execute(f"PRAGMA staging.table_info({table})")]
    return [col for col in prod_cols if col in staging_cols]


def _table_columns(conn: sqlite3.Connection, schema: str, table: str) -> set[str]:
    """Return the available columns for one attached SQLite table."""

    return {str(row[1]) for row in conn.execute(f"PRAGMA {schema}.table_info({table})")}


def _normalize_host_token(raw_host: str) -> str | None:
    """Normalize one host token using the same tolerant rules as crawler host files."""

    value = raw_host.strip().lower()
    if not value:
        return None
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        return parsed.hostname.lower() if parsed.hostname else None
    if "/" in value:
        parsed = urlparse(f"https://{value}")
        return parsed.hostname.lower() if parsed.hostname else None
    return value.strip(".") or None


def _normalize_host_tokens(raw_hosts: set[str] | None) -> set[str]:
    """Normalize caller-provided host scopes for exact SQLite comparisons."""

    if not raw_hosts:
        return set()
    return {
        normalized
        for host in raw_hosts
        if host
        for normalized in [_normalize_host_token(host)]
        if normalized
    }


def load_scoped_hosts_file(hosts_file: Path | None) -> set[str]:
    """Load and normalize an updater host-scope file using crawler-compatible rules."""

    if hosts_file is None:
        return set()
    raw_hosts = {
        line
        for line in hosts_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    return _normalize_host_tokens(raw_hosts)


def _resolve_scope_column(
    table_columns: set[str],
    *,
    preferred: tuple[str, ...],
) -> str | None:
    """Pick the host-bearing column used to scope one logical table."""

    for column in preferred:
        if column in table_columns:
            return column
    return None


def _host_scope_sql(
    conn: sqlite3.Connection,
    *,
    table: str,
    alias: str,
    scoped_hosts: set[str],
) -> tuple[str, list[str]]:
    """Build a host-scope predicate for staging rows when a targeted run is active.

    Host-scoped updater runs still seed the full prod `channels` table into
    staging. Without an explicit staging-side scope, the informational delta
    counts have to compare the entire seeded table and become the slowest part
    of the targeted updater run. Restricting the count to the selected hosts
    keeps the log representative for the current run and avoids scanning the
    full prod-sized staging copy.
    """

    if not scoped_hosts:
        return "", []
    staging_columns = _table_columns(conn, "staging", table)
    scope_column = _resolve_scope_column(
        staging_columns,
        preferred=("instance_domain", "host"),
    )
    if scope_column is None:
        return "", []
    placeholders = ", ".join("?" for _ in scoped_hosts)
    return (
        f"WHERE lower({alias}.{scope_column}) IN ({placeholders})",
        sorted(scoped_hosts),
    )


def _identity_join_sql(columns: tuple[str, ...], *, casefold: bool) -> str:
    """Build the prod/staging identity predicate for one candidate key."""

    if casefold:
        return " AND ".join(
            f"lower(COALESCE(p.{column}, '')) = lower(COALESCE(s.{column}, ''))"
            for column in columns
        )
    return " AND ".join(f"p.{column} = s.{column}" for column in columns)


def _count_missing_rows(
    conn: sqlite3.Connection,
    *,
    table: str,
    identity_candidates: list[tuple[str, ...]],
    scoped_hosts: set[str] | None = None,
) -> int:
    """Count staging rows absent from prod using the first compatible identity key.

    The updater has to compare crawler staging tables against whichever whitelist
    schema is currently deployed. Older tests still use legacy `host/name/uuid`
    columns while the current production DB uses `instance_domain`, `channel_id`,
    and `video_id`/`video_uuid`. Choosing the first identity tuple present in
    both schemas preserves compatibility across both layouts.
    """

    prod_columns = _table_columns(conn, "main", table)
    staging_columns = _table_columns(conn, "staging", table)

    normalized_scope = _normalize_host_tokens(scoped_hosts)
    scope_sql, scope_params = _host_scope_sql(
        conn,
        table=table,
        alias="s",
        scoped_hosts=normalized_scope,
    )

    for columns in identity_candidates:
        if not set(columns).issubset(prod_columns) or not set(columns).issubset(staging_columns):
            continue
        # Current whitelist identities are already normalized and indexed, so
        # exact equality preserves the composite PK/index fast path. Legacy
        # host/name/uuid layouts keep the historical case-insensitive behavior.
        casefold = columns in {("host",), ("host", "name"), ("host", "uuid")}
        join_sql = _identity_join_sql(columns, casefold=casefold)
        primary_column = columns[0]
        started_at = time.monotonic()
        logging.info(
            "staging delta count start table=%s key=%s scoped_hosts=%d",
            table,
            ",".join(columns),
            len(normalized_scope),
        )
        result = int(
            conn.execute(
                f"SELECT COUNT(*) FROM staging.{table} s "
                f"{scope_sql} "
                f"LEFT JOIN main.{table} p ON {join_sql} "
                f"WHERE p.{primary_column} IS NULL"
                if not scope_sql
                else
                f"SELECT COUNT(*) FROM ("
                f"SELECT * FROM staging.{table} s {scope_sql}"
                f") s LEFT JOIN main.{table} p ON {join_sql} "
                f"WHERE p.{primary_column} IS NULL",
                scope_params,
            ).fetchone()[0]
        )
        logging.info(
            "staging delta count done table=%s key=%s rows=%d elapsed_ms=%d",
            table,
            ",".join(columns),
            result,
            int((time.monotonic() - started_at) * 1000),
        )
        return result

    raise RuntimeError(
        f"Cannot count staging deltas for table '{table}': no shared identity columns in prod/staging."
    )


def seed_staging_from_prod(prod_db: Path, staging_db: Path) -> None:
    """Seed instances/channels from prod into staging using shared columns only."""

    with sqlite3.connect(prod_db) as conn:
        conn.execute("ATTACH DATABASE ? AS staging", (staging_db.as_posix(),))
        for table in ("instances", "channels"):
            cols = shared_columns(conn, table)
            if not cols:
                continue
            col_sql = ", ".join(f'"{col}"' for col in cols)
            conn.execute(
                f"INSERT OR REPLACE INTO staging.{table} ({col_sql}) "
                f"SELECT {col_sql} FROM main.{table}"
            )
        conn.execute(
            "INSERT OR REPLACE INTO staging.crawl_state(key, value) VALUES (?, datetime('now'))",
            ("stage_seeded_at",),
        )
        conn.execute(
            "INSERT OR REPLACE INTO staging.crawl_state(key, value) VALUES (?, ?)",
            ("stage_seeded_from", prod_db.as_posix()),
        )
        conn.commit()
        conn.execute("DETACH DATABASE staging")


def count_staging_deltas(
    prod_db: Path, staging_db: Path, scoped_hosts: set[str] | None = None
) -> dict[str, int]:
    """Count current staging rows not present in prod by primary identity.

    `scoped_hosts` is used for targeted updater runs so informational delta
    logging reflects only the selected instances instead of the entire seeded
    staging copy.
    """

    with sqlite3.connect(prod_db) as conn:
        conn.execute("ATTACH DATABASE ? AS staging", (staging_db.as_posix(),))
        instances_new = _count_missing_rows(
            conn,
            table="instances",
            identity_candidates=[("host",)],
            scoped_hosts=scoped_hosts,
        )
        channels_new = _count_missing_rows(
            conn,
            table="channels",
            identity_candidates=[
                ("channel_id", "instance_domain"),
                ("host", "name"),
            ],
            scoped_hosts=scoped_hosts,
        )
        videos_new = _count_missing_rows(
            conn,
            table="videos",
            identity_candidates=[
                ("video_id", "instance_domain"),
                ("video_uuid", "instance_domain"),
                ("host", "uuid"),
            ],
            scoped_hosts=scoped_hosts,
        )
        embeddings_new = 0
        prod_has_embeddings = conn.execute(
            "SELECT COUNT(*) FROM main.sqlite_master WHERE type='table' AND name='video_embeddings'"
        ).fetchone()[0]
        staging_has_embeddings = conn.execute(
            
                "SELECT COUNT(*) FROM staging.sqlite_master "
                "WHERE type='table' AND name='video_embeddings'"
            
        ).fetchone()[0]
        if prod_has_embeddings and staging_has_embeddings:
            embedding_scope = _normalize_host_tokens(scoped_hosts)
            prod_embedding_columns = _table_columns(conn, "main", "video_embeddings")
            staging_embedding_columns = _table_columns(conn, "staging", "video_embeddings")
            composite_identity = {"video_id", "instance_domain"}.issubset(
                prod_embedding_columns
            ) and {"video_id", "instance_domain"}.issubset(staging_embedding_columns)
            identity_label = "video_id,instance_domain" if composite_identity else "video_id"
            started_at = time.monotonic()
            logging.info(
                "staging delta count start table=video_embeddings key=%s scoped_hosts=%d",
                identity_label,
                len(embedding_scope),
            )
            identity_match = "p.video_id = s.video_id"
            if composite_identity:
                identity_match += " AND p.instance_domain = s.instance_domain"

            if embedding_scope:
                placeholders = ", ".join("?" for _ in embedding_scope)
                if "instance_domain" in staging_embedding_columns:
                    scope_expr = f"lower(s.instance_domain) IN ({placeholders})"
                    scope_join = ""
                else:
                    # Legacy embedding tables have no host column, so recover the
                    # scope through the staging videos table when possible.
                    scope_expr = f"lower(sv.instance_domain) IN ({placeholders})"
                    scope_join = "JOIN staging.videos sv ON sv.video_id = s.video_id "
                embeddings_new = conn.execute(
                    "SELECT COUNT(*) "
                    "FROM staging.video_embeddings s "
                    f"{scope_join}"
                    f"WHERE {scope_expr} "
                    "AND NOT EXISTS ("
                    f"  SELECT 1 FROM main.video_embeddings p WHERE {identity_match}"
                    ")",
                    sorted(embedding_scope),
                ).fetchone()[0]
            else:
                embeddings_new = conn.execute(
                    "SELECT COUNT(*) FROM staging.video_embeddings s "
                    "WHERE NOT EXISTS ("
                    f"  SELECT 1 FROM main.video_embeddings p WHERE {identity_match}"
                    ")"
                ).fetchone()[0]
            logging.info(
                "staging delta count done table=video_embeddings key=%s rows=%d elapsed_ms=%d",
                identity_label,
                embeddings_new,
                int((time.monotonic() - started_at) * 1000),
            )
        conn.execute("DETACH DATABASE staging")
    return {
        "instances_new": int(instances_new),
        "channels_new": int(channels_new),
        "videos_new": int(videos_new),
        "embeddings_new": int(embeddings_new),
    }


def prune_staging_local_non_ok_instances(*, prod_db: Path, staging_db: Path) -> dict[str, int]:
    """Drop staging hosts that are marked non-ok in the prod instances table."""

    with sqlite3.connect(prod_db) as conn:
        bad_hosts = {
            str(row[0]).strip().lower()
            for row in conn.execute(
                "SELECT host FROM instances WHERE lower(COALESCE(health_status, 'ok')) != 'ok'"
            )
            if row[0]
        }
    if not bad_hosts:
        return {"removed": 0, "remaining": 0}
    placeholders = ",".join("?" for _ in bad_hosts)
    params = sorted(bad_hosts)
    with sqlite3.connect(staging_db) as conn:
        removed = 0
        for table in ("videos", "channels", "instances"):
            columns = _table_columns(conn, "main", table)
            host_column = _resolve_scope_column(
                columns,
                preferred=("instance_domain", "host"),
            )
            if host_column is None:
                continue
            cur = conn.execute(
                f"DELETE FROM {table} WHERE lower({host_column}) IN ({placeholders})",
                params,
            )
            removed += cur.rowcount
        remaining = conn.execute("SELECT COUNT(*) FROM instances").fetchone()[0]
        conn.commit()
    logging.info("staging local non-ok prune removed=%d remaining_instances=%d", removed, remaining)
    return {"removed": int(removed), "remaining": int(remaining)}


def inject_replace_embedding_for_test(*, prod_db: Path, staging_db: Path) -> None:
    """Inject one staging embedding overlap to preserve the existing test hook."""

    with sqlite3.connect(prod_db) as prod, sqlite3.connect(staging_db) as staging:
        prod_has = prod.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='video_embeddings'"
        ).fetchone()[0]
        staging_has = staging.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='video_embeddings'"
        ).fetchone()[0]
        if not prod_has or not staging_has:
            logging.info("test embedding injection skipped: video_embeddings table missing")
            return
        row = prod.execute("SELECT * FROM video_embeddings LIMIT 1").fetchone()
        if row is None:
            logging.info("test embedding injection skipped: no prod embedding row")
            return
        cols = [info[1] for info in prod.execute("PRAGMA table_info(video_embeddings)")]
        placeholders = ", ".join("?" for _ in cols)
        col_sql = ", ".join(f'"{col}"' for col in cols)
        staging.execute(
            f"INSERT OR REPLACE INTO video_embeddings ({col_sql}) VALUES ({placeholders})",
            row,
        )
        staging.commit()
        logging.info("test embedding injection inserted overlapping video_embeddings row")
