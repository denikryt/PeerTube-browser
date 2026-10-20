"""Behavior contracts for disposable report-only production observations."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.server.db.jobs.updater import cli, staging

SCHEMA = Path(__file__).resolve().parents[2] / "engine/crawler/schema.sql"


@pytest.fixture
def corpus(tmp_path):
    """Separate production and accepted staging, including ineligible UUIDs."""
    prod, stage = tmp_path / "prod.db", tmp_path / "stage.db"
    staging.init_staging_db(prod, SCHEMA)
    staging.init_staging_db(stage, SCHEMA)
    with sqlite3.connect(prod) as c:
        for i, host, uuid in [
            ("a", " Example.org ", "uuid-a"),
            ("b", "example.org", "uuid-b"),
            ("c", "denied.org", "uuid-c"),
            ("d", "example.org", None),
            ("e", "example.org", "  "),
        ]:
            c.execute(
                "INSERT INTO videos(video_id,instance_domain,video_uuid,last_checked_at) VALUES(?,?,?,0)",
                (i, host, uuid),
            )
        c.execute(
            "UPDATE videos SET invalid_reason='gone',invalid_at=9,error_count=100 WHERE video_id='a'"
        )
        # Production keeps original PK/host spelling, while fresh parent
        # eligibility is resolved against normalized staging host identity.
        c.execute("UPDATE videos SET channel_id='owned'")
    with sqlite3.connect(stage) as c:
        for host in ("example.org", "denied.org"):
            c.execute("INSERT INTO instances(host,health_status,health_checked_at) "
                      "VALUES(?,'ok',123)", (host,))
            c.execute("INSERT INTO channels(channel_id,channel_name,instance_domain,health_status,health_checked_at) "
                      "VALUES('owned','owned',?,'ok',123)", (host,))
            c.execute("INSERT INTO channel_crawl_progress(instance_domain,status,last_start,updated_at) "
                      "VALUES(?,'done',0,123)", (host,))
            c.execute("INSERT INTO crawl_state(key,value) VALUES(?,?)",
                      ("parent_enumeration_v1:" + host, "page_zero_complete_v1"))
        c.execute(
            "INSERT INTO videos(video_id,instance_domain,video_uuid,last_checked_at) VALUES('stage-only','example.org','stage-only',0)"
        )
    return prod, stage


@pytest.mark.parametrize(
    "scope,denied,expected,missing",
    [
        (None, set(), {"a", "b", "c"}, 2),
        ({"example.org"}, set(), {"a", "b"}, 2),
        ({"denied.org"}, {"denied.org"}, set(), 0),
        ({"unmatched.org"}, set(), set(), 0),
        (None, {"denied.org"}, {"a", "b"}, 2),
    ],
)
def test_materialize_production_scope_and_uuid(corpus, scope, denied, expected, missing):
    """Selection retains original identity and never imports staging-only rows."""
    prod, stage = corpus
    with sqlite3.connect(prod) as c:
        before = c.execute("SELECT * FROM videos ORDER BY video_id").fetchall()
    staging.reset_video_availability_work(stage)
    assert (
        staging.materialize_video_availability_work(
            prod, stage, included_hosts=scope, denied_hosts=denied
        )
        == missing
    )
    with sqlite3.connect(stage) as c:
        rows = c.execute(
            "SELECT video_id,instance_domain,outcome,checked_at,error FROM video_availability_work"
        ).fetchall()
        assert {r[0] for r in rows} == expected
        assert all(r[2:] == (None, None, None) for r in rows)
        if "a" in expected:
            assert next(r for r in rows if r[0] == "a")[1] == " Example.org "
    with sqlite3.connect(prod) as c:
        assert c.execute("SELECT * FROM videos ORDER BY video_id").fetchall() == before


@pytest.mark.parametrize("poison", [set(), {None}, {1}, {""}, {" "}, {"Example.org"}])
def test_materialize_rejects_invalid_internal_scope(corpus, poison):
    """Invalid sets cannot become unscoped or poison NOT IN membership."""
    prod, stage = corpus
    staging.reset_video_availability_work(stage)
    with pytest.raises(ValueError):
        staging.materialize_video_availability_work(
            prod, stage, included_hosts=poison, denied_hosts=set()
        )
    with sqlite3.connect(stage) as c:
        assert c.execute("SELECT COUNT(*) FROM video_availability_work").fetchone()[0] == 0


@pytest.mark.parametrize("text", ["", "# only\n", " \n", "...\n"])
def test_explicit_empty_scope_fails_validation(tmp_path, text):
    """Explicit zero host input is rejected before pipeline boundaries."""
    f = tmp_path / "hosts"
    f.write_text(text)
    with pytest.raises(ValueError):
        cli.validate_availability_sweep_mode(
            SimpleNamespace(check_existing_video_availability=True, hosts_file=str(f))
        )


@pytest.mark.parametrize("mode,allowed", [
    ("retry_errors", False), ("sync_join_whitelist", True), ("host_pipeline", True),
])
def test_availability_mode_boundary_matches_parent_lifecycle(mode, allowed):
    """Retry cannot publish; strict sync and host-pipeline run fresh parent checks."""
    args = SimpleNamespace(check_existing_video_availability=True, hosts_file=None, **{mode: True})
    if allowed:
        assert cli.validate_availability_sweep_mode(args) is None
    else:
        with pytest.raises(ValueError, match="retry-errors"):
            cli.validate_availability_sweep_mode(args)
    args.check_existing_video_availability = False
    assert cli.validate_availability_sweep_mode(args) is None


def test_report_requires_one_detail_observation_per_selected_video(corpus):
    """Legacy host-wide skips are rejected; attempted detail unknowns are valid."""
    prod, stage = corpus
    staging.reset_video_availability_work(stage)
    staging.materialize_video_availability_work(
        prod, stage, included_hosts={"example.org"}, denied_hosts=set()
    )
    with pytest.raises(RuntimeError):
        staging.video_availability_report(stage, missing_uuid=2)
    with sqlite3.connect(stage) as c:
        c.execute("UPDATE video_availability_work SET outcome='available',checked_at=123 "
                  "WHERE video_id='a'")
        c.execute("UPDATE video_availability_work SET outcome='unknown',"
                  "error='host_preflight: unavailable' WHERE video_id='b'")
    # A legacy skip never authorizes success, even when all hosts differ.
    with pytest.raises(RuntimeError):
        staging.video_availability_report(stage, missing_uuid=2)
    with sqlite3.connect(stage) as c:
        c.execute("UPDATE video_availability_work SET checked_at=124,"
                  "error='detail: network' WHERE video_id='b'")
    assert staging.video_availability_report(stage, missing_uuid=2) == dict(
        selected_videos=2, available=1, not_found=0, gone=0, unknown=1,
        missing_uuid=2, hosts_processed=1, video_requests_attempted=2,
    )
    staging.reset_video_availability_work(stage)
    assert all(v == 0 for v in staging.video_availability_report(stage, missing_uuid=0).values())


def test_reset_rejects_legacy_shape_without_erasing_evidence(corpus):
    """Incompatible table cannot be silently accepted by IF NOT EXISTS."""
    _, stage = corpus
    with sqlite3.connect(stage) as c:
        c.execute("DROP TABLE IF EXISTS video_availability_work")
        c.execute("CREATE TABLE video_availability_work(video_id TEXT)")
        c.execute("INSERT INTO video_availability_work VALUES('evidence')")
    with pytest.raises(RuntimeError):
        staging.reset_video_availability_work(stage)
    with sqlite3.connect(stage) as c:
        assert c.execute("SELECT * FROM video_availability_work").fetchall() == [("evidence",)]


@pytest.mark.parametrize("composite", [False, True])
def test_large_scope_counts_under_low_bind_limit(tmp_path, monkeypatch, composite):
    """All four diagnostics remain scoped, and hostless embeddings count once."""
    prod, stage = tmp_path / "prod", tmp_path / "stage"
    for p in (prod, stage):
        with sqlite3.connect(p) as c:
            c.executescript(
                "CREATE TABLE instances(host TEXT PRIMARY KEY);"
                "CREATE TABLE channels(channel_id TEXT,instance_domain TEXT,PRIMARY KEY(channel_id,instance_domain));"
                "CREATE TABLE videos(video_id TEXT,instance_domain TEXT,PRIMARY KEY(video_id,instance_domain));"
            )
            c.execute(
                "CREATE TABLE video_embeddings(video_id TEXT"
                + (
                    ",instance_domain TEXT,PRIMARY KEY(video_id,instance_domain))"
                    if composite
                    else " PRIMARY KEY)"
                )
            )
    with sqlite3.connect(stage) as c:
        c.execute("INSERT INTO instances VALUES(' A.example ')")
        c.execute("INSERT INTO channels VALUES('c',' A.example ')")
        c.executemany(
            "INSERT INTO videos VALUES(?,?)",
            [("v", " A.example "), ("v", "b.example"), ("excluded", "excluded.org")],
        )
        c.execute(
            "INSERT INTO video_embeddings VALUES(" + ("?,?" if composite else "?") + ")",
            ("v", " A.example ") if composite else ("v",),
        )
    connect = sqlite3.connect

    def limited(*a, **kw):
        """Set the ceiling on each actual production counter connection."""
        c = connect(*a, **kw)
        c.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
        return c

    monkeypatch.setattr(staging.sqlite3, "connect", limited)
    scope = {"a.example", "b.example"} | {f"host{i}.org" for i in range(1001)}
    assert staging.count_staging_deltas(prod, stage, scope, json_host_scope=True) == dict(
        instances_new=1, channels_new=1, videos_new=2, embeddings_new=1
    )
    assert not any(
        staging.count_staging_deltas(prod, stage, {"unmatched.org"}, json_host_scope=True).values()
    )
    with pytest.raises(sqlite3.OperationalError, match="too many SQL variables"):
        staging.count_staging_deltas(prod, stage, scope)


@pytest.mark.parametrize("edit", ["replace", "truncate", "delete"])
def test_full_pipeline_uses_frozen_scope_through_real_late_counts(
    tmp_path, monkeypatch, caplog, edit
):
    """Operator mutation after snapshot cannot widen selection or break counts."""
    import logging

    from engine.server.db.jobs.updater import pipeline
    from tests.jobs.test_updater_pipeline_commands import _args

    args = _args(
        tmp_path, check_existing_video_availability=True, skip_systemctl=True, use_gpu=False
    )
    (Path(args.crawler_dir) / "schema.sql").write_text(SCHEMA.read_text())
    host_file = tmp_path / "hosts"
    host_file.write_text(" A.example \n" + "\n".join(f"host{i}.org" for i in range(1001)))
    args.hosts_file = str(host_file)
    prod, stage = Path(args.prod_db), Path(args.staging_db)
    # Production video identities are preserved; only freshly checked staged
    # parents authorize existing-video work. All SQLite paths remain real.
    with sqlite3.connect(prod) as c:
        c.executescript(SCHEMA.read_text())
        for i, host in [("a", "a.example"), ("b", "b.example")]:
            c.execute(
                "INSERT INTO videos(video_id,instance_domain,video_uuid,last_checked_at,channel_id) "
                "VALUES(?,?,?,0,'owned')",
                (i, host, "uuid-" + i),
            )
    staging.init_staging_db(stage, SCHEMA)
    monkeypatch.setattr(pipeline, "_prepared_discovery_is_available", lambda p: True)
    commands = []
    snapshots = []
    connect = sqlite3.connect

    def limited(*a, **kw):
        c = connect(*a, **kw)
        c.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
        return c

    monkeypatch.setattr(staging.sqlite3, "connect", limited)

    def runner(cmd, cwd):
        """Fake only subprocess/network/derived boundaries; SQLite effects are real."""
        commands.append(cmd)
        name = Path(cmd[1]).name
        if "--hosts-file" in cmd:
            snapshot = Path(cmd[cmd.index("--hosts-file") + 1])
            snapshots.append((str(snapshot), snapshot.read_text()))
            if len(snapshots) == 1:
                if edit == "delete":
                    host_file.unlink()
                else:
                    host_file.write_text("b.example\n" if edit == "replace" else "# empty\n")
        # Fake only PeerTube network answers, preserving their SQLite effects.
        # The operator file can change after the first discovery request, but
        # that must not admit b.example or alter the current frozen scope.
        if name == "instances-cli.js":
            with connect(stage) as c:
                c.execute("INSERT OR IGNORE INTO instances(host) VALUES('a.example')")
                c.execute("INSERT INTO channels(channel_id,channel_name,instance_domain) "
                          "VALUES('owned','owned','a.example')")
        if name == "channels-cli.js" and "--initialize-only" in cmd:
            with connect(stage) as c:
                c.execute("INSERT INTO channel_crawl_progress(instance_domain,status,last_start,updated_at) "
                          "VALUES('a.example','pending',0,123)")
                c.execute("INSERT INTO crawl_state(key,value) "
                          "VALUES('parent_enumeration_v1:a.example','page_zero_complete_v1')")
        if name == "instances-health-cli.js":
            with connect(stage) as c:
                c.execute("UPDATE instances SET health_status='ok',health_checked_at=123 "
                          "WHERE host='a.example'")
        if name == "channels-cli.js" and "--already-initialized" in cmd:
            with connect(stage) as c:
                c.execute("UPDATE channel_crawl_progress SET status='done' WHERE instance_domain='a.example'")
        if name == "channels-cli.js" and "--check-health" in cmd:
            with connect(stage) as c:
                c.execute("UPDATE channels SET health_status='ok',health_checked_at=123 "
                          "WHERE instance_domain='a.example'")
        if "--check-availability" in cmd:
            with connect(stage) as c:
                assert c.execute("SELECT video_id FROM video_availability_work").fetchall() == [
                    ("a",)
                ]
                c.execute("UPDATE video_availability_work SET outcome='available',checked_at=123")
        if name == "build-video-embeddings.py":
            with connect(stage) as c:
                c.execute("INSERT OR IGNORE INTO instances(host) VALUES('a.example')")

    with caplog.at_level(logging.INFO):
        pipeline.run_pipeline(args, command_runner=runner, validate_files=False)
    # The initial operator snapshot and the later selected-host snapshot have
    # different content, but no stage rereads the mutated operator file.
    assert len(snapshots) == 7
    assert snapshots[0][1].startswith("a.example\n")
    assert "host1000.org" in snapshots[0][1]
    assert all(body == "a.example\n" for _, body in snapshots[1:])
    assert len({path for path, _ in snapshots[1:]}) == 1
    assert "--allow-empty-scoped-whitelist" in commands[0]
    assert all("--allow-empty-scoped-whitelist" not in c for c in commands[1:])
    names = [Path(c[1]).name for c in commands]
    assert names[:8] == [
        "instances-cli.js",
        "channels-cli.js",  # reset
        "instances-health-cli.js",
        "channels-cli.js",  # page-zero enumeration
        "channels-cli.js",  # unresolved health
        "channels-videos-count-cli.js",
        "videos-cli.js",  # new ingest
        "videos-cli.js",  # existing-video detail
    ]
    assert caplog.text.count("video_availability_report ") == 1
    assert "instances=1 channels=1 videos=0 embeddings=0" in caplog.text
    assert not Path(snapshots[0][0]).exists()
    with connect(prod) as c:
        assert c.execute(
            "SELECT video_id,invalid_reason,error_count FROM videos ORDER BY video_id"
        ).fetchall() == [("a", None, 0), ("b", None, 0)]


def test_json_capability_failure_precedes_paths_and_db_mutation(tmp_path, monkeypatch):
    """A missing JSON function cannot be discovered after ordinary crawler HTTP."""
    from engine.server.db.jobs.updater import pipeline
    from tests.jobs.test_updater_pipeline_commands import _args

    args = _args(tmp_path, check_existing_video_availability=True)

    def unavailable():
        raise RuntimeError("SQLite json_each/JSON1 unavailable in updater Python runtime")

    monkeypatch.setattr(staging, "require_sqlite_json_each", unavailable)
    with pytest.raises(RuntimeError, match="json_each"):
        pipeline.run_pipeline(
            args, command_runner=lambda *a: pytest.fail("subprocess ran"), validate_files=False
        )
    assert not Path(args.staging_db).exists()
    args.check_existing_video_availability = False
    assert cli.validate_availability_sweep_mode(args) is None


def test_large_json_selection_uses_shared_uncorrelated_scope(tmp_path, monkeypatch):
    """100k source rows and 20k hosts select exactly the reference predicate."""
    prod, stage = tmp_path / "prod", tmp_path / "stage"
    included = {f"host{i}.org" for i in range(20000)}
    denied = {f"host{i}.org" for i in range(500)}
    rows = [
        (str(i), f" Host{i % 25000}.org ", None if i % 17 == 0 else f"uuid-{i}")
        for i in range(100000)
    ]
    with sqlite3.connect(prod) as c:
        # Existing-video work now needs a production channel identity; the
        # crawler's parent probe owns the corresponding staging eligibility.
        c.execute("CREATE TABLE videos(video_id TEXT,instance_domain TEXT,video_uuid TEXT,channel_id TEXT)")
        c.executemany("INSERT INTO videos VALUES(?,?,?, 'owned')", rows)
    staging.init_staging_db(stage, SCHEMA)
    eligible_hosts = included - denied
    with sqlite3.connect(stage) as c:
        c.executemany(
            "INSERT INTO instances(host,health_status,health_checked_at) VALUES(?,'ok',123)",
            ((host,) for host in sorted(eligible_hosts)),
        )
        c.executemany(
            "INSERT INTO channels(channel_id,channel_name,instance_domain,health_status,health_checked_at) "
            "VALUES('owned','owned',?,'ok',123)",
            ((host,) for host in sorted(eligible_hosts)),
        )
        c.executemany(
            "INSERT INTO channel_crawl_progress(instance_domain,status,last_start,updated_at) "
            "VALUES(?,'done',0,123)",
            ((host,) for host in sorted(eligible_hosts)),
        )
        c.executemany(
            "INSERT INTO crawl_state(key,value) VALUES(?,'page_zero_complete_v1')",
            (("parent_enumeration_v1:" + host,) for host in sorted(eligible_hosts)),
        )
    statements = []
    connect = sqlite3.connect

    def traced(*a, **kw):
        """Record actual materializer statements to verify its read lifecycle."""
        c = connect(*a, **kw)
        c.set_trace_callback(statements.append)
        return c

    monkeypatch.setattr(staging.sqlite3, "connect", traced)
    eligible_hosts = included - denied
    expected = [r for r in rows if r[1].strip().lower() in eligible_hosts]
    assert staging.materialize_video_availability_work(
        prod, stage, included_hosts=included, denied_hosts=denied
    ) == sum(r[2] is None for r in expected)
    with connect(stage, uri=True) as c:
        assert c.execute("SELECT COUNT(*) FROM video_availability_work").fetchone()[0] == sum(
            r[2] is not None for r in expected
        )
        c.execute("ATTACH DATABASE ? AS production", (prod.as_uri() + "?mode=ro",))
        params = dict(
            included_json=__import__("json").dumps(sorted(included)),
            denied_json=__import__("json").dumps(sorted(denied)),
            unscoped=0,
        )
        plan = c.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM production.videos v WHERE 1" + staging.WORK_SCOPE_SQL,
            params,
        ).fetchall()
        # Parent admission is legitimately correlated to a production video.
        # The 20k-host membership check must instead be an uncorrelated
        # json_each list, never 20k SQL parameters or one JSON scan per row.
        assert any("JSON_EACH" in r[3].upper() for r in plan)
        assert not any("CORRELATED LIST SUBQUERY" in r[3].upper() for r in plan)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            c.execute("DELETE FROM production.videos")
    assert not any("TEMP TABLE" in q.upper() for q in statements)
    assert next(q for q in statements if q.startswith("ATTACH")).find("mode=ro") >= 0
    begin = statements.index("BEGIN IMMEDIATE")
    commit = statements.index("COMMIT")
    assert (
        begin
        < next(
            i for i, q in enumerate(statements) if q.startswith("SELECT COUNT(*) FROM production")
        )
        < commit
    )
    assert commit < statements.index("DETACH DATABASE production")
    assert not any(q == "COMMIT" for q in statements[:begin])


@pytest.mark.parametrize(
    "filename,text",
    [("", None), ("missing", None), ("invalid", b"\xff"), ("empty", b""), ("comment", b"# hosts")],
)
def test_cli_and_direct_pipeline_reject_bad_scope_before_effects(tmp_path, filename, text):
    """Both public boundaries reject explicit bad files without starting work."""
    from engine.server.db.jobs.updater import pipeline
    from tests.jobs.test_updater_pipeline_commands import _args

    f = tmp_path / filename
    if text is not None:
        f.write_bytes(text)
    value = str(f) if filename else ""
    with pytest.raises(SystemExit):
        cli.parse_args(
            ["--check-existing-video-availability", "--hosts-file", value, "--service-name", "test"]
        )
    args = _args(tmp_path, check_existing_video_availability=True, hosts_file=value)
    with pytest.raises((ValueError, OSError)):
        pipeline.run_pipeline(
            args, command_runner=lambda *a: pytest.fail("subprocess started"), validate_files=False
        )
    assert not Path(args.staging_db).exists()


@pytest.mark.parametrize("mode,allowed", [
    ("--retry-errors", False), ("--sync-join-whitelist", True), ("--host-pipeline", True),
])
def test_cli_and_direct_pipeline_availability_mode_contract(tmp_path, mode, allowed):
    """The public CLI and direct validator accept the same intended modes."""
    from engine.server.db.jobs.updater import pipeline
    from tests.jobs.test_updater_pipeline_commands import _args

    flags = ["--check-existing-video-availability", mode, "--resume-staging", "--service-name", "test"]
    args = _args(tmp_path, check_existing_video_availability=True, **{mode[2:].replace("-", "_"): True})
    if allowed:
        parsed = cli.parse_args(flags)
        assert getattr(parsed, mode[2:].replace("-", "_")) is True
        assert cli.validate_availability_sweep_mode(args) is None
    else:
        with pytest.raises(SystemExit):
            cli.parse_args(flags)
        with pytest.raises(ValueError, match="retry-errors"):
            pipeline.run_pipeline(args, validate_files=False)
        assert not Path(args.staging_db).exists()


def test_scoped_json_counters_fail_closed_without_host_column(tmp_path):
    """A scoped diagnostic cannot silently broaden to all rows on legacy DDL."""
    with sqlite3.connect(":memory:") as c:
        c.execute("ATTACH ':memory:' AS staging")
        c.execute("CREATE TABLE staging.instances(id TEXT)")
        with pytest.raises(RuntimeError, match="host column"):
            staging._host_scope_sql(
                c, table="instances", alias="s", scoped_hosts={"example.org"}, json_host_scope=True
            )
        assert staging._host_scope_sql(
            c, table="instances", alias="s", scoped_hosts={"example.org"}
        ) == ("", [])


@pytest.mark.parametrize("role", ["standalone", None])
def test_work_reset_rejects_wrong_role_without_mutation(corpus, role):
    """Only updater staging can be ensured/cleared, including flag-disabled runs."""
    _, stage = corpus
    with sqlite3.connect(stage) as c:
        c.execute("DELETE FROM crawl_state WHERE key='video_corpus_role'")
        if role:
            c.execute("INSERT INTO crawl_state VALUES('video_corpus_role',?)", (role,))
        c.execute(
            "INSERT INTO video_availability_work(video_id,instance_domain,video_uuid) VALUES('old','example.org','uuid')"
        )
    with pytest.raises(RuntimeError):
        staging.reset_video_availability_work(stage)
    with sqlite3.connect(stage) as c:
        assert c.execute("SELECT video_id FROM video_availability_work").fetchall() == [("old",)]


def simulate_parent_cli_observation(stage: Path, cmd: list[str]) -> None:
    """Record the parent facts an accepted fake PeerTube probe would persist.

    The Python pipeline still owns selection, reset, materialization and merge;
    only the external Node subprocess's SQLite effects are represented here.
    Old ``done`` alone is never fabricated as current-run evidence.
    """
    if cmd[0] != "node":
        return
    name = Path(cmd[1]).name
    if name not in {"channels-cli.js", "instances-health-cli.js"}:
        return
    with sqlite3.connect(stage) as c:
        if name == "channels-cli.js" and "--initialize-only" in cmd:
            c.execute("INSERT INTO channel_crawl_progress(instance_domain,status,last_start,updated_at) "
                      "VALUES('example.org','pending',0,123) ON CONFLICT(instance_domain) "
                      "DO UPDATE SET status='pending',last_start=0,updated_at=123")
            c.execute("INSERT OR REPLACE INTO crawl_state(key,value) "
                      "VALUES('parent_enumeration_v1:example.org','page_zero_complete_v1')")
            c.execute("UPDATE instances SET health_status=NULL,health_checked_at=NULL,health_error=NULL "
                      "WHERE host='example.org'")
            c.execute("UPDATE channels SET health_status=NULL,health_checked_at=NULL,health_error=NULL "
                      "WHERE instance_domain='example.org'")
        elif name == "instances-health-cli.js":
            c.execute("UPDATE instances SET health_status='ok',health_checked_at=123 "
                      "WHERE host='example.org'")
        elif name == "channels-cli.js" and "--already-initialized" in cmd:
            c.execute("UPDATE channel_crawl_progress SET status='done',last_start=0 "
                      "WHERE instance_domain='example.org'")
        elif name == "channels-cli.js" and "--check-health" in cmd:
            c.execute("UPDATE channels SET health_status='ok',health_checked_at=123 "
                      "WHERE instance_domain='example.org'")


@pytest.fixture
def accepted_pipeline(tmp_path, monkeypatch):
    """Run real updater staging lifecycle while substituting subprocesses only."""
    from engine.server.db.jobs.updater import pipeline
    from tests.jobs.test_updater_pipeline_commands import _args

    args = _args(
        tmp_path, check_existing_video_availability=True, skip_systemctl=False, use_gpu=False
    )
    (Path(args.crawler_dir) / "schema.sql").write_text(SCHEMA.read_text())
    prod, stage = Path(args.prod_db), Path(args.staging_db)
    with sqlite3.connect(prod) as c:
        c.executescript(SCHEMA.read_text())
        c.executemany(
            "INSERT INTO videos(video_id,instance_domain,video_uuid,last_checked_at,channel_id) "
            "VALUES(?,?,?,0,'owned')",
            [("a", "example.org", "uuid-a"), ("b", "example.org", "uuid-b")],
        )
        c.execute("CREATE TABLE video_embeddings(video_id TEXT PRIMARY KEY,embedding BLOB)")
        c.execute("INSERT INTO video_embeddings VALUES('a',X'00')")
        c.execute("CREATE TABLE derived_evidence(value TEXT)")
        c.execute("INSERT INTO derived_evidence VALUES('untouched')")
    staging.init_staging_db(stage, SCHEMA)
    # Existing production identities are not sufficient to authorize a sweep.
    # A resumed fake crawler will freshly reset/probe these staging parents.
    with sqlite3.connect(stage) as c:
        c.execute("INSERT INTO instances(host) VALUES('example.org')")
        c.execute("INSERT INTO channels(channel_id,channel_name,instance_domain) "
                  "VALUES('owned','owned','example.org')")
    monkeypatch.setattr(pipeline, "_prepared_discovery_is_available", lambda p: True)
    return pipeline, args, prod, stage


@pytest.mark.parametrize("point", ["before", "halfway", "after"])
def test_interruption_has_no_report_or_merge_and_restart_discards_evidence(
    accepted_pipeline, caplog, point
):
    """Fatal subprocess at any result boundary leaves disposable evidence only."""
    import logging

    pipeline, args, prod, stage = accepted_pipeline
    commands = []
    with sqlite3.connect(prod) as c:
        before = c.execute("SELECT * FROM videos").fetchall()

    def fail(cmd, cwd):
        commands.append(cmd)
        simulate_parent_cli_observation(stage, cmd)
        if "--check-availability" in cmd:
            with sqlite3.connect(stage) as c:
                if point != "before":
                    c.execute(
                        "UPDATE video_availability_work SET outcome='available',checked_at=123 WHERE video_id='a'"
                    )
                if point == "after":
                    c.execute(
                        "UPDATE video_availability_work SET outcome='available',checked_at=123"
                    )
            raise RuntimeError("worker interrupted")

    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError, match="interrupted"):
        pipeline.run_pipeline(args, command_runner=fail, validate_files=False)
    assert "video_availability_report " not in caplog.text
    assert not any(
        c[0] == "systemctl" or Path(c[1]).name == "build-video-embeddings.py" for c in commands
    )
    caplog.clear()
    commands.clear()

    def succeed(cmd, cwd):
        simulate_parent_cli_observation(stage, cmd)
        if not commands:
            with sqlite3.connect(stage) as c:
                assert c.execute("SELECT COUNT(*) FROM video_availability_work").fetchone()[0] == 0
        commands.append(cmd)
        if "--check-availability" in cmd:
            with sqlite3.connect(stage) as c:
                assert (
                    c.execute(
                        "SELECT COUNT(*) FROM video_availability_work WHERE outcome IS NULL"
                    ).fetchone()[0]
                    == 2
                )
                c.execute("UPDATE video_availability_work SET outcome='available',checked_at=124")

    with caplog.at_level(logging.INFO):
        pipeline.run_pipeline(args, command_runner=succeed, validate_files=False)
    assert caplog.text.count("video_availability_report ") == 1
    assert any(c[0] == "systemctl" and c[1] == "stop" for c in commands)
    with sqlite3.connect(prod) as c:
        assert c.execute("SELECT * FROM videos").fetchall() == before
        assert c.execute("SELECT * FROM video_embeddings").fetchall() == [("a", b"\x00")]
        assert c.execute("SELECT * FROM derived_evidence").fetchall() == [("untouched",)]
    commands.clear()
    args.check_existing_video_availability = False
    pipeline.run_pipeline(args, command_runner=succeed, validate_files=False)
    assert not any("--check-availability" in c for c in commands)
    assert not any("--allow-empty-scoped-whitelist" in c for c in commands)
    with sqlite3.connect(stage) as c:
        assert c.execute("SELECT COUNT(*) FROM video_availability_work").fetchone()[0] == 0


def test_valid_scope_without_production_matches_finishes_zero_work(
    accepted_pipeline, tmp_path, caplog
):
    """Nonempty scope with no matches is successful, unlike empty operator input."""
    import logging

    pipeline, args, prod, stage = accepted_pipeline
    f = tmp_path / "hosts"
    f.write_text("unmatched.org\n")
    args.hosts_file = str(f)
    with caplog.at_level(logging.INFO):
        pipeline.run_pipeline(args, command_runner=lambda *a: None, validate_files=False)
    line = next(
        r.message for r in caplog.records if r.message.startswith("video_availability_report ")
    )
    assert all(v == 0 for v in __import__("json").loads(line.split(" ", 1)[1]).values())


@pytest.mark.parametrize(
    "alter",
    [
        "UPDATE sqlite_master SET sql=replace(sql,'''available''','''AVAILABLE''') WHERE name='video_availability_work'",
        "UPDATE sqlite_master SET sql=replace(sql,'lower(trim(instance_domain))','lower(instance_domain)') WHERE name='idx_availability_work_host_identity'",
    ],
)
def test_schema_contract_preserves_literal_labels_and_index_expression(corpus, alter):
    """Formatting tolerance must not weaken case-sensitive CHECK/index identity."""
    _, stage = corpus
    with sqlite3.connect(stage) as c:
        c.execute("PRAGMA writable_schema=ON")
        c.execute(alter)
    with pytest.raises(RuntimeError, match="Incompatible"):
        staging.reset_video_availability_work(stage)


def test_built_node_worker_runs_after_production_file_removed(corpus, tmp_path):
    """Exercise real Python-to-built-Node schema contract with only HTTP faked."""
    import os
    import subprocess

    prod, stage = corpus
    crawler = SCHEMA.parent
    if (
        not (crawler / "dist/videos-cli.js").exists()
        or not (crawler / "node_modules/better-sqlite3").exists()
    ):
        pytest.skip("Build crawler and install Node dependencies for cross-runtime contract")
    staging.reset_video_availability_work(stage)
    missing = staging.materialize_video_availability_work(
        prod, stage, included_hosts={"example.org", "denied.org"}, denied_hosts={"denied.org"}
    )
    prod.unlink()
    stub = tmp_path / "fake-network.mjs"
    stub.write_text("""globalThis.fetch = async input => {
      const url = new URL(String(input));
      console.log('fixture_request '+url.host+' '+url.pathname);
      return new Response(JSON.stringify(url.pathname.includes('video-channels')
        ? {total:0,data:[]} : {uuid:url.pathname.split('/').at(-1)}));
    };""")
    with sqlite3.connect(stage) as c:
        before = c.execute("SELECT * FROM videos").fetchall()
    result = subprocess.run(
        [
            os.environ.get("CRAWLER_TEST_NODE", "node"),
            "--import",
            str(stub),
            str(crawler / "dist/videos-cli.js"),
            "--check-availability",
            "--db",
            str(stage),
            "--host-delay",
            "0",
            "--max-retries",
            "0",
            "--max-instances",
            "0",
        ],
        capture_output=True,
        text=True,
        cwd=crawler,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    # Parent eligibility was already decided by the persisted staging worklist.
    # Availability must not re-probe the channel list before video detail.
    assert result.stdout.count("/api/v1/video-channels") == 0
    assert result.stdout.count("/api/v1/videos/") == 2
    assert "video_availability_report" not in result.stdout
    assert (
        staging.video_availability_report(stage, missing_uuid=missing)["video_requests_attempted"]
        == 2
    )
    with sqlite3.connect(stage) as c:
        assert c.execute("SELECT * FROM videos").fetchall() == before


def test_unreadable_scope_fails_before_staging(tmp_path, monkeypatch):
    """Permission error is operator failure, even where tests run as root."""
    from engine.server.db.jobs.updater import pipeline
    from tests.jobs.test_updater_pipeline_commands import _args

    f = tmp_path / "hosts"
    f.write_text("example.org")
    read = Path.read_text

    def denied(path, *a, **kw):
        if path == f:
            raise PermissionError("unreadable hosts file")
        return read(path, *a, **kw)

    monkeypatch.setattr(Path, "read_text", denied)
    args = _args(tmp_path, check_existing_video_availability=True, hosts_file=str(f))
    with pytest.raises(PermissionError):
        pipeline.run_pipeline(args, validate_files=False)
    assert not Path(args.staging_db).exists()


@pytest.mark.parametrize("failure", [False, True])
def test_json_probe_closes_connection_on_success_and_sqlite_failure(monkeypatch, failure):
    """Probe lifetime ends before pipeline starts on either capability outcome."""
    connect = sqlite3.connect
    c = connect(":memory:")

    class Probe:
        """Expose only the SQLite boundary needed by the functional probe."""

        def execute(self, *a):
            if failure:
                raise sqlite3.OperationalError("no such table: json_each")
            return c.execute(*a)

        def close(self):
            c.close()

    monkeypatch.setattr(staging.sqlite3, "connect", lambda *a, **kw: Probe())
    if failure:
        with pytest.raises(RuntimeError, match="updater Python runtime"):
            staging.require_sqlite_json_each()
    else:
        staging.require_sqlite_json_each()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        c.execute("SELECT 1")


def test_denied_json_poison_rejected_before_materialization(corpus):
    """NULL exclusion values cannot silently remove valid production work."""
    prod, stage = corpus
    with pytest.raises(ValueError):
        staging.materialize_video_availability_work(
            prod, stage, included_hosts=None, denied_hosts={None}
        )
    with sqlite3.connect(stage) as c:
        assert c.execute("SELECT COUNT(*) FROM video_availability_work").fetchone()[0] == 0


@pytest.mark.parametrize(
    "outcome,checked,error",
    [
        ("unknown", None, "host_preflight: "),
        ("unknown", 123, ""),
        ("unknown", 123, "detail: network\nsecret"),
        ("unknown", "bad", "detail: network"),
        ("available", 123, "unexpected"),
        ("unknown", 9007199254740992, "detail: network"),
    ],
)
def test_report_rejects_malformed_terminal_evidence(corpus, outcome, checked, error):
    """A terminal label alone cannot authorize a finished structured report."""
    prod, stage = corpus
    staging.materialize_video_availability_work(
        prod, stage, included_hosts={"example.org"}, denied_hosts=set()
    )
    with sqlite3.connect(stage) as c:
        c.execute(
            "UPDATE video_availability_work SET outcome=?,checked_at=?,error=?",
            (outcome, checked, error),
        )
    with pytest.raises(RuntimeError):
        staging.video_availability_report(stage, missing_uuid=2)
    with sqlite3.connect(stage) as c:
        c.execute(
            "UPDATE video_availability_work SET outcome='unknown',checked_at=123,error='detail: network'"
        )
    report = staging.video_availability_report(stage, missing_uuid=2)
    assert report["unknown"] == 2 and report["video_requests_attempted"] == 2


def test_scope_snapshot_creation_failure_precedes_staging_reset(
    accepted_pipeline, tmp_path, monkeypatch
):
    """A failed transport file cannot fall back to the mutable operator path."""
    pipeline, args, prod, stage = accepted_pipeline
    f = tmp_path / "hosts"
    f.write_text("example.org")
    args.hosts_file = str(f)
    with sqlite3.connect(stage) as c:
        c.execute(
            "INSERT INTO video_availability_work(video_id,instance_domain,video_uuid) VALUES('evidence','example.org','uuid')"
        )
    monkeypatch.setattr(pipeline, "write_hosts_file", lambda *a, **kw: None)
    with pytest.raises(RuntimeError, match="freeze"):
        pipeline.run_pipeline(
            args, command_runner=lambda *a: pytest.fail("crawler ran"), validate_files=False
        )
    with sqlite3.connect(stage) as c:
        assert c.execute("SELECT video_id FROM video_availability_work").fetchall() == [
            ("evidence",)
        ]
