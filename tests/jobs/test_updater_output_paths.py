"""Observable ownership checks at both updater entrypoints, before any writes."""

import sqlite3
from dataclasses import replace
from itertools import combinations
from pathlib import Path

import pytest

from engine.server.db.jobs.updater import cli, paths, pipeline
from tests.jobs.test_updater_pipeline_commands import _args

ROLES = (
    "prod_db",
    "staging_db",
    "random_cache_db",
    "similarity_db",
    "lock_file",
    "index_path",
    "index_meta_path",
    "logs",
)
SQLITE_ROLES = ROLES[:4]


@pytest.mark.parametrize("left,right", list(combinations(ROLES, 2)))
@pytest.mark.parametrize("alias", ["pathname", "symlink", "hardlink"])
def test_cross_role_aliases_preserve_files(tmp_path, left, right, alias):
    """Every cross-role alias is rejected without touching the original SQLite."""
    args = _args(tmp_path)
    target = Path(getattr(args, left))
    with sqlite3.connect(target) as conn:
        conn.execute("CREATE TABLE marker(value)")
        conn.execute("INSERT INTO marker VALUES('durable')")
    original = target.read_bytes(), target.stat().st_ino
    other = Path(getattr(args, right))
    if alias == "pathname":
        setattr(args, right, str(target.parent / "unused" / ".." / target.name))
    elif alias == "symlink":
        other.symlink_to(target)
    else:
        other.hardlink_to(target)
    with pytest.raises(RuntimeError, match="path collision") as error:
        pipeline.run_pipeline(args, validate_files=False)
    assert left in str(error.value) and right in str(error.value)
    assert ("device/inode" if alias == "hardlink" else "resolved pathname") in str(error.value)
    assert (target.read_bytes(), target.stat().st_ino) == original
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT value FROM marker").fetchone() == ("durable",)


@pytest.mark.parametrize(
    "base,other", [(base, other) for base in SQLITE_ROLES for other in ROLES if base != other]
)
@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
@pytest.mark.parametrize("exists", [False, True])
def test_potential_sidecar_collision(tmp_path, base, other, suffix, exists):
    """SQLite namespaces reserve future sidecars as well as existing inodes."""
    resolved = paths.from_args(_args(tmp_path))
    sidecar = Path(str(getattr(resolved, base)) + suffix)
    if exists:
        sidecar.write_bytes(b"owned sidecar")
    unsafe = replace(resolved, **{other: sidecar})
    with pytest.raises(RuntimeError, match="resolved pathname"):
        paths.validate_updater_output_paths(unsafe)
    if exists:
        assert sidecar.read_bytes() == b"owned sidecar"


def test_disjoint_future_paths_and_same_role_inode_are_allowed(tmp_path):
    """Missing outputs, similar prefixes and within-role aliases are legitimate."""
    resolved = paths.from_args(_args(tmp_path))
    paths.validate_updater_output_paths(resolved)
    resolved.prod_db.write_bytes(b"owned")
    Path(str(resolved.prod_db) + "-wal").hardlink_to(resolved.prod_db)
    paths.validate_updater_output_paths(
        replace(resolved, logs=Path(str(resolved.prod_db) + ".log"))
    )


@pytest.mark.parametrize("operation", ["resolve", "stat"])
def test_filesystem_error_is_fail_closed(tmp_path, monkeypatch, operation):
    """Only a missing future inode can be ignored; permission failures abort."""
    resolved = paths.from_args(_args(tmp_path))
    original = getattr(Path, operation)

    def denied(path, *args, **kwargs):
        if path == resolved.random_cache_db:
            raise PermissionError("filesystem denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, operation, denied)
    with pytest.raises(PermissionError):
        paths.validate_updater_output_paths(resolved)


@pytest.mark.parametrize(
    "mode",
    [
        {},
        {"check_existing_video_availability": True},
        {"apply_existing_video_availability": True},
        {"sync_join_whitelist": True, "dry_run": True},
        {"retry_errors": True},
        {"host_pipeline": True},
    ],
)
@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("output", ROLES[1:])
def test_every_mode_refuses_before_effects(tmp_path, mode, resume, output):
    """Direct callers cannot bypass ownership with validate_files=False or modes."""
    args = _args(tmp_path, resume_staging=resume, **mode)
    prod = Path(args.prod_db)
    with sqlite3.connect(prod) as conn:
        conn.execute("CREATE TABLE marker(value)")
    before = prod.read_bytes(), prod.stat().st_ino
    setattr(args, output, args.prod_db)
    with pytest.raises(RuntimeError, match="path collision"):
        pipeline.run_pipeline(
            args, command_runner=lambda *a: pytest.fail("subprocess ran"), validate_files=False
        )
    assert (prod.read_bytes(), prod.stat().st_ino) == before
    if output != "lock_file":
        assert not Path(args.lock_file).exists()


@pytest.mark.parametrize("output", ["logs", "lock_file", "random_cache_db"])
def test_cli_preflight_precedes_service_discovery_and_logging(tmp_path, monkeypatch, output):
    """CLI refusal leaves even the future logging parent uncreated."""
    prod = tmp_path / "production"
    prod.write_bytes(b"protected")
    monkeypatch.setattr(
        cli,
        "resolve_default_engine_service_name",
        lambda *a: pytest.fail("service subprocess discovery ran"),
    )
    argv = [
        "--prod-db",
        str(prod),
        "--logs",
        str(tmp_path / "future" / "log"),
        "--" + output.replace("_", "-"),
        str(prod),
    ]
    with pytest.raises(SystemExit):
        cli.parse_args(argv)
    assert prod.read_bytes() == b"protected"
    assert not (tmp_path / "future").exists()
