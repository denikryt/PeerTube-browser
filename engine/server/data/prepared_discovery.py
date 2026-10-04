"""Build and read updater-owned prepared Discovery data in the canonical SQLite DB.

The module owns only the normalized tag-membership relation and the singleton
facet snapshot.  Runtime request paths are read-only; data-build/updater paths
replace both artifacts atomically and use the singleton as a narrow readiness
marker for this prepared Discovery unit.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from typing import Any

from .video_filters import UNKNOWN_LANGUAGE

# Version 2 changes source eligibility: every non-NULL reason is excluded.
PREPARED_DISCOVERY_SCHEMA_VERSION = 2
TAG_LIMIT = 100
INSTANCE_LIMIT = 100


class VideoFacetsUnavailable(RuntimeError):
    """Report a missing or incompatible prepared facet snapshot."""


def ensure_prepared_discovery_schema(conn: sqlite3.Connection) -> None:
    """Ensure the two prepared Discovery tables without committing the caller transaction."""
    # Use individual execute() calls: rebuild owns the surrounding explicit
    # transaction and must not invoke executescript() with its commit semantics.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_tags (
          tag TEXT NOT NULL,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          PRIMARY KEY (tag, video_id, instance_domain)
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_facets_snapshot (
          snapshot_id INTEGER PRIMARY KEY CHECK (snapshot_id = 1),
          schema_version INTEGER NOT NULL,
          built_at INTEGER NOT NULL,
          source_video_count INTEGER NOT NULL,
          payload_json TEXT NOT NULL
        )
        """
    )


def invalidate_prepared_discovery(conn: sqlite3.Connection) -> None:
    """Delete the narrow prepared-Discovery readiness marker if its table exists.

    Callers must execute this inside the same transaction as a canonical
    mutation that actually changes prepared-Discovery source rows.  The tag
    relation is deliberately retained until the mandatory full rebuild.
    """
    if not _table_exists(conn, "video_facets_snapshot"):
        return
    conn.execute("DELETE FROM video_facets_snapshot WHERE snapshot_id = 1")


def prepared_discovery_available(conn: sqlite3.Connection) -> bool:
    """Return whether both prepared tables and one structurally valid snapshot are present."""
    if not _table_exists(conn, "video_tags") or not _table_exists(
        conn, "video_facets_snapshot"
    ):
        return False
    try:
        _read_snapshot(conn)
    except (sqlite3.Error, VideoFacetsUnavailable):
        return False
    return True


def rebuild_prepared_discovery(conn: sqlite3.Connection) -> dict[str, int]:
    """Atomically rebuild normalized tag membership and the facet snapshot from canonical videos.

    The function is self-contained: it creates its own prepared tables inside
    the explicit transaction, replaces all tag memberships, computes the facet
    payload from the new relation, and writes the singleton snapshot last.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        ensure_prepared_discovery_schema(conn)
        conn.execute("DELETE FROM video_tags")
        # json_each is intentional here: this is one offline set operation, not
        # a request-path scan.  The nested CASE prevents malformed/scalar JSON
        # from ever reaching json_each(), while DISTINCT expresses normalized
        # per-video membership deduplication before the PK enforces identity.
        conn.execute(
            """
            INSERT INTO video_tags(tag, video_id, instance_domain)
            SELECT DISTINCT
                   lower(trim(CAST(j.value AS TEXT))) AS tag,
                   v.video_id,
                   v.instance_domain
            FROM videos AS v
            JOIN json_each(
                CASE
                    WHEN json_valid(v.tags_json) THEN
                        CASE
                            WHEN json_type(v.tags_json) = 'array' THEN v.tags_json
                            ELSE '[]'
                        END
                    ELSE '[]'
                END
            ) AS j
            WHERE j.type = 'text'
              AND trim(CAST(j.value AS TEXT)) <> ''
            """
        )

        payload, source_video_count = _build_facets_payload(conn)
        _validate_payload(payload)
        tag_membership_count = int(
            conn.execute("SELECT COUNT(*) FROM video_tags").fetchone()[0]
        )
        built_at = int(time.time() * 1000)
        # The singleton is the commit marker for this narrow prepared unit and
        # is therefore written only after tags and payload validation succeed.
        conn.execute(
            """
            INSERT OR REPLACE INTO video_facets_snapshot(
              snapshot_id, schema_version, built_at, source_video_count, payload_json
            ) VALUES (1, ?, ?, ?, ?)
            """,
            (
                PREPARED_DISCOVERY_SCHEMA_VERSION,
                built_at,
                source_video_count,
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "source_video_count": source_video_count,
        "tag_membership_count": tag_membership_count,
        "language_count": len(payload["languages"]),
        "category_count": len(payload["categories"]),
        "tag_count": len(payload["tags"]),
        "instance_count": len(payload["instances"]),
    }


def fetch_prepared_video_facets(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return the prepared facet payload or raise a controlled unavailability error."""
    try:
        return _read_snapshot(conn)
    except sqlite3.Error as exc:
        raise VideoFacetsUnavailable("Prepared video facets are unavailable") from exc


def _build_facets_payload(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
    """Compute canonical metadata statistics using only the stable invalid-row exclusion."""
    eligible = "v.invalid_reason IS NULL"
    language_rows = conn.execute(
        f"""
        SELECT
          CASE
            WHEN v.language IS NULL OR trim(v.language) = '' THEN ?
            ELSE lower(trim(v.language))
          END AS value,
          CASE
            WHEN v.language IS NULL OR trim(v.language) = '' THEN 'Unknown'
            ELSE COALESCE(NULLIF(trim(MIN(v.language_label)), ''), lower(trim(v.language)))
          END AS label,
          COUNT(*) AS count
        FROM videos AS v
        WHERE {eligible}
        GROUP BY value
        ORDER BY count DESC, value ASC
        """,
        (UNKNOWN_LANGUAGE,),
    ).fetchall()
    category_rows = conn.execute(
        f"""
        WITH grouped AS (
          SELECT
            lower(trim(v.category)) AS normalized_value,
            MIN(trim(v.category)) AS value,
            COUNT(*) AS count,
            COUNT(DISTINCT CASE
              WHEN v.category_id IS NOT NULL AND trim(v.category_id) <> ''
              THEN trim(v.category_id)
            END) AS id_count,
            MIN(CASE
              WHEN v.category_id IS NOT NULL AND trim(v.category_id) <> ''
              THEN trim(v.category_id)
            END) AS only_id
          FROM videos AS v
          WHERE {eligible}
            AND v.category IS NOT NULL
            AND trim(v.category) <> ''
          GROUP BY lower(trim(v.category))
        )
        SELECT value,
               CASE WHEN id_count = 1 THEN only_id ELSE NULL END AS category_id,
               count
        FROM grouped
        ORDER BY count DESC, lower(value) ASC
        """
    ).fetchall()
    tag_rows = conn.execute(
        f"""
        SELECT vt.tag AS value, COUNT(*) AS count
        FROM video_tags AS vt
        JOIN videos AS v
          ON v.video_id = vt.video_id
         AND v.instance_domain = vt.instance_domain
        WHERE {eligible}
        GROUP BY vt.tag
        ORDER BY count DESC, value ASC
        LIMIT ?
        """,
        (TAG_LIMIT,),
    ).fetchall()
    instance_rows = conn.execute(
        f"""
        SELECT lower(trim(v.instance_domain)) AS value, COUNT(*) AS count
        FROM videos AS v
        WHERE {eligible}
          AND trim(v.instance_domain) <> ''
        GROUP BY lower(trim(v.instance_domain))
        ORDER BY count DESC, value ASC
        LIMIT ?
        """,
        (INSTANCE_LIMIT,),
    ).fetchall()

    source_video_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM videos AS v WHERE v.invalid_reason IS NULL"
        ).fetchone()[0]
    )
    unknown = sum(
        int(row["count"])
        for row in language_rows
        if row["value"] == UNKNOWN_LANGUAGE
    )
    known = source_video_count - unknown
    payload: dict[str, Any] = {
        "languages": [dict(row) for row in language_rows],
        "categories": [dict(row) for row in category_rows],
        "tags": [dict(row) for row in tag_rows],
        "instances": [dict(row) for row in instance_rows],
        "coverage": {
            "language": {
                "known": known,
                "unknown": unknown,
                "total": source_video_count,
                "ratio": (known / source_video_count) if source_video_count else 0.0,
            }
        },
        "meta": {
            "dynamic": False,
            "tag_limit": TAG_LIMIT,
            "instance_limit": INSTANCE_LIMIT,
        },
    }
    return payload, source_video_count


def _read_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    """Read and validate exactly one current-version singleton snapshot."""
    row = conn.execute(
        """
        SELECT schema_version, payload_json
        FROM video_facets_snapshot
        WHERE snapshot_id = 1
        """
    ).fetchone()
    if row is None:
        raise VideoFacetsUnavailable("Prepared video facets are unavailable")
    try:
        schema_version = int(row["schema_version"])
    except (TypeError, ValueError, IndexError) as exc:
        raise VideoFacetsUnavailable("Prepared video facets are incompatible") from exc
    if schema_version != PREPARED_DISCOVERY_SCHEMA_VERSION:
        raise VideoFacetsUnavailable("Prepared video facets are incompatible")
    try:
        payload = json.loads(str(row["payload_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VideoFacetsUnavailable("Prepared video facets are corrupt") from exc
    try:
        _validate_payload(payload)
    except ValueError as exc:
        raise VideoFacetsUnavailable("Prepared video facets are corrupt") from exc
    return payload


def _validate_payload(payload: Any) -> None:
    """Validate the stable facet payload shape at the artifact read/publication boundary."""
    if not isinstance(payload, dict):
        raise ValueError("facet payload must be an object")
    if set(payload) != {"languages", "categories", "tags", "instances", "coverage", "meta"}:
        raise ValueError("facet payload keys are incompatible")
    _validate_count_rows(payload["languages"], require_label=True)
    _validate_category_rows(payload["categories"])
    _validate_count_rows(payload["tags"])
    _validate_count_rows(payload["instances"])

    coverage = payload["coverage"]
    if not isinstance(coverage, dict) or set(coverage) != {"language"}:
        raise ValueError("facet coverage is incompatible")
    language = coverage["language"]
    if not isinstance(language, dict) or set(language) != {"known", "unknown", "total", "ratio"}:
        raise ValueError("language coverage is incompatible")
    for key in ("known", "unknown", "total"):
        if type(language[key]) is not int or language[key] < 0:
            raise ValueError("language coverage count is invalid")
    ratio = language["ratio"]
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
        raise ValueError("language coverage ratio is invalid")
    if not math.isfinite(float(ratio)) or not 0.0 <= float(ratio) <= 1.0:
        raise ValueError("language coverage ratio is invalid")
    if language["known"] + language["unknown"] != language["total"]:
        raise ValueError("language coverage counts disagree")

    expected_meta = {
        "dynamic": False,
        "tag_limit": TAG_LIMIT,
        "instance_limit": INSTANCE_LIMIT,
    }
    if payload["meta"] != expected_meta:
        raise ValueError("facet metadata is incompatible")


def _validate_count_rows(rows: Any, *, require_label: bool = False) -> None:
    """Validate normalized value/count rows used by language/tag/instance facets."""
    if not isinstance(rows, list):
        raise ValueError("facet rows must be a list")
    expected = {"value", "count"}
    if require_label:
        expected.add("label")
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected:
            raise ValueError("facet row shape is invalid")
        if not isinstance(row["value"], str) or not row["value"]:
            raise ValueError("facet value is invalid")
        if require_label and (not isinstance(row["label"], str) or not row["label"]):
            raise ValueError("facet label is invalid")
        if type(row["count"]) is not int or row["count"] < 0:
            raise ValueError("facet count is invalid")


def _validate_category_rows(rows: Any) -> None:
    """Validate category rows while allowing an intentionally ambiguous null category id."""
    if not isinstance(rows, list):
        raise ValueError("category rows must be a list")
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"value", "category_id", "count"}:
            raise ValueError("category row shape is invalid")
        if not isinstance(row["value"], str) or not row["value"]:
            raise ValueError("category value is invalid")
        category_id = row["category_id"]
        if category_id is not None and not isinstance(category_id, str):
            raise ValueError("category id is invalid")
        if type(row["count"]) is not int or row["count"] < 0:
            raise ValueError("category count is invalid")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Return whether one prepared table exists in the main canonical schema."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone() is not None
