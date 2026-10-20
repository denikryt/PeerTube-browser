"""Real SQLite evidence-to-canonical publication, counters and atomic failures."""

import logging
import sqlite3
from dataclasses import asdict
from pathlib import Path

import pytest

from engine.server.db.jobs.updater import availability_publish as publisher
from engine.server.db.jobs.updater import staging

SCHEMA = Path(__file__).resolve().parents[2] / "engine/crawler/schema.sql"


@pytest.fixture
def corpus(tmp_path):
    """Use actual crawler schema and production moderation/readiness artifacts."""
    prod, stage = tmp_path / "prod.db", tmp_path / "stage.db"
    staging.init_staging_db(stage, SCHEMA)
    with sqlite3.connect(prod) as conn:
        conn.executescript(SCHEMA.read_text())
        conn.execute("CREATE TABLE instance_denylist(host TEXT PRIMARY KEY,is_active INTEGER)")
        conn.execute(
            "CREATE TABLE video_facets_snapshot(snapshot_id INTEGER PRIMARY KEY,value TEXT)"
        )
        conn.execute("INSERT INTO video_facets_snapshot VALUES(1,'ready')")
        conn.execute(
            "CREATE TABLE video_index_ids(index_id INTEGER,video_id TEXT,"
            "instance_domain TEXT,is_active INTEGER)"
        )
    return prod, stage


def seed(
    corpus,
    identity="v",
    host="example.org",
    reason=None,
    invalid_at=None,
    outcome="not_found",
    checked=3000,
    error=None,
    last_checked=9000,
):
    """Seed independent current canonical state and completed observation."""
    prod, stage = corpus
    with sqlite3.connect(prod) as conn:
        conn.execute(
            """INSERT INTO videos(video_id,instance_domain,video_uuid,title,tags_json,
          last_checked_at,last_error,last_error_at,error_count,invalid_reason,invalid_at)
          VALUES(?,?,?,'kept','["tag"]',?,'old error',10,2,?,?)""",
            (identity, host, "uuid-" + identity, last_checked, reason, invalid_at),
        )
        conn.execute("INSERT INTO video_index_ids VALUES(?,?,?,1)", (7, identity, host))
    with sqlite3.connect(stage) as conn:
        conn.execute(
            "INSERT INTO video_availability_work VALUES(?,?,?,?,?,?)",
            (identity, host, "uuid-" + identity, outcome, checked, error),
        )


def report(corpus):
    """Read the current run's report before entering the publisher."""
    return staging.video_availability_report(corpus[1], missing_uuid=0)


def rows(prod):
    """Return complete persistent state used to prove rollback and narrow writes."""
    with sqlite3.connect(prod) as conn:
        return tuple(
            conn.execute("SELECT * FROM " + table).fetchall()
            for table in ("videos", "video_index_ids", "video_facets_snapshot")
        )


@pytest.mark.parametrize("reason", [None, "not_found", "gone", "legacy_unknown", ""])
@pytest.mark.parametrize("outcome", ["available", "not_found", "gone", "unknown"])
def test_transition_matrix_preserves_all_other_columns(corpus, reason, outcome, caplog):
    """Only canonical transitions may write, never diagnostics or stable identity."""
    seed(
        corpus,
        reason=reason,
        invalid_at=1000 if reason else None,
        outcome=outcome,
        error="detail: failed" if outcome == "unknown" else None,
    )
    prod, stage = corpus
    before = rows(prod)
    source = stage.read_bytes()
    with caplog.at_level(logging.INFO):
        result = asdict(
            publisher.publish_existing_video_availability(prod, stage, sweep_report=report(corpus))
        )
    after = rows(prod)
    with sqlite3.connect(prod) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(videos)")]
        pair = conn.execute("SELECT invalid_reason,invalid_at FROM videos").fetchone()
    allowed = outcome != "unknown"
    expected = (None, None) if outcome == "available" else (outcome, 3000)
    assert pair == (expected if allowed else (reason, 1000 if reason else None))
    for i, col in enumerate(cols):
        if col not in ("invalid_reason", "invalid_at"):
            assert before[0][0][i] == after[0][0][i]
    assert after[1] == before[1]
    changed = before[0] != after[0]
    assert after[2] == ([] if changed else before[2])
    assert result["eligible_observations"] == sum(
        result[k]
        for k in (
            "applied_available",
            "applied_absent",
            "unchanged",
            "skipped_missing",
            "skipped_denied",
        )
    )
    assert result["applied_available"] + result["applied_absent"] == int(changed)
    assert stage.read_bytes() == source
    assert caplog.text.count("video_availability_publication ") == 1
    # Identical evidence produces no further DML or readiness invalidation.
    with sqlite3.connect(prod) as conn:
        conn.execute("INSERT OR REPLACE INTO video_facets_snapshot VALUES(1,'rebuilt')")
    rerun = publisher.publish_existing_video_availability(prod, stage, sweep_report=report(corpus))
    assert rerun.applied_available + rerun.applied_absent == 0
    assert rows(prod)[2] == [(1, "rebuilt")]


@pytest.mark.parametrize("outcome", ["available", "not_found", "gone"])
def test_missing_denied_and_legacy_buckets(corpus, outcome):
    """Only missing/denied identities skip; legacy availability is authoritative."""
    for identity in ("missing", "denied", "legacy", "live"):
        seed(
            corpus,
            identity=identity,
            outcome=outcome,
            reason="policy" if identity in ("denied", "legacy") else None,
        )
    with sqlite3.connect(corpus[0]) as conn:
        conn.execute("DELETE FROM videos WHERE video_id='missing'")
        conn.execute("UPDATE videos SET instance_domain=' Denied.Org ' WHERE video_id='denied'")
        conn.execute("INSERT INTO instance_denylist VALUES('denied.org',1)")
    with sqlite3.connect(corpus[1]) as conn:
        conn.execute(
            "UPDATE video_availability_work SET instance_domain=' Denied.Org ' "
            "WHERE video_id='denied'"
        )
    result = publisher.publish_existing_video_availability(*corpus, sweep_report=report(corpus))
    assert (result.skipped_missing, result.skipped_denied) == (1, 1)
    # A historical unclassified reason is not a policy authority after ownership cut.
    with sqlite3.connect(corpus[0]) as conn:
        pair = conn.execute("SELECT invalid_reason, invalid_at FROM videos WHERE video_id='legacy'").fetchone()
    assert pair == ((None, None) if outcome == "available" else (outcome, 3000))


@pytest.mark.parametrize(
    "reason,time,outcome,checked,fatal",
    [
        ("gone", 5000, "available", 3000, True),
        ("not_found", 5000, "not_found", 3000, True),
        ("gone", 3000, "not_found", 3000, True),
        ("gone", 3000, "gone", 3000, False),
        (None, None, "available", 3000, False),
        ("gone", 1000, "not_found", 3000, False),
        (None, 1000, "available", 3000, False),
        ("gone", 3000, "available", 3000, False),
    ],
)
def test_canonical_staleness_and_exact_pair_noop(
    corpus, reason, time, outcome, checked, fatal, caplog
):
    """Stale changes roll back independent rows; no-ops are classified first."""
    seed(corpus, reason=reason, invalid_at=time, outcome=outcome, checked=checked)
    seed(corpus, identity="independent", outcome="gone")
    before = rows(corpus[0])
    with caplog.at_level(logging.INFO):
        if fatal:
            with pytest.raises(RuntimeError, match="stale"):
                publisher.publish_existing_video_availability(*corpus, sweep_report=report(corpus))
            assert rows(corpus[0]) == before
            assert "video_availability_publication " not in caplog.text
        else:
            summary = publisher.publish_existing_video_availability(
                *corpus, sweep_report=report(corpus)
            )
            assert summary.applied_absent >= 1


@pytest.mark.parametrize("last_checked", [1000, 9000, "malformed", 3.5])
def test_metadata_timestamp_has_no_availability_authority(corpus, last_checked):
    """Both newer and malformed metadata clocks are preserved, never validated."""
    seed(corpus, last_checked=last_checked)
    seed(corpus, identity="b", outcome="gone")
    result = publisher.publish_existing_video_availability(*corpus, sweep_report=report(corpus))
    assert result.applied_absent == 2
    with sqlite3.connect(corpus[0]) as conn:
        assert conn.execute("SELECT last_checked_at FROM videos WHERE video_id='v'").fetchone() == (
            last_checked,
        )


@pytest.mark.parametrize(
    "corrupt",
    [
        "UPDATE videos SET video_uuid='other'",
        "UPDATE videos SET invalid_at='bad'",
        "DROP TABLE instance_denylist",
    ],
)
def test_production_preflight_fails_before_any_mutation(corpus, corrupt):
    """Identity, timestamp and required moderation table failures are atomic."""
    seed(corpus, outcome="available")
    with sqlite3.connect(corpus[0]) as conn:
        conn.execute(corrupt)
    before = rows(corpus[0])
    with pytest.raises((RuntimeError, sqlite3.Error)):
        publisher.publish_existing_video_availability(*corpus, sweep_report=report(corpus))
    assert rows(corpus[0]) == before


@pytest.mark.parametrize(
    "corrupt",
    [
        "UPDATE crawl_state SET value='standalone' WHERE key='video_corpus_role'",
        "UPDATE crawl_state SET value='old' WHERE key='video_availability_semantics'",
        "DROP INDEX idx_availability_work_host_identity",
        "UPDATE video_availability_work SET outcome=NULL",
        "UPDATE video_availability_work SET checked_at='bad'",
        "UPDATE video_availability_work SET video_uuid=''",
        "UPDATE video_availability_work SET error='unexpected'",
    ],
)
def test_evidence_revalidation_is_readonly_and_atomic(corpus, corrupt):
    """Post-report source drift cannot authorize production publication."""
    seed(corpus)
    original_report = report(corpus)
    with sqlite3.connect(corpus[1]) as conn:
        conn.execute(corrupt)
    before = rows(corpus[0])
    source = corpus[1].read_bytes()
    with pytest.raises((RuntimeError, sqlite3.Error)):
        publisher.publish_existing_video_availability(*corpus, sweep_report=original_report)
    assert rows(corpus[0]) == before and corpus[1].read_bytes() == source


@pytest.mark.parametrize(
    "field",
    ["selected_videos", "available", "not_found", "gone", "unknown", "video_requests_attempted"],
)
def test_report_drift_rejected(corpus, field):
    """The current invocation's validated report is an independent source check."""
    seed(corpus)
    frozen = report(corpus)
    frozen[field] += 1
    before = rows(corpus[0])
    with pytest.raises(RuntimeError, match="report"):
        publisher.publish_existing_video_availability(*corpus, sweep_report=frozen)
    assert rows(corpus[0]) == before


@pytest.mark.parametrize(
    "point", ["update", "before_invalidation", "after_invalidation", "commit", "count"]
)
def test_transaction_failures_roll_back_canonical_and_readiness(corpus, monkeypatch, point, caplog):
    """Failures throughout the sole UPDATE and readiness transaction leave no success."""
    seed(corpus)
    frozen = report(corpus)
    before = rows(corpus[0])
    connect = sqlite3.connect
    if point == "update":
        with connect(corpus[0]) as conn:
            conn.execute(
                "CREATE TRIGGER abort_publish BEFORE UPDATE OF invalid_reason ON videos "
                "BEGIN SELECT RAISE(ABORT,'injected'); END"
            )
    elif point == "count":
        with connect(corpus[0]) as conn:
            conn.execute(
                "CREATE TRIGGER ignore_publish BEFORE UPDATE OF invalid_reason ON videos "
                "BEGIN SELECT RAISE(IGNORE); END"
            )
    elif point in ("before_invalidation", "after_invalidation"):
        original = publisher.invalidate_prepared_discovery

        def broken(conn):
            """Fail before or after the real readiness DELETE within the transaction."""
            if point == "after_invalidation":
                original(conn)
            raise RuntimeError("injected invalidation failure")

        monkeypatch.setattr(publisher, "invalidate_prepared_discovery", broken)
    else:

        class FailedCommit(sqlite3.Connection):
            """Fault at the outer durability boundary, after transactional DML."""

            def commit(self):
                """Raise before durability to exercise rollback after readiness invalidation."""
                raise sqlite3.OperationalError("injected commit failure")

        monkeypatch.setattr(
            publisher.sqlite3, "connect", lambda *a, **kw: connect(*a, **kw, factory=FailedCommit)
        )
    with caplog.at_level(logging.INFO), pytest.raises((RuntimeError, sqlite3.Error)):
        publisher.publish_existing_video_availability(*corpus, sweep_report=frozen)
    assert rows(corpus[0]) == before
    assert "video_availability_publication " not in caplog.text


def test_no_creation_for_missing_databases(tmp_path):
    """Neither the production typo nor absent evidence may create an empty DB."""
    prod, stage = tmp_path / "prod", tmp_path / "stage"
    with pytest.raises(sqlite3.OperationalError):
        publisher.publish_existing_video_availability(prod, stage, sweep_report={})
    assert not prod.exists() and not stage.exists()


def test_case_sensitive_composite_identity(corpus):
    """Same IDs on different domain bytes are separate canonical identities."""
    seed(corpus, host="Example.org")
    seed(corpus, host="example.org", outcome="gone")
    result = publisher.publish_existing_video_availability(*corpus, sweep_report=report(corpus))
    assert result.applied_absent == 2
    with sqlite3.connect(corpus[0]) as conn:
        assert conn.execute(
            "SELECT instance_domain,invalid_reason FROM videos ORDER BY instance_domain"
        ).fetchall() == [("Example.org", "not_found"), ("example.org", "gone")]


def test_large_publication_is_set_based_and_preserves_source(corpus, monkeypatch):
    """100k identities across >999 hosts use indexed joins and one mixed UPDATE."""
    prod, stage = corpus
    identities = [(str(i), f"host{i % 2000}.org", f"uuid-{i}", 1) for i in range(100000)]
    with sqlite3.connect(prod) as conn:
        conn.executemany(
            "INSERT INTO videos(video_id,instance_domain,video_uuid,last_checked_at) "
            "VALUES(?,?,?,?)",
            identities,
        )
    with sqlite3.connect(stage) as conn:
        conn.executemany(
            "INSERT INTO video_availability_work VALUES(?,?,?,?,?,NULL)",
            [
                (id, host, uuid, "available" if int(id) % 2 else "gone", 3000)
                for id, host, uuid, _ in identities
            ],
        )
    frozen = report(corpus)
    source = stage.read_bytes()
    queries = []
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        """Trace SQLite as an outer boundary, preserving real transaction effects."""
        conn = connect(*args, **kwargs)
        conn.set_trace_callback(queries.append)
        return conn

    monkeypatch.setattr(publisher.sqlite3, "connect", traced)
    summary = publisher.publish_existing_video_availability(prod, stage, sweep_report=frozen)
    assert (summary.applied_absent, summary.unchanged) == (50000, 50000)
    assert stage.read_bytes() == source
    updates = [q for q in queries if q.lstrip().upper().startswith("UPDATE MAIN.VIDEOS")]
    assert len(updates) == 1 and "CASE" in updates[0] and "FROM evidence" in updates[0]
    with connect(prod, uri=True) as conn:
        conn.execute("ATTACH DATABASE ? AS evidence", (stage.as_uri() + "?mode=ro",))
        plan = conn.execute(
            "EXPLAIN QUERY PLAN " + publisher._CLASSIFIED + "SELECT * FROM classified"
        ).fetchall()
        assert any("SEARCH v USING INDEX sqlite_autoindex_videos" in r[3] for r in plan)
        assert (
            conn.execute("SELECT COUNT(*) FROM videos WHERE invalid_reason='gone'").fetchone()[0]
            == 50000
        )


def test_empty_completed_work_is_noop(corpus):
    """Valid empty work completes without removing a readiness marker."""
    before = rows(corpus[0])
    summary = publisher.publish_existing_video_availability(*corpus, sweep_report=report(corpus))
    assert summary.selected_videos == 0 and summary.eligible_observations == 0
    assert rows(corpus[0]) == before


def test_legacy_host_preflight_is_not_accepted_as_completed_detail(corpus):
    """Old host-wide evidence without a video request cannot authorize publication."""
    seed(corpus, identity="legacy", checked=None, outcome="unknown", error="host_preflight: network")
    before = rows(corpus[0])
    with pytest.raises(RuntimeError, match="incomplete or inconsistent"):
        report(corpus)
    assert rows(corpus[0]) == before


def test_unknown_detail_is_terminal_but_never_absence_authority(corpus):
    """Attempted detail with a transport failure records unknown, not 404/410."""
    seed(corpus, identity="detail", outcome="unknown", checked=6000, error="detail: network")
    before = rows(corpus[0])
    summary = publisher.publish_existing_video_availability(*corpus, sweep_report=report(corpus))
    assert summary.unknown == 1 and summary.eligible_observations == 0
    assert rows(corpus[0]) == before


def test_absent_evidence_does_not_create_file_or_mutate_production(corpus):
    """Existing production cannot turn a staging typo into a fresh empty source."""
    missing = corpus[1].with_name("missing.db")
    before = rows(corpus[0])
    with pytest.raises(sqlite3.OperationalError):
        publisher.publish_existing_video_availability(corpus[0], missing, sweep_report={})
    assert not missing.exists() and rows(corpus[0]) == before


def test_inspector_aliases_are_bounded_and_leave_connection_state_unchanged(corpus):
    """Attached inspection agrees with standalone reporting without DDL or global row factories."""
    seed(corpus)
    expected = report(corpus)
    with sqlite3.connect(corpus[1]) as conn:
        result = staging.inspect_video_availability_work(conn)
        assert result["selected_videos"] == expected["selected_videos"] and conn.row_factory is None
        with pytest.raises(ValueError):
            staging.inspect_video_availability_work(conn, "main; DELETE FROM videos")
    with sqlite3.connect(corpus[0], uri=True) as conn:
        conn.execute("ATTACH DATABASE ? AS evidence", (corpus[1].as_uri() + "?mode=ro",))
        assert staging.inspect_video_availability_work(conn, "evidence") == result
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM evidence.video_availability_work")
