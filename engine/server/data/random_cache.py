"""Build and consume the updater-owned persisted random browse-order artifact.

Production Engine runtime is strictly read-only.  Writable helpers exist only
for the build/updater path, which publishes a fully validated sibling temporary
SQLite file with one atomic ``os.replace``.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import logging
import os
import random
import re
import sqlite3
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote

RANDOM_CACHE_SCHEMA_VERSION = 2
_BUILD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_REQUIRED_CANONICAL_TABLES = {
    "videos",
    "video_embeddings",
    "video_index_ids",
    "video_tags",
    "channels",
    "instance_denylist",
    "channel_moderation",
}


class RandomCacheUnavailable(RuntimeError):
    """Report an unavailable or incompatible random-cache artifact."""


def _readonly_uri(path: Path) -> str:
    """Return an SQLite URI that cannot create or write the requested database."""
    absolute = path.expanduser().resolve().as_posix()
    return f"file:{quote(absolute, safe='/:')}?mode=ro"


def connect_random_cache_db(path: Path) -> sqlite3.Connection:
    """Open a writable random-cache DB for build/test code only."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def open_random_cache_artifact_readonly(path: Path) -> sqlite3.Connection:
    """Open and validate only the authoritative artifact file without creating it."""
    try:
        conn = sqlite3.connect(_readonly_uri(path), uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        validate_random_cache_artifact(conn)
        return conn
    except (OSError, sqlite3.Error, RandomCacheUnavailable) as exc:
        try:
            conn.close()  # type: ignore[possibly-undefined]
        except Exception:
            pass
        if isinstance(exc, RandomCacheUnavailable):
            raise
        raise RandomCacheUnavailable(str(exc)) from exc


def open_random_provider_readonly(random_path: Path, canonical_db_path: Path) -> sqlite3.Connection:
    """Open the long-lived read-only Random provider with canonical DB attached.

    Both database files are URI ``mode=ro`` and ``query_only`` is enabled after
    attach.  This connection is the only SQL boundary used by paged Random, so
    no second main-DB lock or Python batch-resolution loop is required.
    """
    conn = open_random_cache_artifact_readonly(random_path)
    try:
        conn.execute("ATTACH DATABASE ? AS canonical", (_readonly_uri(canonical_db_path),))
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            "SELECT name FROM canonical.sqlite_master WHERE type='table'"
        ).fetchall()
        tables = {str(row["name"]) for row in rows}
        missing = sorted(_REQUIRED_CANONICAL_TABLES - tables)
        if missing:
            raise RandomCacheUnavailable(
                f"Canonical DB missing required Random tables: {', '.join(missing)}"
            )
        return conn
    except Exception as exc:
        conn.close()
        if isinstance(exc, RandomCacheUnavailable):
            raise
        raise RandomCacheUnavailable(str(exc)) from exc


def validate_random_cache_artifact(conn: sqlite3.Connection) -> dict[str, object]:
    """Validate exact v2 schema, completion identity, and persisted-order invariants."""
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    expected_tables = {"random_cache_meta", "random_index_ids"}
    if tables != expected_tables:
        raise RandomCacheUnavailable(
            "Random cache schema must contain only generation metadata and persisted order"
        )

    expected_columns = {
        "random_cache_meta": {"singleton_id", "schema_version", "build_id", "built_at"},
        "random_index_ids": {"position", "index_id"},
    }
    for table, expected in expected_columns.items():
        columns = {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}
        if columns != expected:
            raise RandomCacheUnavailable(f"Random cache {table} columns are incompatible")

    meta_rows = conn.execute(
        "SELECT schema_version, build_id, built_at FROM random_cache_meta WHERE singleton_id=1"
    ).fetchall()
    if len(meta_rows) != 1:
        raise RandomCacheUnavailable("Random cache completion metadata is missing")
    meta = meta_rows[0]
    try:
        schema_version = int(meta["schema_version"])
    except (TypeError, ValueError) as exc:
        raise RandomCacheUnavailable("Random cache schema version is invalid") from exc
    if schema_version != RANDOM_CACHE_SCHEMA_VERSION:
        raise RandomCacheUnavailable("Random cache schema version is incompatible")
    build_id = str(meta["build_id"] or "")
    if not _BUILD_ID_RE.fullmatch(build_id):
        raise RandomCacheUnavailable("Random cache build id is invalid")

    stats = conn.execute(
        """
        SELECT
          COUNT(*) AS count,
          COUNT(DISTINCT index_id) AS distinct_index_ids,
          SUM(CASE WHEN index_id IS NULL THEN 1 ELSE 0 END) AS null_index_ids,
          MIN(position) AS min_position,
          MAX(position) AS max_position
        FROM random_index_ids
        """
    ).fetchone()
    try:
        count = int(stats["count"] or 0)
        distinct_index_ids = int(stats["distinct_index_ids"] or 0)
        null_index_ids = int(stats["null_index_ids"] or 0)
        min_position = int(stats["min_position"] or 0)
        max_position = int(stats["max_position"] or 0)
    except (TypeError, ValueError) as exc:
        raise RandomCacheUnavailable("Random cache order metadata is invalid") from exc
    if null_index_ids or distinct_index_ids != count:
        raise RandomCacheUnavailable("Random cache index ids are not unique non-null values")
    if count > 0 and (min_position != 1 or max_position != count):
        raise RandomCacheUnavailable("Random cache positions are not contiguous")
    return {
        "schema_version": RANDOM_CACHE_SCHEMA_VERSION,
        "build_id": build_id,
        "built_at": str(meta["built_at"]),
        "count": count,
    }


def read_random_cache_meta(conn: sqlite3.Connection) -> dict[str, object]:
    """Read immutable generation metadata from an already validated artifact.

    Runtime opens and validates the artifact once and does not hot-reload it.
    Re-running the full table-shape/contiguity validation for every Random page
    would turn a page request into an O(artifact-size) metadata check.  Because
    the open connection is read-only, ``MAX(position)`` is the validated row
    count for the lifetime of that connection.
    """
    meta = conn.execute(
        "SELECT schema_version, build_id, built_at FROM random_cache_meta WHERE singleton_id=1"
    ).fetchone()
    if meta is None:
        raise RandomCacheUnavailable("Random cache completion metadata is missing")
    max_row = conn.execute("SELECT MAX(position) AS max_position FROM random_index_ids").fetchone()
    count = int(max_row["max_position"] or 0) if max_row is not None else 0
    return {
        "schema_version": int(meta["schema_version"]),
        "build_id": str(meta["build_id"]),
        "built_at": str(meta["built_at"]),
        "count": count,
    }


def rebuild_random_cache(
    src_db: sqlite3.Connection,
    final_path: Path,
    *,
    size: int,
    refresh: bool = False,
    filtered_mode: bool = False,
    max_per_instance: int = 0,
    max_per_author: int = 0,
    built_at: str | int | None = None,
) -> dict[str, object]:
    """Build a sibling temporary artifact, validate it read-only, then publish atomically."""
    if size < 0:
        raise ValueError("size must be non-negative")
    if not refresh and final_path.exists():
        try:
            with closing(open_random_cache_artifact_readonly(final_path)) as existing:
                meta = read_random_cache_meta(existing)
            if int(meta["count"]) >= size:
                return {**meta, "rebuilt": False}
        except RandomCacheUnavailable:
            # An invalid final file is never repaired in place; a fresh sibling
            # artifact will replace it only after full validation.
            pass

    final_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{final_path.name}.tmp-", dir=final_path.parent.as_posix()
    )
    os.close(fd)
    temp_path = Path(temp_name)
    build_id = uuid.uuid4().hex
    build_time = str(built_at) if built_at is not None else datetime.now(timezone.utc).isoformat()
    published = False
    try:
        with closing(connect_random_cache_db(temp_path)) as temp_db:
            temp_db.execute("PRAGMA journal_mode=DELETE")
            try:
                from engine.server.db.bootstrap import bootstrap_engine_random_cache_db
            except ModuleNotFoundError:  # pragma: no cover - direct script execution path
                from db.bootstrap import bootstrap_engine_random_cache_db
            bootstrap_engine_random_cache_db(temp_db)
            count = populate_random_cache(
                src_db,
                temp_db,
                size,
                filtered_mode=filtered_mode,
                max_per_instance=max_per_instance,
                max_per_author=max_per_author,
            )
            # Completion metadata is written last.  A temp DB without this row is
            # intentionally invalid and can never become authoritative.
            temp_db.execute("DELETE FROM random_cache_meta")
            temp_db.execute(
                "INSERT INTO random_cache_meta(singleton_id, schema_version, build_id, built_at) VALUES (1, ?, ?, ?)",
                (RANDOM_CACHE_SCHEMA_VERSION, build_id, build_time),
            )
            temp_db.commit()

        with closing(open_random_cache_artifact_readonly(temp_path)) as validator:
            validated = read_random_cache_meta(validator)
        if int(validated["count"]) != int(count):
            raise RandomCacheUnavailable("Random cache validation count mismatch")
        os.replace(temp_path, final_path)
        published = True
        return {**validated, "rebuilt": True}
    finally:
        if not published:
            temp_path.unlink(missing_ok=True)
            Path(f"{temp_path}-journal").unlink(missing_ok=True)


def populate_random_cache(
    src_db: sqlite3.Connection,
    cache_db: sqlite3.Connection,
    size: int,
    filtered_mode: bool = False,
    max_per_instance: int = 0,
    max_per_author: int = 0,
) -> int:
    """Populate one freshly bootstrapped build artifact with stable active video index ids."""
    if size <= 0:
        return 0
    total_row = src_db.execute(
        """
        SELECT COUNT(*) AS total, MIN(vii.index_id) AS min_id, MAX(vii.index_id) AS max_id
        FROM video_index_ids vii
        JOIN video_embeddings e
          ON e.video_id = vii.video_id AND e.instance_domain = vii.instance_domain
        JOIN videos v
          ON v.video_id = vii.video_id AND v.instance_domain = vii.instance_domain
        WHERE vii.is_active = 1
        """
    ).fetchone()
    if not total_row or int(total_row["total"] or 0) == 0:
        cache_db.commit()
        return 0
    total = int(total_row["total"])
    min_id = int(total_row["min_id"])
    max_id = int(total_row["max_id"])
    target = min(size, total)
    start_id = random.randint(min_id, max_id)
    if not filtered_mode or (max_per_instance <= 0 and max_per_author <= 0):
        rows = _fetch_unfiltered_index_ids(src_db, start_id, target, before_start=False)
        if len(rows) < target:
            rows += _fetch_unfiltered_index_ids(src_db, start_id, target - len(rows), before_start=True)
        random.shuffle(rows)
        cache_db.executemany(
            "INSERT INTO random_index_ids (position, index_id) VALUES (?, ?)",
            [(index, int(row["index_id"])) for index, row in enumerate(rows, start=1)],
        )
        cache_db.commit()
        return len(rows)

    index_ids: list[int] = []
    instance_counts: dict[str, int] = {}
    author_counts: dict[str, int] = {}
    seen: set[int] = set()
    scanned = 0
    chunk_size = 10000

    def try_add(entry: sqlite3.Row) -> bool:
        """Add a candidate while preserving existing builder diversity caps."""
        index_id = int(entry["index_id"])
        if index_id in seen:
            return False
        instance = entry["instance_domain"] or ""
        if max_per_instance > 0 and instance_counts.get(instance, 0) >= max_per_instance:
            return False
        channel_id = entry["channel_id"]
        author = f"{channel_id}::{instance}" if channel_id else None
        if author and max_per_author > 0 and author_counts.get(author, 0) >= max_per_author:
            return False
        index_ids.append(index_id)
        seen.add(index_id)
        if instance:
            instance_counts[instance] = instance_counts.get(instance, 0) + 1
        if author:
            author_counts[author] = author_counts.get(author, 0) + 1
        return True

    def scan_range(range_start: int, range_end: int) -> None:
        """Scan one stable-id window before the final random shuffle."""
        nonlocal scanned
        if range_end < range_start:
            return
        current = range_start
        while current <= range_end and len(index_ids) < target:
            rows = src_db.execute(
                """
                SELECT vii.index_id, v.instance_domain, v.channel_id
                FROM video_index_ids vii
                JOIN video_embeddings e
                  ON e.video_id = vii.video_id AND e.instance_domain = vii.instance_domain
                JOIN videos v
                  ON v.video_id = vii.video_id AND v.instance_domain = vii.instance_domain
                WHERE vii.is_active = 1 AND vii.index_id >= ? AND vii.index_id <= ?
                ORDER BY vii.index_id
                LIMIT ?
                """,
                (current, range_end, chunk_size),
            ).fetchall()
            if not rows:
                break
            scanned += len(rows)
            current = int(rows[-1]["index_id"]) + 1
            for entry in rows:
                if len(index_ids) >= target:
                    break
                try_add(entry)

    scan_range(start_id, max_id)
    if len(index_ids) < target:
        scan_range(min_id, start_id - 1)
    if len(index_ids) < target:
        logging.info("random cache filtered fill short: target=%d got=%d scanned=%d", target, len(index_ids), scanned)
    logging.info(
        "random cache filtered=%s size=%d scanned=%d max_per_instance=%d max_per_author=%d",
        filtered_mode,
        len(index_ids),
        scanned,
        max_per_instance,
        max_per_author,
    )
    random.shuffle(index_ids)
    cache_db.executemany(
        "INSERT INTO random_index_ids (position, index_id) VALUES (?, ?)",
        [(index, index_id) for index, index_id in enumerate(index_ids, start=1)],
    )
    cache_db.commit()
    return len(index_ids)


def _fetch_unfiltered_index_ids(
    src_db: sqlite3.Connection, start_id: int, target: int, *, before_start: bool
) -> list[sqlite3.Row]:
    """Fetch active random-cache candidates from one side of the random start id."""
    comparator = "<" if before_start else ">="
    return src_db.execute(
        f"""
        SELECT vii.index_id
        FROM video_index_ids vii
        JOIN video_embeddings e
          ON e.video_id = vii.video_id AND e.instance_domain = vii.instance_domain
        JOIN videos v
          ON v.video_id = vii.video_id AND v.instance_domain = vii.instance_domain
        WHERE vii.is_active = 1 AND vii.index_id {comparator} ?
        ORDER BY vii.index_id
        LIMIT ?
        """,
        (start_id, target),
    ).fetchall()


def fetch_random_index_ids(cache_db: sqlite3.Connection, limit: int) -> list[int]:
    """Return a finite random window for the legacy recommendation fallback."""
    if limit <= 0:
        return []
    count_row = cache_db.execute("SELECT COUNT(*) FROM random_index_ids").fetchone()
    total = int(count_row[0]) if count_row else 0
    if total <= 0:
        return []
    start = 0 if total <= limit else random.randint(0, total - limit)
    rows = cache_db.execute(
        "SELECT index_id FROM random_index_ids ORDER BY position LIMIT ? OFFSET ?",
        (limit, start),
    ).fetchall()
    return [int(row["index_id"]) for row in rows]
