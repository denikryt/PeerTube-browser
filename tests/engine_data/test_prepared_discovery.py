"""Regression tests for updater-owned prepared Discovery data."""
from __future__ import annotations

import json
import sqlite3

import pytest

from engine.server.data.prepared_discovery import (
    PREPARED_DISCOVERY_SCHEMA_VERSION,
    VideoFacetsUnavailable,
    fetch_prepared_video_facets,
    invalidate_prepared_discovery,
    prepared_discovery_available,
    rebuild_prepared_discovery,
)


def _conn() -> sqlite3.Connection:
    """Create the canonical columns consumed by the prepared Discovery builder."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE videos (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          language TEXT,
          language_label TEXT,
          category TEXT,
          category_id TEXT,
          tags_json TEXT,
          invalid_reason TEXT,
          error_count INTEGER DEFAULT 0,
          channel_id TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE instance_denylist (
          host TEXT PRIMARY KEY,
          is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE channel_moderation (
          channel_id TEXT,
          instance_domain TEXT,
          status TEXT,
          PRIMARY KEY(channel_id, instance_domain)
        );
        """
    )
    return conn


def test_prepared_semantic_version_and_exact_null_source():
    """V1 readiness is rejected; rebuilding v2 excludes empty/unknown reasons, not high errors."""
    conn = _conn()
    for i, reason in enumerate([None, "not_found", "gone", "unknown", "", None]):
        _insert(conn, str(i), invalid_reason=reason, error_count=10 if i == 5 else 0)
    conn.commit()
    stats = rebuild_prepared_discovery(conn)
    assert stats["source_video_count"] == 2
    assert PREPARED_DISCOVERY_SCHEMA_VERSION == 2
    assert prepared_discovery_available(conn)
    conn.execute("UPDATE video_facets_snapshot SET schema_version=1")
    conn.commit()
    assert not prepared_discovery_available(conn)
    with pytest.raises(VideoFacetsUnavailable):
        fetch_prepared_video_facets(conn)
    rebuild_prepared_discovery(conn)
    assert prepared_discovery_available(conn)
    conn.close()


def _insert(
    conn: sqlite3.Connection,
    video_id: str,
    *,
    instance: str = "example.org",
    language: str | None = "en",
    language_label: str | None = "English",
    category: str | None = "Education",
    category_id: str | None = "13",
    tags_json: str | None = '["linux"]',
    invalid_reason: str | None = None,
    error_count: int = 0,
    channel_id: str | None = None,
) -> None:
    """Insert one canonical source row with explicit facet metadata."""
    conn.execute(
        """
        INSERT INTO videos(
          video_id, instance_domain, language, language_label, category,
          category_id, tags_json, invalid_reason, error_count, channel_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            video_id,
            instance,
            language,
            language_label,
            category,
            category_id,
            tags_json,
            invalid_reason,
            error_count,
            channel_id or f"c-{video_id}",
        ),
    )


def test_rebuild_is_self_contained_and_normalizes_tag_membership() -> None:
    """Positive: one rebuild creates its schema and exact normalized memberships from scratch."""
    conn = _conn()
    _insert(conn, "a", tags_json='[" Linux ", "linux", "", 7, null, "Fediverse"]')
    _insert(conn, "b", tags_json="not-json")
    _insert(conn, "c", tags_json='{"tag":"linux"}')
    conn.commit()

    stats = rebuild_prepared_discovery(conn)

    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='video_tags'"
    ).fetchone()[0]
    assert "WITHOUT ROWID" in table_sql.upper()
    assert [tuple(row) for row in conn.execute(
        "SELECT tag, video_id, instance_domain FROM video_tags ORDER BY tag, video_id"
    )] == [
        ("fediverse", "a", "example.org"),
        ("linux", "a", "example.org"),
    ]
    assert stats["source_video_count"] == 3
    assert stats["tag_membership_count"] == 2
    assert prepared_discovery_available(conn) is True


def test_rebuild_excludes_only_invalid_rows_from_facets_not_runtime_policy() -> None:
    """Positive/negative: facet statistics ignore invalid rows but not threshold or moderation state."""
    conn = _conn()
    _insert(conn, "normal", instance="one.example", tags_json='["linux"]')
    _insert(conn, "high-error", instance="two.example", tags_json='["linux"]', error_count=999)
    _insert(conn, "denied", instance="blocked.example", tags_json='["hidden"]')
    _insert(conn, "blocked-channel", instance="three.example", tags_json='["blocked"]', channel_id="blocked-c")
    _insert(conn, "invalid", instance="invalid.example", tags_json='["invalid"]', invalid_reason="deleted")
    conn.execute("INSERT INTO instance_denylist(host,is_active) VALUES ('blocked.example',1)")
    conn.execute(
        "INSERT INTO channel_moderation(channel_id,instance_domain,status) VALUES ('blocked-c','three.example','blocked')"
    )
    conn.commit()

    rebuild_prepared_discovery(conn)
    payload = fetch_prepared_video_facets(conn)

    assert payload["coverage"]["language"]["total"] == 4
    instances = {row["value"] for row in payload["instances"]}
    assert {"one.example", "two.example", "blocked.example", "three.example"}.issubset(instances)
    assert "invalid.example" not in instances
    tags = {row["value"]: row["count"] for row in payload["tags"]}
    assert tags == {"linux": 2, "blocked": 1, "hidden": 1}
    assert "error_threshold" not in json.dumps(payload)


def test_rebuild_empty_corpus_publishes_valid_empty_snapshot() -> None:
    """Positive boundary: an empty canonical corpus is available, not an unavailable artifact."""
    conn = _conn()

    stats = rebuild_prepared_discovery(conn)
    payload = fetch_prepared_video_facets(conn)

    assert stats == {
        "source_video_count": 0,
        "tag_membership_count": 0,
        "language_count": 0,
        "category_count": 0,
        "tag_count": 0,
        "instance_count": 0,
    }
    assert payload["languages"] == []
    assert payload["categories"] == []
    assert payload["tags"] == []
    assert payload["instances"] == []
    assert payload["coverage"]["language"] == {
        "known": 0,
        "unknown": 0,
        "total": 0,
        "ratio": 0.0,
    }


def test_failed_rebuild_rolls_back_new_tags_and_preserves_prior_snapshot() -> None:
    """Negative: snapshot publication failure rolls back the whole prepared rebuild transaction."""
    conn = _conn()
    _insert(conn, "a", tags_json='["old"]')
    conn.commit()
    rebuild_prepared_discovery(conn)
    previous_payload = fetch_prepared_video_facets(conn)
    previous_tags = [tuple(row) for row in conn.execute("SELECT * FROM video_tags")]

    conn.execute("UPDATE videos SET tags_json='[\"new\"]' WHERE video_id='a'")
    conn.execute(
        """
        CREATE TRIGGER fail_snapshot_publish
        BEFORE INSERT ON video_facets_snapshot
        BEGIN
          SELECT RAISE(ABORT, 'injected snapshot failure');
        END
        """
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="snapshot failure"):
        rebuild_prepared_discovery(conn)

    assert [tuple(row) for row in conn.execute("SELECT * FROM video_tags")] == previous_tags
    assert fetch_prepared_video_facets(conn) == previous_payload


def test_invalidation_is_idempotent_and_availability_rejects_corrupt_state() -> None:
    """Positive/negative: readiness is only a valid singleton with current schema and payload shape."""
    conn = _conn()
    _insert(conn, "a")
    conn.commit()
    rebuild_prepared_discovery(conn)
    assert prepared_discovery_available(conn) is True
    assert fetch_prepared_video_facets(conn)["meta"] == {
        "dynamic": False,
        "tag_limit": 100,
        "instance_limit": 100,
    }

    invalidate_prepared_discovery(conn)
    invalidate_prepared_discovery(conn)
    conn.commit()
    assert prepared_discovery_available(conn) is False
    with pytest.raises(VideoFacetsUnavailable):
        fetch_prepared_video_facets(conn)

    rebuild_prepared_discovery(conn)
    payload = fetch_prepared_video_facets(conn)
    payload["meta"]["tag_limit"] = 99
    conn.execute(
        "UPDATE video_facets_snapshot SET payload_json=? WHERE snapshot_id=1",
        (json.dumps(payload),),
    )
    conn.commit()
    assert prepared_discovery_available(conn) is False
    with pytest.raises(VideoFacetsUnavailable):
        fetch_prepared_video_facets(conn)

    rebuild_prepared_discovery(conn)
    conn.execute(
        "UPDATE video_facets_snapshot SET schema_version=?",
        (PREPARED_DISCOVERY_SCHEMA_VERSION + 1,),
    )
    conn.commit()
    assert prepared_discovery_available(conn) is False
    with pytest.raises(VideoFacetsUnavailable):
        fetch_prepared_video_facets(conn)

    conn.execute(
        "UPDATE video_facets_snapshot SET schema_version=?, payload_json='{}'",
        (PREPARED_DISCOVERY_SCHEMA_VERSION,),
    )
    conn.commit()
    assert prepared_discovery_available(conn) is False
    with pytest.raises(VideoFacetsUnavailable):
        fetch_prepared_video_facets(conn)


def _create_purge_fixture(conn: sqlite3.Connection) -> None:
    """Create canonical rows needed to test host-purge prepared-state invalidation."""
    conn.executescript(
        """
        CREATE TABLE videos(
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          channel_id TEXT,
          language TEXT,
          language_label TEXT,
          category TEXT,
          category_id TEXT,
          tags_json TEXT,
          invalid_reason TEXT,
          PRIMARY KEY(video_id, instance_domain)
        );
        CREATE TABLE channels(
          channel_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          PRIMARY KEY(channel_id, instance_domain)
        );
        CREATE TABLE instances(host TEXT PRIMARY KEY);
        INSERT INTO videos VALUES(
          'v1','purge.example','c1','en','English','Education','13','["linux"]',''
        );
        INSERT INTO channels VALUES('c1','purge.example');
        INSERT INTO instances VALUES('purge.example');
        """
    )
    rebuild_prepared_discovery(conn)


def test_host_purge_invalidates_prepared_discovery_when_videos_are_deleted() -> None:
    """A committed canonical video purge must make the old prepared snapshot unavailable."""
    from engine.server.data.moderation import purge_host_data

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_purge_fixture(conn)
    assert prepared_discovery_available(conn) is True

    counts = purge_host_data(conn, "purge.example", dry_run=False)

    assert counts["videos"] == 1
    assert prepared_discovery_available(conn) is False
    assert conn.execute("SELECT COUNT(*) FROM video_tags").fetchone()[0] == 1


def test_host_purge_dry_run_or_noop_keeps_prepared_discovery_ready() -> None:
    """Planning or purging a host with no videos must not invalidate a valid snapshot."""
    from engine.server.data.moderation import purge_host_data

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_purge_fixture(conn)

    dry_counts = purge_host_data(conn, "purge.example", dry_run=True)
    noop_counts = purge_host_data(conn, "missing.example", dry_run=False)

    assert dry_counts["videos"] == 1
    assert noop_counts.get("videos", 0) == 0
    assert prepared_discovery_available(conn) is True


def test_rebuild_discovery_cli_builds_fresh_artifacts_and_reports_failure(tmp_path) -> None:
    """The standalone job is self-contained on a valid DB and non-zero on invalid input."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    job = root / "engine/server/db/jobs/rebuild-video-discovery-data.py"
    good_db = tmp_path / "good.db"
    bad_db = tmp_path / "bad.db"
    with sqlite3.connect(good_db) as conn:
        conn.execute(
            """
            CREATE TABLE videos(
              video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, channel_id TEXT,
              language TEXT, language_label TEXT, category TEXT, category_id TEXT,
              tags_json TEXT, invalid_reason TEXT, error_count INTEGER DEFAULT 0,
              PRIMARY KEY(video_id, instance_domain)
            )
            """
        )
        conn.execute(
            "INSERT INTO videos VALUES('v1','one.example','c1','en','English','Education','13','[\"linux\"]','',0)"
        )
        conn.commit()
    sqlite3.connect(bad_db).close()

    good = subprocess.run(
        [sys.executable, str(job), "--db", str(good_db)],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    bad = subprocess.run(
        [sys.executable, str(job), "--db", str(bad_db)],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert good.returncode == 0, good.stderr
    with sqlite3.connect(good_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM video_tags").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM video_facets_snapshot").fetchone()[0] == 1
    assert bad.returncode != 0


def test_host_purge_invalidates_from_actual_video_delete_even_if_precheck_was_stale() -> None:
    """Positive: actual video DELETE is authoritative even when supplied pre-count says zero."""
    from engine.server.data.moderation import purge_host_data

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_purge_fixture(conn)

    purge_host_data(
        conn,
        "purge.example",
        dry_run=False,
        precomputed_counts={"videos": 0},
    )

    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
    assert prepared_discovery_available(conn) is False


def test_host_purge_does_not_invalidate_when_stale_precheck_claims_video_but_delete_is_noop() -> None:
    """Negative: an inaccurate positive pre-count cannot invalidate when no video row changed."""
    from engine.server.data.moderation import purge_host_data

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_purge_fixture(conn)

    purge_host_data(
        conn,
        "missing.example",
        dry_run=False,
        precomputed_counts={"videos": 1},
    )

    assert prepared_discovery_available(conn) is True


def _load_rebuild_discovery_job():
    """Load the standalone prepared-Discovery job for lifecycle tests."""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    path = root / "engine/server/db/jobs/rebuild-video-discovery-data.py"
    spec = importlib.util.spec_from_file_location("rebuild_video_discovery_data_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rebuild_discovery_job_runs_optimize_only_after_success(monkeypatch, tmp_path) -> None:
    """Positive: standalone successful rebuild reaches its natural planner-maintenance point."""
    from types import SimpleNamespace

    mod = _load_rebuild_discovery_job()
    db_path = tmp_path / "optimize.db"
    seen: list[str] = []

    class RecordingConnection(sqlite3.Connection):
        """Record SQL while executing against a real SQLite connection."""

        def execute(self, sql: str, parameters=(), /):  # type: ignore[override]
            seen.append(sql.strip())
            return super().execute(sql, parameters)

    conn = sqlite3.connect(db_path, factory=RecordingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE videos(
          video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, channel_id TEXT,
          language TEXT, language_label TEXT, category TEXT, category_id TEXT,
          tags_json TEXT, invalid_reason TEXT, error_count INTEGER DEFAULT 0,
          PRIMARY KEY(video_id, instance_domain)
        )
        """
    )
    conn.commit()
    monkeypatch.setattr(mod, "parse_args", lambda: SimpleNamespace(db=str(db_path)))
    monkeypatch.setattr(mod, "connect_db", lambda _path: conn)

    mod.main()

    assert "PRAGMA optimize" in seen


def test_rebuild_discovery_job_does_not_optimize_after_failed_rebuild(monkeypatch, tmp_path) -> None:
    """Negative: planner maintenance cannot mask or follow a failed prepared rebuild."""
    from types import SimpleNamespace

    mod = _load_rebuild_discovery_job()
    db_path = tmp_path / "failed-optimize.db"
    seen: list[str] = []

    class RecordingConnection(sqlite3.Connection):
        """Record SQL so the failure path can prove optimize was not reached."""

        def execute(self, sql: str, parameters=(), /):  # type: ignore[override]
            seen.append(sql.strip())
            return super().execute(sql, parameters)

    conn = sqlite3.connect(db_path, factory=RecordingConnection)
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(mod, "parse_args", lambda: SimpleNamespace(db=str(db_path)))
    monkeypatch.setattr(mod, "connect_db", lambda _path: conn)
    monkeypatch.setattr(
        mod,
        "rebuild_prepared_discovery",
        lambda _conn: (_ for _ in ()).throw(RuntimeError("rebuild failed")),
    )

    with pytest.raises(RuntimeError, match="rebuild failed"):
        mod.main()

    assert "PRAGMA optimize" not in seen
