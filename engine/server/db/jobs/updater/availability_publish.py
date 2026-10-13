"""Offline publication of validated existing-video observations into canonical state.

The caller must quiesce production writers. Evidence is attached read-only;
unknown observations never authorize changes, and diagnostics/metadata/stable
identities are never copied. Canonical changes and Prepared invalidation commit
in one production transaction, with no network or staging writes.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    from engine.server.data.prepared_discovery import invalidate_prepared_discovery
except ModuleNotFoundError:  # pragma: no cover - direct updater executable.
    from data.prepared_discovery import invalidate_prepared_discovery

from .staging import inspect_video_availability_work


@dataclass(frozen=True)
class AvailabilityPublicationSummary:
    """Committed outcome counts and disjoint publication buckets for one sweep."""

    selected_videos: int
    available: int
    not_found: int
    gone: int
    unknown: int
    eligible_observations: int
    applied_available: int
    applied_absent: int
    unchanged: int
    skipped_missing: int
    skipped_denied: int
    skipped_noncanonical_reason: int


# One classification definition drives independent aggregates and stale checking.
# Exact source PK validation makes the join unique; domain identity is byte exact.
_CLASSIFIED = """
WITH classified AS (
 SELECT w.outcome, w.checked_at, v.invalid_reason, v.invalid_at,
   CASE
     WHEN v.video_id IS NULL THEN 'skipped_missing'
     WHEN EXISTS (SELECT 1 FROM main.instance_denylist d
        WHERE d.is_active=1 AND lower(trim(d.host))=lower(trim(v.instance_domain)))
       THEN 'skipped_denied'
     WHEN v.invalid_reason IS NOT NULL AND v.invalid_reason NOT IN ('not_found','gone')
       THEN 'skipped_noncanonical_reason'
     WHEN v.invalid_reason IS (CASE WHEN w.outcome='available' THEN NULL ELSE w.outcome END)
      AND v.invalid_at IS (CASE WHEN w.outcome='available' THEN NULL ELSE w.checked_at END)
       THEN 'unchanged'
     ELSE 'to_update'
   END AS bucket
 FROM evidence.video_availability_work w
 LEFT JOIN main.videos v ON v.video_id=w.video_id AND v.instance_domain=w.instance_domain
 WHERE w.outcome IN ('available','not_found','gone')
)
"""
_UPDATE = """
UPDATE main.videos AS v
SET invalid_reason=CASE WHEN w.outcome='available' THEN NULL ELSE w.outcome END,
    invalid_at=CASE WHEN w.outcome='available' THEN NULL ELSE w.checked_at END
FROM evidence.video_availability_work AS w
WHERE v.video_id=w.video_id AND v.instance_domain=w.instance_domain
  AND v.video_uuid=w.video_uuid
  AND w.outcome IN ('available','not_found','gone')
  AND (v.invalid_reason IS NULL OR v.invalid_reason IN ('not_found','gone'))
  AND NOT EXISTS (SELECT 1 FROM main.instance_denylist d WHERE d.is_active=1
    AND lower(trim(d.host))=lower(trim(v.instance_domain)))
  AND NOT (v.invalid_reason IS (CASE WHEN w.outcome='available' THEN NULL ELSE w.outcome END)
       AND v.invalid_at IS (CASE WHEN w.outcome='available' THEN NULL ELSE w.checked_at END))
"""


def publish_existing_video_availability(
    prod_db: Path, staging_db: Path, *, sweep_report: dict[str, int]
) -> AvailabilityPublicationSummary:
    """Publish only this invocation's completed evidence, atomically or fail closed.

    Exact PK+UUID and canonical timestamp validation precede bucket assignment.
    Only real changes undergo stale checking. Metadata last_checked_at is neither
    availability authority nor a write target, even after a successful refresh.
    The result and success log exist only after the durable canonical commit.
    """
    if sqlite3.sqlite_version_info < (3, 33, 0):
        raise RuntimeError("Availability publication requires SQLite >= 3.33.0 (UPDATE FROM)")
    conn = sqlite3.connect(prod_db.resolve().as_uri() + "?mode=rw", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("ATTACH DATABASE ? AS evidence", (staging_db.resolve().as_uri() + "?mode=ro",))
        conn.execute("BEGIN IMMEDIATE")
        evidence = inspect_video_availability_work(conn, "evidence")
        fields = (
            "selected_videos",
            "available",
            "not_found",
            "gone",
            "unknown",
            "video_requests_attempted",
        )
        if any(
            type(sweep_report.get(k)) is not int or sweep_report[k] != evidence[k] for k in fields
        ):
            raise RuntimeError("Availability evidence disagrees with current sweep report")
        # Unknown is excluded from authority. For every matched eligible identity,
        # UUID drift is fatal even on a no-op/denied row, not a missing identity.
        bad = conn.execute("""SELECT 1 FROM evidence.video_availability_work w
          JOIN main.videos v ON v.video_id=w.video_id AND v.instance_domain=w.instance_domain
          WHERE w.outcome IN ('available','not_found','gone') AND v.video_uuid IS NOT w.video_uuid
          LIMIT 1""").fetchone()
        if bad:
            raise RuntimeError("Availability publication UUID identity mismatch")
        bad = conn.execute("""SELECT 1 FROM evidence.video_availability_work w
          JOIN main.videos v ON v.video_id=w.video_id AND v.instance_domain=w.instance_domain
          WHERE w.outcome IN ('available','not_found','gone')
            AND (v.invalid_reason IS NULL OR v.invalid_reason IN ('not_found','gone'))
            AND v.invalid_at IS NOT NULL AND typeof(v.invalid_at) != 'integer'
          LIMIT 1""").fetchone()
        if bad:
            raise RuntimeError("Availability publication invalid canonical invalid_at type")
        counts = dict(
            conn.execute(
                _CLASSIFIED
                + """SELECT
          COUNT(*) AS eligible_observations,
          COUNT(*) FILTER (WHERE bucket='to_update' AND outcome='available') AS applied_available,
          COUNT(*) FILTER (WHERE bucket='to_update' AND outcome!='available') AS applied_absent,
          COUNT(*) FILTER (WHERE bucket='unchanged') AS unchanged,
          COUNT(*) FILTER (WHERE bucket='skipped_missing') AS skipped_missing,
          COUNT(*) FILTER (WHERE bucket='skipped_denied') AS skipped_denied,
          COUNT(*) FILTER (WHERE bucket='skipped_noncanonical_reason')
            AS skipped_noncanonical_reason
          FROM classified"""
            ).fetchone()
        )
        if counts["eligible_observations"] != sum(
            v for k, v in counts.items() if k != "eligible_observations"
        ):
            raise RuntimeError("Availability publication bucket accounting mismatch")
        # A stale no-op does not conflict. More recent canonical negatives, or
        # contradictory negatives at one time, abort the whole changing batch.
        stale = conn.execute(
            _CLASSIFIED
            + """SELECT 1 FROM classified WHERE bucket='to_update'
          AND (invalid_at > checked_at OR (invalid_at=checked_at
            AND invalid_reason IN ('not_found','gone') AND outcome IN ('not_found','gone')
            AND invalid_reason != outcome)) LIMIT 1"""
        ).fetchone()
        if stale:
            raise RuntimeError("Availability publication stale canonical evidence conflict")
        conn.execute(_UPDATE)
        # Read changes immediately: readiness DELETE must not overwrite its count.
        changed = conn.execute("SELECT changes()").fetchone()[0]
        if changed != counts["applied_available"] + counts["applied_absent"]:
            raise RuntimeError("Availability publication UPDATE count mismatch")
        if changed:
            invalidate_prepared_discovery(conn)
        summary = AvailabilityPublicationSummary(
            **{
                k: evidence[k]
                for k in ("selected_videos", "available", "not_found", "gone", "unknown")
            },
            **counts,
        )
        conn.commit()
        conn.execute("DETACH DATABASE evidence")
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    logging.info("video_availability_publication %s", json.dumps(asdict(summary), sort_keys=True))
    return summary
