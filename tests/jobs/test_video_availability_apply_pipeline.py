"""Same-run sweep publication through real updater lifecycle and merge job."""

import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from engine.server.data.prepared_discovery import rebuild_prepared_discovery
from engine.server.db.bootstrap import bootstrap_engine_runtime_db
from tests.jobs.test_video_availability_sweep import accepted_pipeline as _accepted_pipeline

accepted_pipeline = _accepted_pipeline


@pytest.mark.parametrize("mode", ["ordinary", "report", "apply"])
def test_real_merge_and_opt_in_publication(accepted_pipeline, mode, caplog):
    """New INSERT_ONLY rows coexist with preserved existing state unless apply."""
    pipeline, args, prod, stage = accepted_pipeline
    args.check_existing_video_availability = mode == "report"
    args.apply_existing_video_availability = mode == "apply"
    args.merge_rules = str(
        Path(__file__).resolve().parents[2] / "engine/server/db/jobs/merge_rules.json"
    )
    with sqlite3.connect(prod) as conn:
        conn.execute("ALTER TABLE videos ADD COLUMN popularity REAL DEFAULT 0")
        conn.execute("ALTER TABLE video_embeddings ADD COLUMN instance_domain TEXT")
        bootstrap_engine_runtime_db(conn)
        conn.row_factory = sqlite3.Row
        rebuild_prepared_discovery(conn)
    commands = []

    def runner(cmd, cwd):
        """Replace crawler/network and heavy artifacts; execute actual merge SQL."""
        name = Path(cmd[1]).name
        commands.append(name)
        if name == "videos-cli.js" and "--check-availability" not in cmd:
            with sqlite3.connect(stage) as conn:
                conn.execute(
                    "INSERT INTO videos(video_id,instance_domain,video_uuid,last_checked_at,"
                    "invalid_reason,invalid_at) VALUES('new','example.org','uuid-new',1,'gone',1)"
                )
        if "--check-availability" in cmd:
            with sqlite3.connect(stage) as conn:
                conn.execute(
                    "UPDATE video_availability_work SET outcome='not_found',checked_at=123"
                )
        if name == "build-video-embeddings.py":
            with sqlite3.connect(stage) as conn:
                conn.execute(
                    "CREATE TABLE video_embeddings(video_id TEXT PRIMARY KEY,embedding BLOB,"
                    "instance_domain TEXT)"
                )
        if name == "merge-staging-db.py":
            completed = subprocess.run(
                [sys.executable, *cmd[1:]], cwd=cwd, capture_output=True, text=True
            )
            assert completed.returncode == 0, completed.stderr
        if name == "recompute-popularity.py":
            with sqlite3.connect(prod) as conn:
                pair = conn.execute(
                    "SELECT invalid_reason,invalid_at FROM videos WHERE video_id='a'"
                ).fetchone()
            assert pair == (("not_found", 123) if mode == "apply" else (None, None))
        if name == "rebuild-video-discovery-data.py":
            with sqlite3.connect(prod) as conn:
                conn.row_factory = sqlite3.Row
                rebuild_prepared_discovery(conn)

    with caplog.at_level(logging.INFO):
        pipeline.run_pipeline(args, command_runner=runner, validate_files=False)
    with sqlite3.connect(prod) as conn:
        assert conn.execute(
            "SELECT invalid_reason,invalid_at FROM videos WHERE video_id='new'"
        ).fetchone() == ("gone", 1)
        assert conn.execute(
            "SELECT invalid_reason,invalid_at FROM videos WHERE video_id='b'"
        ).fetchone() == (("not_found", 123) if mode == "apply" else (None, None))
    assert caplog.text.count("video_availability_report ") == int(mode != "ordinary")
    assert caplog.text.count("video_availability_publication ") == int(mode == "apply")
    assert (
        commands.index("stop")
        < commands.index("merge-staging-db.py")
        < commands.index("recompute-popularity.py")
    )
    if mode != "ordinary":
        assert commands.index(
            "videos-cli.js", commands.index("videos-cli.js") + 1
        ) < commands.index("stop")


@pytest.mark.parametrize("failure", ["uuid", "derived"])
def test_apply_failure_obeys_durable_restart_guard(accepted_pipeline, monkeypatch, caplog, failure):
    """Publication conflicts and post-commit rebuild failures cannot serve stale Prepared."""
    pipeline, args, prod, stage = accepted_pipeline
    args.check_existing_video_availability = False
    args.apply_existing_video_availability = True
    from engine.server.data.prepared_discovery import prepared_discovery_available

    def ready(path):
        """Read real durable Prepared readiness at the existing restart boundary."""
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            return prepared_discovery_available(conn)

    monkeypatch.setattr(pipeline, "_prepared_discovery_is_available", ready)
    with sqlite3.connect(prod) as conn:
        conn.execute("ALTER TABLE videos ADD COLUMN popularity REAL DEFAULT 0")
        conn.execute("ALTER TABLE video_embeddings ADD COLUMN instance_domain TEXT")
        bootstrap_engine_runtime_db(conn)
        conn.row_factory = sqlite3.Row
        rebuild_prepared_discovery(conn)
    commands = []

    def runner(cmd, cwd):
        """Inject source drift or a derived build fault at actual lifecycle boundaries."""
        name = Path(cmd[1]).name
        commands.append(name)
        if "--check-availability" in cmd:
            with sqlite3.connect(stage) as conn:
                conn.execute("UPDATE video_availability_work SET outcome='gone',checked_at=123")
        if name == "merge-staging-db.py":
            # Merge owns invalidation even before publisher; reflect that canonical
            # transaction effect without invoking unrelated derived jobs.
            from engine.server.data.prepared_discovery import invalidate_prepared_discovery

            with sqlite3.connect(prod) as conn:
                invalidate_prepared_discovery(conn)
                if failure == "uuid":
                    conn.execute("UPDATE videos SET video_uuid='drift' WHERE video_id='a'")
        if name == "rebuild-video-discovery-data.py":
            raise RuntimeError("derived rebuild failed")

    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
        pipeline.run_pipeline(args, command_runner=runner, validate_files=False)
    assert "start" not in commands and not ready(prod)
    with sqlite3.connect(prod) as conn:
        assert conn.execute("SELECT invalid_reason FROM videos WHERE video_id='b'").fetchone() == (
            None if failure == "uuid" else "gone",
        )
    assert caplog.text.count("video_availability_publication ") == int(failure == "derived")
    assert ("recompute-popularity.py" in commands) == (failure == "derived")


@pytest.mark.parametrize("apply", [False, True])
def test_cli_valid_modes_share_sweep_contract(apply, tmp_path):
    """Each permanent mode selects the same sweep with distinct publication intent."""
    from engine.server.db.jobs.updater import cli

    flag = "--apply-existing-video-availability" if apply else "--check-existing-video-availability"
    args = cli.parse_args([flag, "--service-name", "test"])
    assert args.apply_existing_video_availability is apply
    assert args.check_existing_video_availability is (not apply)
    assert cli.validate_availability_sweep_mode(args) is None


@pytest.mark.parametrize(
    "extra",
    [
        ["--check-existing-video-availability"],
        ["--retry-errors", "--resume-staging"],
        ["--sync-join-whitelist", "--dry-run"],
        ["--host-pipeline"],
    ],
)
def test_apply_cli_incompatible_modes_fail_before_effects(extra):
    """Apply inherits sweep eligibility and rejects simultaneous report mode."""
    from engine.server.db.jobs.updater import cli

    with pytest.raises(SystemExit):
        cli.parse_args(["--apply-existing-video-availability", *extra, "--service-name", "test"])


def test_direct_conflicting_flags_and_old_sqlite_fail_before_paths(tmp_path, monkeypatch):
    """Manually built args and unsupported UPDATE FROM cannot reach writable gates."""
    from engine.server.db.jobs.updater import cli, pipeline
    from tests.jobs.test_updater_pipeline_commands import _args

    args = _args(
        tmp_path, check_existing_video_availability=True, apply_existing_video_availability=True
    )
    with pytest.raises(ValueError):
        pipeline.run_pipeline(args, validate_files=False)
    args.check_existing_video_availability = False
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 32, 0))
    with pytest.raises(RuntimeError, match="3.33"):
        pipeline.run_pipeline(args, validate_files=False)
    assert not Path(args.lock_file).exists() and not Path(args.staging_db).exists()
    with pytest.raises(SystemExit):
        cli.parse_args(["--apply-existing-video-availability"])


def test_resumed_apply_discards_old_work_and_keeps_frozen_scope(accepted_pipeline, tmp_path):
    """Interrupted work is replaced; editing/deleting host input cannot change the sweep."""
    pipeline, args, prod, stage = accepted_pipeline
    args.check_existing_video_availability = False
    args.apply_existing_video_availability = True
    scope = tmp_path / "hosts"
    scope.write_text("example.org\n")
    args.hosts_file = str(scope)
    with sqlite3.connect(prod) as conn:
        conn.execute("CREATE TABLE instance_denylist(host TEXT,is_active INTEGER)")
        conn.execute("UPDATE videos SET invalid_reason='gone',invalid_at=1")
    with sqlite3.connect(stage) as conn:
        conn.execute(
            "INSERT INTO video_availability_work "
            "VALUES('old','unselected.org','old','gone',1000,NULL)"
        )
    for interrupted in (True, False):
        scope.write_text("example.org\n")
        commands = []

        def runner(cmd, cwd, *, commands=commands, interrupted=interrupted):
            """Change only operator/network edges; retain real frozen work lifecycle."""
            if not commands:
                with sqlite3.connect(stage) as conn:
                    assert (
                        conn.execute("SELECT COUNT(*) FROM video_availability_work").fetchone()[0]
                        == 0
                    )
                scope.unlink()
            commands.append(cmd)
            if "--hosts-file" in cmd:
                frozen = Path(cmd[cmd.index("--hosts-file") + 1])
                assert frozen != scope and frozen.read_text().strip() == "example.org"
            if "--check-availability" in cmd:
                with sqlite3.connect(stage) as conn:
                    assert conn.execute(
                        "SELECT video_id FROM video_availability_work ORDER BY video_id"
                    ).fetchall() == [("a",), ("b",)]
                    conn.execute(
                        "UPDATE video_availability_work SET outcome='available',checked_at=2000 "
                        "WHERE video_id='a'"
                    )
                    if not interrupted:
                        conn.execute(
                            "UPDATE video_availability_work SET outcome='available',checked_at=2000"
                        )
                if interrupted:
                    raise RuntimeError("interrupted sweep")

        if interrupted:
            with pytest.raises(RuntimeError, match="interrupted sweep"):
                pipeline.run_pipeline(args, command_runner=runner, validate_files=False)
            assert not any(c[0] == "systemctl" for c in commands)
            with sqlite3.connect(prod) as conn:
                assert conn.execute("SELECT invalid_reason,invalid_at FROM videos").fetchall() == [
                    ("gone", 1),
                    ("gone", 1),
                ]
        else:
            pipeline.run_pipeline(args, command_runner=runner, validate_files=False)
            with sqlite3.connect(prod) as conn:
                assert conn.execute("SELECT invalid_reason,invalid_at FROM videos").fetchall() == [
                    (None, None),
                    (None, None),
                ]


@pytest.mark.parametrize("bad", [0, 1, None, "yes"])
def test_direct_flags_require_actual_booleans(tmp_path, bad):
    """Malformed programmatic input cannot silently choose a publication mode."""
    from engine.server.db.jobs.updater import pipeline
    from tests.jobs.test_updater_pipeline_commands import _args

    args = _args(tmp_path, apply_existing_video_availability=bad)
    with pytest.raises(ValueError):
        pipeline.run_pipeline(args, validate_files=False)
    assert not Path(args.lock_file).exists() and not Path(args.staging_db).exists()
