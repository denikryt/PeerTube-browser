"""Staging database helpers for the updater pipeline.

These helpers preserve the current SQLite table assumptions while moving DB
operations out of the executable updater wrapper.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

# TODO(peertube-browser-video-availability-generation-cutover): Remove legacy corpus
# rejection after pre-v2 corpora are unsupported.
AVAILABILITY_SEMANTICS_KEY = "video_availability_semantics"
AVAILABILITY_SEMANTICS_VALUE = "canonical_absence_atomic_ingest_v2"
VIDEO_CORPUS_ROLE_KEY = "video_corpus_role"
UPDATER_STAGING_ROLE = "updater_staging_delta"


def remove_db_with_sidecars(db_path: Path) -> None:
    """Remove an SQLite DB and WAL/SHM sidecars using current file names."""

    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db_path) + suffix)
        if path.exists():
            path.unlink()


def init_staging_db(staging_db: Path, schema_path: Path) -> None:
    """Recreate DB/sidecars and stamp fresh staging writer semantics plus corpus kind.

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
        conn.execute(
            "INSERT OR REPLACE INTO crawl_state(key, value) VALUES (?, ?)",
            (VIDEO_CORPUS_ROLE_KEY, UPDATER_STAGING_ROLE),
        )
        _ensure_video_availability_work(conn)
        conn.commit()


def assert_video_availability_staging_semantics_conn(conn: sqlite3.Connection, schema: str) -> None:
    """Authorize only the exact writer generation and updater-delta corpus kind.

    Merge passes its already attached stage within its transaction; pathname
    validation is a fail-fast wrapper only. Legacy staging is never converted.
    """
    if schema not in {"main", "stage", "evidence"}:
        raise ValueError("Unsupported staging semantics schema")
    error = "Unsupported legacy staging: recreate staging without --resume-staging/--retry-errors."
    try:
        semantics_row = conn.execute(
            f"SELECT value FROM {schema}.crawl_state WHERE key = ?",
            (AVAILABILITY_SEMANTICS_KEY,),
        ).fetchone()
        role_row = conn.execute(
            f"SELECT value FROM {schema}.crawl_state WHERE key = ?",
            (VIDEO_CORPUS_ROLE_KEY,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        # Only absence of the store is legacy evidence; unrelated I/O/lock
        # failures retain their real SQLite diagnostic rather than being guessed.
        if "no such table" not in str(exc):
            raise
        raise RuntimeError(error) from exc
    if semantics_row is None or semantics_row[0] != AVAILABILITY_SEMANTICS_VALUE:
        raise RuntimeError(error)
    # Corpus kind is permanent workflow identity rather than part of the
    # removable writer-generation cutover. Roleless standalone DBs must never
    # be admitted to the updater delta-merge lifecycle.
    if role_row is None or role_row[0] != UPDATER_STAGING_ROLE:
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
    json_host_scope: bool = False,
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
        if json_host_scope:
            raise RuntimeError(f"Scoped JSON delta count requires host column in {table}")
        return "", []
    if json_host_scope:
        return (
            f"WHERE lower(trim({alias}.{scope_column})) IN (SELECT value FROM json_each(?))",
            [json.dumps(sorted(_validated_host_set(scoped_hosts)))],
        )
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
    json_host_scope: bool = False,
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

    normalized_scope = (
        _validated_host_set(scoped_hosts or set())
        if json_host_scope
        else _normalize_host_tokens(scoped_hosts)
    )
    scope_sql, scope_params = _host_scope_sql(
        conn,
        table=table,
        alias="s",
        scoped_hosts=normalized_scope,
        json_host_scope=json_host_scope,
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
                else f"SELECT COUNT(*) FROM ("
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


def seed_staging_from_prod(
    prod_db: Path, staging_db: Path, hosts: set[str] | None = None
) -> None:
    """Seed parent metadata from production, optionally for exact existing hosts.

    Strict-sync availability copies only existing selected parents. A scoped
    seed cannot import unrelated stale production parents or overwrite new-host
    discovery; parent health is reset before any fresh network observation.
    """

    with sqlite3.connect(prod_db) as conn:
        conn.execute("ATTACH DATABASE ? AS staging", (staging_db.as_posix(),))
        scoped_json = json.dumps(sorted(_validated_host_set(hosts))) if hosts is not None else None
        for table in ("instances", "channels"):
            cols = shared_columns(conn, table)
            if not cols:
                continue
            col_sql = ", ".join(f'"{col}"' for col in cols)
            host_col = "host" if table == "instances" else "instance_domain"
            predicate = (
                f" WHERE {host_col} IN (SELECT value FROM json_each(?))"
                if scoped_json is not None else ""
            )
            conn.execute(
                f"INSERT OR {'IGNORE' if scoped_json is not None else 'REPLACE'} "
                f"INTO staging.{table} ({col_sql}) "
                f"SELECT {col_sql} FROM main.{table}{predicate}",
                (scoped_json,) if scoped_json is not None else (),
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


def list_staging_hosts(staging_db: Path) -> set[str]:
    """Return currently discovered normalized staging hosts for scope freezing.

    This read happens after registry discovery; the selected result becomes a
    single immutable cross-process host file, not separate CLI selections.
    """
    with closing(sqlite3.connect(staging_db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        return {str(row[0]) for row in conn.execute("SELECT host FROM instances") if row[0]}


def assert_retry_parent_provenance(staging_db: Path, selected: set[str]) -> None:
    """Validate current enumeration only for actual count/video repair candidates.

    Inspect error records before eligibility filters: a real candidate with old
    provenance must fail explicitly, while unrelated legacy hosts do not block it.
    """
    if not selected:
        return
    with closing(sqlite3.connect(staging_db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        scope = json.dumps(sorted(selected))
        count_hosts = {str(row[0]) for row in conn.execute("""
            SELECT DISTINCT c.instance_domain FROM channels c
            WHERE c.instance_domain IN (SELECT value FROM json_each(?))
              AND c.channel_name IS NOT NULL AND c.videos_count IS NULL
              AND c.last_error_source='videos_count'
        """, (scope,))}
        video_hosts = {str(row[0]) for row in conn.execute("""
            SELECT DISTINCT p.instance_domain FROM video_crawl_progress p
            JOIN channels c ON c.channel_id=p.channel_id AND c.instance_domain=p.instance_domain
            WHERE p.instance_domain IN (SELECT value FROM json_each(?))
              AND p.status='error' AND c.videos_count >= 1
              AND c.channel_name IS NOT NULL
        """, (scope,))}
        candidates = count_hosts | video_hosts
        if not candidates:
            return
        actual = {row[0] for row in conn.execute("""
            SELECT p.instance_domain FROM channel_crawl_progress p
            JOIN crawl_state state ON state.key='parent_enumeration_v1:' || p.instance_domain
            WHERE p.instance_domain IN (SELECT value FROM json_each(?))
              AND state.value='page_zero_complete_v1' AND p.last_start=0
        """, (json.dumps(sorted(candidates)),))}
    missing = candidates - actual
    if missing:
        raise RuntimeError(
            "Missing verified parent enumeration for " + ", ".join(sorted(missing)) +
            "; run ordinary --resume-staging for these hosts before --retry-errors"
        )


def count_staging_deltas(
    prod_db: Path,
    staging_db: Path,
    scoped_hosts: set[str] | None = None,
    *,
    json_host_scope: bool = False,
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
            json_host_scope=json_host_scope,
        )
        channels_new = _count_missing_rows(
            conn,
            table="channels",
            identity_candidates=[
                ("channel_id", "instance_domain"),
                ("host", "name"),
            ],
            scoped_hosts=scoped_hosts,
            json_host_scope=json_host_scope,
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
            json_host_scope=json_host_scope,
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
            embedding_scope = (
                _validated_host_set(scoped_hosts or set())
                if json_host_scope
                else _normalize_host_tokens(scoped_hosts)
            )
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

            if embedding_scope and json_host_scope:
                # EXISTS recovers hostless identity without multiplying embeddings
                # when the same video ID is present on several selected domains.
                if "instance_domain" in staging_embedding_columns:
                    scope_expr = (
                        "lower(trim(s.instance_domain)) IN (SELECT value FROM json_each(?))"
                    )
                else:
                    if "instance_domain" not in _table_columns(conn, "staging", "videos"):
                        raise RuntimeError("Scoped JSON embeddings require videos.instance_domain")
                    scope_expr = (
                        "EXISTS (SELECT 1 FROM staging.videos sv WHERE sv.video_id=s.video_id "
                        "AND lower(trim(sv.instance_domain)) IN (SELECT value FROM json_each(?)))"
                    )
                embeddings_new = conn.execute(
                    "SELECT COUNT(*) FROM staging.video_embeddings s WHERE "
                    + scope_expr
                    + " AND NOT EXISTS (SELECT 1 FROM main.video_embeddings p WHERE "
                    + identity_match
                    + ")",
                    [json.dumps(sorted(embedding_scope))],
                ).fetchone()[0]
            elif embedding_scope:
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


AVAILABILITY_WORK_DDL = """CREATE TABLE IF NOT EXISTS video_availability_work (
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  video_uuid TEXT NOT NULL,
  outcome TEXT CHECK (outcome IS NULL OR outcome IN ('available', 'not_found', 'gone', 'unknown')),
  checked_at INTEGER,
  error TEXT,
  PRIMARY KEY (video_id, instance_domain)
)"""
AVAILABILITY_WORK_INDEX_DDL = """CREATE INDEX IF NOT EXISTS idx_availability_work_host_identity
 ON video_availability_work (lower(trim(instance_domain)), video_id, instance_domain)"""
WORK_SCOPE_SQL = """
 AND lower(trim(v.instance_domain)) NOT IN (SELECT value FROM json_each(:denied_json))
 AND (:unscoped = 1 OR lower(trim(v.instance_domain)) IN
      (SELECT value FROM json_each(:included_json)))
 -- A production video is eligible only after this invocation verified both
 -- parents, completed page-zero enumeration, and stamped host provenance.
 AND EXISTS (
   SELECT 1 FROM instances i
   JOIN channels c ON c.instance_domain = i.host
   JOIN channel_crawl_progress p ON p.instance_domain = i.host
   JOIN crawl_state provenance ON provenance.key = 'parent_enumeration_v1:' || i.host
   WHERE i.host = lower(trim(v.instance_domain))
     AND c.channel_id = v.channel_id
     AND i.health_status = 'ok' AND i.health_checked_at IS NOT NULL
     AND c.health_status = 'ok' AND c.health_checked_at IS NOT NULL
     AND p.status = 'done' AND p.last_start = 0
     AND provenance.value = 'page_zero_complete_v1'
 )
"""


def require_sqlite_json_each() -> None:
    """Probe the actual updater SQLite runtime before side effects; no fallback."""
    try:
        with closing(sqlite3.connect(":memory:")) as conn:
            if conn.execute("SELECT value FROM json_each(?)", ('["capability"]',)).fetchall() != [
                ("capability",)
            ]:
                raise RuntimeError("SQLite json_each/JSON1 unavailable in updater Python runtime")
    except sqlite3.Error as exc:
        raise RuntimeError(
            "SQLite json_each/JSON1 unavailable in updater Python runtime; upgrade Python SQLite"
        ) from exc


def _validated_host_set(hosts: set[str]) -> set[str]:
    """Reject non-string or noncanonical membership before serialization."""
    if not isinstance(hosts, (set, frozenset)):
        raise ValueError("Host scope must be a normalized string set")
    for host in hosts:
        if not isinstance(host, str) or not host or _normalize_host_token(host) != host:
            raise ValueError("Host scope must contain normalized nonblank strings only")
    return set(hosts)


def _ddl_fingerprint(sql: str) -> str:
    """Compare the owned DDL, including constraints and expression index."""
    # Literal labels are case-sensitive CHECK values; normalize SQL syntax only.
    parts = re.split("('(?:''|[^'])*')", sql)
    return "".join(
        part if i % 2 else "".join(part.lower().split()).replace("ifnotexists", "")
        for i, part in enumerate(parts)
    ).rstrip(";")


def _ensure_video_availability_work(conn: sqlite3.Connection) -> None:
    """Ensure only additive exact updater work schema; never repair legacy DDL."""
    assert_video_availability_staging_semantics_conn(conn, "main")
    for name, ddl in [
        ("video_availability_work", AVAILABILITY_WORK_DDL),
        ("idx_availability_work_host_identity", AVAILABILITY_WORK_INDEX_DDL),
    ]:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
        if row and (row[0] is None or _ddl_fingerprint(row[0]) != _ddl_fingerprint(ddl)):
            raise RuntimeError(
                "Incompatible video availability work schema; recreate staging without resume"
            )
    # Validate both definitions before creating either, preserving incompatible evidence.
    conn.execute(AVAILABILITY_WORK_DDL)
    conn.execute(AVAILABILITY_WORK_INDEX_DDL)


def reset_video_availability_work(staging_db: Path) -> None:
    """Discard old observations on every accepted invocation, including resume."""
    with (
        closing(sqlite3.connect(staging_db.resolve().as_uri() + "?mode=rw", uri=True)) as conn,
        conn,
    ):
        _ensure_video_availability_work(conn)
        conn.execute("DELETE FROM video_availability_work")


def materialize_video_availability_work(
    prod_db: Path,
    staging_db: Path,
    *,
    included_hosts: set[str] | None,
    denied_hosts: set[str],
) -> int:
    """Copy production identities and count UUID skips in one short read snapshot.

    Production is read-only and detached/closed before the caller starts HTTP.
    Result identity preserves original domain bytes; host scope is normalized.
    """
    included = None if included_hosts is None else _validated_host_set(included_hosts)
    if included is not None and not included:
        raise ValueError("Explicit availability host scope must be nonempty")
    denied = _validated_host_set(denied_hosts)
    params = dict(
        included_json=json.dumps(sorted(included or [])),
        denied_json=json.dumps(sorted(denied)),
        unscoped=int(included is None),
    )
    with closing(sqlite3.connect(staging_db.resolve().as_uri() + "?mode=rw", uri=True)) as conn:
        _ensure_video_availability_work(conn)
        if conn.execute("SELECT COUNT(*) FROM video_availability_work").fetchone()[0]:
            raise RuntimeError("Availability work must be reset before materialization")
        conn.execute(
            "ATTACH DATABASE ? AS production",
            (prod_db.resolve().as_uri() + "?mode=ro",),
        )
        try:
            conn.execute("BEGIN IMMEDIATE")
            missing = int(
                conn.execute(
                    "SELECT COUNT(*) FROM production.videos v WHERE "
                    "(v.video_uuid IS NULL OR length(trim(v.video_uuid))=0)" + WORK_SCOPE_SQL,
                    params,
                ).fetchone()[0]
            )
            conn.execute(
                "INSERT INTO main.video_availability_work(video_id,instance_domain,video_uuid) "
                "SELECT v.video_id,v.instance_domain,v.video_uuid FROM production.videos v "
                "WHERE v.video_uuid IS NOT NULL AND length(trim(v.video_uuid))>0" + WORK_SCOPE_SQL,
                params,
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.execute("DETACH DATABASE production")
    return missing


def inspect_video_availability_work(
    conn: sqlite3.Connection, schema: str = "main"
) -> dict[str, int]:
    """Inspect completed evidence read-only in the caller's consistent snapshot.

    Only owned aliases are interpolated. Generation, corpus, table and index
    must match exactly; this function never creates or repairs work schema.
    """
    if schema not in {"main", "stage", "evidence"}:
        raise ValueError("Unsupported availability evidence schema")
    assert_video_availability_staging_semantics_conn(conn, schema)
    for name, ddl in (
        ("video_availability_work", AVAILABILITY_WORK_DDL),
        ("idx_availability_work_host_identity", AVAILABILITY_WORK_INDEX_DDL),
    ):
        row = conn.execute(
            f"SELECT sql FROM {schema}.sqlite_master WHERE name=?", (name,)
        ).fetchone()
        if not row or row[0] is None or _ddl_fingerprint(row[0]) != _ddl_fingerprint(ddl):
            raise RuntimeError("Incompatible video availability work schema; recreate staging")
    # Named aggregates keep report and validation independent of SELECT order.
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    counts = cursor.execute(f"""SELECT COUNT(*) AS selected_videos,
      COUNT(*) FILTER (WHERE outcome='available') AS available,
      COUNT(*) FILTER (WHERE outcome='not_found') AS not_found,
      COUNT(*) FILTER (WHERE outcome='gone') AS gone,
      COUNT(*) FILTER (WHERE outcome='unknown') AS unknown,
      COUNT(*) FILTER (WHERE outcome IS NULL) AS unfinished,
      COUNT(checked_at) AS video_requests_attempted
      FROM {schema}.video_availability_work""").fetchone()
    invalid = cursor.execute(f"""SELECT COUNT(*) FROM {schema}.video_availability_work
      WHERE typeof(video_id) != 'text' OR length(trim(video_id))=0
      OR typeof(instance_domain) != 'text' OR length(trim(instance_domain))=0
      OR typeof(video_uuid) != 'text' OR length(trim(video_uuid))=0
      OR typeof(checked_at) != 'integer' OR checked_at < 0
      OR checked_at > 9007199254740991
      OR (outcome='unknown' AND (error IS NULL OR length(trim(error))=0
          OR length(error)>512 OR instr(error,char(10))>0 OR instr(error,char(13))>0))
      OR (outcome IN ('available','not_found','gone') AND error IS NOT NULL)
      OR error LIKE 'host_preflight: %'""").fetchone()[0]
    if (
        counts["unfinished"]
        or invalid
        or counts["selected_videos"] != (
            counts["available"] + counts["not_found"] + counts["gone"] + counts["unknown"]
        )
        or counts["video_requests_attempted"] != counts["selected_videos"]
    ):
        raise RuntimeError("Availability sweep incomplete or inconsistent; no success report")
    return dict(
        selected_videos=counts["selected_videos"],
        available=counts["available"],
        not_found=counts["not_found"],
        gone=counts["gone"],
        unknown=counts["unknown"],
        hosts_processed=cursor.execute(f"""SELECT COUNT(DISTINCT lower(trim(instance_domain)))
          FROM {schema}.video_availability_work""").fetchone()[0],
        video_requests_attempted=counts["video_requests_attempted"],
    )


def video_availability_report(staging_db: Path, *, missing_uuid: int) -> dict[str, int]:
    """Build the finished sweep report without authorizing canonical publication."""
    if not isinstance(missing_uuid, int) or missing_uuid < 0:
        raise ValueError("Invalid missing UUID count")
    with closing(sqlite3.connect(staging_db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        # Keep all integrity/count reads in one snapshot even for standalone reports.
        conn.execute("BEGIN")
        result = inspect_video_availability_work(conn)
    result["missing_uuid"] = missing_uuid
    return result
