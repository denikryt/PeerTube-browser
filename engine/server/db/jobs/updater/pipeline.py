"""Updater pipeline orchestration and command construction.

This module preserves the historical updater stage order while moving the large
operational flow out of ``updater-worker.py``.  Tests inject fake command
runners and monkeypatch helper boundaries; production defaults still call the
same subprocess jobs and crawler CLIs.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

try:
    from engine.server.api.server_config import (
        DEFAULT_RANDOM_CACHE_FILTERED_MODE,
        DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR,
        DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE,
        DEFAULT_RANDOM_CACHE_SIZE,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution path.
    # updater-worker.py adds engine/server to sys.path so the stable executable
    # path can import updater modules without requiring package-mode PYTHONPATH.
    # Keep that deployment contour while sharing runtime random-cache defaults.
    from api.server_config import (
        DEFAULT_RANDOM_CACHE_FILTERED_MODE,
        DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR,
        DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE,
        DEFAULT_RANDOM_CACHE_SIZE,
    )


try:
    from engine.server.data.prepared_discovery import prepared_discovery_available
except ModuleNotFoundError:  # pragma: no cover - direct script execution path.
    from data.prepared_discovery import prepared_discovery_available

from .cli import validate_availability_sweep_mode
from .commands import CommandRun, run_cmd, run_with_cpu_fallback, systemctl_cmd
from .locks import single_run_lock
from .paths import from_args, validate_required_files, validate_updater_output_paths
from .staging import (
    assert_production_schema_compatible,
    assert_video_availability_staging_semantics,
    count_staging_deltas,
    init_staging_db,
    list_staging_hosts,
    assert_retry_parent_provenance,
    inject_replace_embedding_for_test,
    load_scoped_hosts_file,
    materialize_video_availability_work,
    prune_staging_local_non_ok_instances,
    reset_video_availability_work,
    seed_staging_from_prod,
    video_availability_report,
)
from .sync import (
    fetch_join_hosts,
    list_prod_hosts,
    load_denied_hosts,
    purge_hosts,
    purge_hosts_from_staging,
    write_hosts_file,
)


def _prepared_discovery_is_available(prod_db: Path) -> bool:
    """Return whether the canonical DB has a valid prepared Discovery snapshot.

    This is deliberately checked at the updater's existing service-restart
    boundary so a failed rebuild from any prior updater run remains durable.
    """

    try:
        with sqlite3.connect(prod_db.as_posix()) as conn:
            conn.row_factory = sqlite3.Row
            return prepared_discovery_available(conn)
    except sqlite3.Error as exc:
        logging.error("prepared Discovery readiness check failed: %s", exc)
        return False


def run_pipeline(
    args, *, command_runner: CommandRun | None = None, validate_files: bool = True
) -> None:
    """Run the updater pipeline with current stage order and compatibility behavior."""

    frozen_included_hosts = validate_availability_sweep_mode(args)
    # Freeze operator input before discovery: rereading mutable file content
    # after a subprocess would change the security boundary of this invocation.
    requested_hosts = (
        frozen_included_hosts if frozen_included_hosts is not None
        else load_scoped_hosts_file(Path(args.hosts_file)) if args.hosts_file else None
    )
    apply_availability = getattr(args, "apply_existing_video_availability", False)
    availability = getattr(args, "check_existing_video_availability", False) or apply_availability
    paths = from_args(args)
    # Direct Python callers receive the same protection as the executable CLI,
    # even when runtime-file validation is intentionally disabled by a harness.
    validate_updater_output_paths(paths)
    if validate_files:
        validate_required_files(paths)

    logging.info("worker start prod_db=%s staging_db=%s", paths.prod_db, paths.staging_db)
    service_stopped = False
    pipeline_start = time.monotonic()
    retry_errors = bool(getattr(args, "retry_errors", False))
    host_pipeline = bool(getattr(args, "host_pipeline", False))
    if args.dry_run and not args.sync_join_whitelist:
        raise RuntimeError("--dry-run is supported only together with --sync-join-whitelist.")
    if retry_errors and (not args.resume_staging or not paths.staging_db.exists()):
        raise RuntimeError("--retry-errors requires an existing --resume-staging database.")
    if retry_errors and host_pipeline:
        raise RuntimeError("--host-pipeline cannot be combined with --retry-errors.")

    temp_files: list[Path] = []
    try:
        with single_run_lock(paths.lock_file):
            # The updater must fail before any network request or production mutation
            # when crawler-owned columns have not been migrated into whitelist.db.
            assert_production_schema_compatible(paths.prod_db, paths.schema_path)
            if args.resume_staging and paths.staging_db.exists():
                assert_video_availability_staging_semantics(paths.staging_db)
            denied_hosts = load_denied_hosts(paths.prod_db)
            logging.info("moderation deny_hosts_active=%d", len(denied_hosts))

            requested_file = None
            if requested_hosts is not None:
                requested_file = write_hosts_file(
                    requested_hosts, "ptb-requested-hosts-", allow_empty=True
                )
                # An operator-selected run must never silently turn into an
                # unscoped crawler run when its transport snapshot fails.
                if requested_file is None:
                    raise RuntimeError("Failed to freeze requested host scope")
                temp_files.append(requested_file)

            sync_new_hosts: set[str] = set()
            sync_stale_hosts: set[str] = set()
            existing_sweep_hosts: set[str] = set()
            if args.sync_join_whitelist:
                join_hosts = fetch_join_hosts(args.whitelist_url)
                effective_join_hosts = join_hosts - denied_hosts
                prod_hosts = list_prod_hosts(paths.prod_db)
                sync_stale_hosts = prod_hosts - effective_join_hosts
                sync_new_hosts = effective_join_hosts - prod_hosts
                if availability:
                    existing_sweep_hosts = prod_hosts & effective_join_hosts
                    if requested_hosts is not None:
                        existing_sweep_hosts &= requested_hosts
                logging.info(
                    "sync-join hosts_total=%d effective=%d stale=%d new=%d",
                    len(join_hosts),
                    len(effective_join_hosts),
                    len(sync_stale_hosts),
                    len(sync_new_hosts),
                )

                stale_plan = purge_hosts(
                    prod_db=paths.prod_db,
                    similarity_db=paths.similarity_db,
                    hosts=sync_stale_hosts,
                    dry_run=True,
                )
                if args.dry_run:
                    logging.info(
                        "sync-join dry-run stale_hosts=%d delete_plan=%s",
                        len(sync_stale_hosts),
                        stale_plan,
                    )
                    return
                if sync_stale_hosts and not args.yes:
                    raise RuntimeError(
                        "Refusing sync stale-host purge without --yes. "
                        "Re-run with --yes or use --dry-run to inspect."
                    )
            if args.resume_staging and paths.staging_db.exists():
                logging.info("staging reused from previous run: %s", paths.staging_db)
            else:
                init_staging_db(paths.staging_db, paths.schema_path)
                logging.info("staging initialized")
                if not args.sync_join_whitelist:
                    seed_staging_from_prod(paths.prod_db, paths.staging_db)
                    logging.info("staging seeded from prod (instances + channels)")

            if existing_sweep_hosts:
                # Strict sync availability reads old production videos, not new
                # ingest scope. Seed only the selected existing parents.
                seed_staging_from_prod(paths.prod_db, paths.staging_db, existing_sweep_hosts)

            reset_video_availability_work(paths.staging_db)

            if denied_hosts:
                staging_prune = purge_hosts_from_staging(paths.staging_db, denied_hosts)
                if staging_prune:
                    logging.info("staging denylist prune=%s", staging_prune)

            exclude_hosts_file = write_hosts_file(denied_hosts, "ptb-exclude-hosts-")
            if denied_hosts and exclude_hosts_file is None:
                raise RuntimeError("Failed to freeze excluded host scope")
            if exclude_hosts_file is not None:
                temp_files.append(exclude_hosts_file)
            whitelist_hosts_file = None
            if args.sync_join_whitelist:
                whitelist_hosts_file = write_hosts_file(sync_new_hosts, "ptb-whitelist-hosts-")
                if sync_new_hosts and whitelist_hosts_file is None:
                    raise RuntimeError("Failed to freeze JoinPeerTube new-host scope")
                if whitelist_hosts_file is not None:
                    temp_files.append(whitelist_hosts_file)

            host_concurrency = int(getattr(args, "host_concurrency", 2))
            parent_scope: set[str] = set()
            parent_scope_file = None
            host_delay_ms = int(getattr(args, "host_delay_ms", 200))
            run_crawl_stages = (
                retry_errors or (not args.sync_join_whitelist) or bool(sync_new_hosts) or bool(existing_sweep_hosts)
            )
            if run_crawl_stages:
                # Keep one host-scope file flowing through every crawler stage so a
                # targeted updater run stays constrained after instances discovery.
                host_scope_args: list[str] = []
                if requested_file is not None:
                    host_scope_args = ["--hosts-file", requested_file.as_posix()]

                # Registry discovery has no error-only selector. A retry run
                # intentionally preserves the staging host set and revisits the
                # three crawler stages that persist retryable record errors.
                if (not retry_errors and requested_hosts != set()
                    and (not args.sync_join_whitelist or bool(sync_new_hosts))):
                    instances_cmd = [
                        args.node_bin,
                        (paths.crawler_dist / "instances-cli.js").as_posix(),
                        "--db",
                        paths.staging_db.as_posix(),
                        "--resume",
                        "--max-instances",
                        str(args.max_instances),
                        "--concurrency",
                        str(args.concurrency),
                        "--host-delay",
                        str(host_delay_ms),
                        "--timeout",
                        str(args.timeout_ms),
                        "--max-retries",
                        str(args.max_retries),
                        *host_scope_args,
                    ]
                    if requested_hosts is not None:
                        # A valid nonempty operator scope may have zero registry
                        # overlap; this is zero work, never an unscoped fallback.
                        instances_cmd.append("--allow-empty-scoped-whitelist")
                    if whitelist_hosts_file is not None:
                        instances_cmd.extend(["--whitelist-file", whitelist_hosts_file.as_posix()])
                    else:
                        instances_cmd.extend(["--whitelist-url", args.whitelist_url])
                    if exclude_hosts_file is not None:
                        instances_cmd.extend(
                            ["--exclude-hosts-file", exclude_hosts_file.as_posix()]
                        )
                    run_cmd(instances_cmd, cwd=paths.crawler_dir, runner=command_runner)

                # A fresh run must select once after registry discovery and
                # forward only that exact set through subsequent child stages.
                discovered = list_staging_hosts(paths.staging_db) - denied_hosts
                if requested_hosts is not None:
                    discovered &= requested_hosts
                candidate_ingest = (discovered & sync_new_hosts) if args.sync_join_whitelist else discovered
                candidate_existing = (discovered & existing_sweep_hosts) if availability else set()
                # A single deterministic max-instances budget covers both
                # branches without making old existing parents new ingest work.
                combined = sorted(candidate_ingest | candidate_existing)
                if args.max_instances > 0:
                    combined = combined[:args.max_instances]
                allowed = set(combined)
                ingest_scope = candidate_ingest & allowed
                existing_scope = candidate_existing & allowed
                parent_scope = ingest_scope | existing_scope
                parent_scope_file = write_hosts_file(
                    parent_scope, "ptb-parent-run-", allow_empty=True
                )
                if parent_scope_file is None:
                    raise RuntimeError("Failed to freeze parent-health publication scope")
                temp_files.append(parent_scope_file)
                ingest_file = write_hosts_file(ingest_scope, "ptb-ingest-run-", allow_empty=True)
                if ingest_file is None:
                    raise RuntimeError("Failed to freeze new-ingest host scope")
                temp_files.append(ingest_file)
                host_scope_args = ["--hosts-file", ingest_file.as_posix()]
                if retry_errors:
                    assert_retry_parent_provenance(paths.staging_db, ingest_scope)

                channels_cmd = [
                    args.node_bin,
                    (paths.crawler_dist / "channels-cli.js").as_posix(),
                    "--db",
                    paths.staging_db.as_posix(),
                    "--resume",
                    "--new-channels",
                    "--max-instances",
                    str(args.max_instances),
                    "--max-channels",
                    str(args.max_channels),
                    "--concurrency",
                    str(args.concurrency),
                    "--host-concurrency",
                    str(host_concurrency),
                    "--host-delay",
                    str(host_delay_ms),
                    "--timeout",
                    str(args.timeout_ms),
                    "--max-retries",
                    str(args.max_retries),
                    *host_scope_args,
                ]
                if exclude_hosts_file is not None:
                    channels_cmd.extend(["--exclude-hosts-file", exclude_hosts_file.as_posix()])

                videos_cmd = [
                    args.node_bin,
                    (paths.crawler_dist / "videos-cli.js").as_posix(),
                    "--db",
                    paths.staging_db.as_posix(),
                    "--existing-db",
                    paths.prod_db.as_posix(),
                    "--resume",
                    "--new-videos",
                    "--sort",
                    "-publishedAt",
                    "--max-instances",
                    str(args.max_instances),
                    "--max-channels",
                    str(args.max_channels),
                    "--max-videos-pages",
                    str(args.max_videos_pages),
                    "--stop-after-full-pages",
                    str(args.videos_stop_after_full_pages),
                    "--concurrency",
                    str(args.concurrency),
                    "--host-concurrency",
                    str(host_concurrency),
                    "--host-delay",
                    str(host_delay_ms),
                    "--timeout",
                    str(args.timeout_ms),
                    "--max-retries",
                    str(args.max_retries),
                    *host_scope_args,
                ]
                if exclude_hosts_file is not None:
                    videos_cmd.extend(["--exclude-hosts-file", exclude_hosts_file.as_posix()])
                if retry_errors:
                    videos_cmd.append("--errors")

                counts_cmd = [
                    args.node_bin,
                    (paths.crawler_dist / "channels-videos-count-cli.js").as_posix(),
                    "--db",
                    paths.staging_db.as_posix(),
                    "--resume",
                    "--concurrency",
                    str(args.concurrency),
                    "--host-concurrency",
                    str(host_concurrency),
                    "--host-delay",
                    str(host_delay_ms),
                    "--timeout",
                    str(args.timeout_ms),
                    "--max-retries",
                    str(args.max_retries),
                    *host_scope_args,
                ]
                if exclude_hosts_file is not None:
                    counts_cmd.extend(["--exclude-hosts-file", exclude_hosts_file.as_posix()])
                if retry_errors:
                    counts_cmd.append("--errors")

                if ingest_scope and host_pipeline:
                    # One process owns the shared SQLite scheduler. Within it,
                    # hosts overlap but each host observes strict stage order.
                    host_pipeline_cmd = [
                        args.node_bin,
                        (paths.crawler_dist / "host-pipeline-cli.js").as_posix(),
                        "--db",
                        paths.staging_db.as_posix(),
                        "--existing-db",
                        paths.prod_db.as_posix(),
                        "--resume",
                        "--sort",
                        "-publishedAt",
                        "--max-instances",
                        str(args.max_instances),
                        "--max-channels",
                        str(args.max_channels),
                        "--max-videos-pages",
                        str(args.max_videos_pages),
                        "--stop-after-full-pages",
                        str(args.videos_stop_after_full_pages),
                        "--concurrency",
                        str(args.concurrency),
                        "--host-concurrency",
                        str(host_concurrency),
                        "--host-delay",
                        str(host_delay_ms),
                        "--timeout",
                        str(args.timeout_ms),
                        "--max-retries",
                        str(args.max_retries),
                        *host_scope_args,
                    ]
                    if exclude_hosts_file is not None:
                        host_pipeline_cmd.extend(
                            ["--exclude-hosts-file", exclude_hosts_file.as_posix()]
                        )
                    run_cmd(host_pipeline_cmd, cwd=paths.crawler_dir, runner=command_runner)
                elif ingest_scope:
                    if not retry_errors:
                        # Sequential updater is the sole initialization owner.
                        # Reset before probe; never reset after fresh health.
                        run_cmd([
                            args.node_bin,
                            (paths.crawler_dist / "channels-cli.js").as_posix(),
                            "--db", paths.staging_db.as_posix(),
                            "--initialize-only", *host_scope_args,
                        ], cwd=paths.crawler_dir, runner=command_runner)
                        run_cmd([
                            args.node_bin,
                            (paths.crawler_dist / "instances-health-cli.js").as_posix(),
                            "--db", paths.staging_db.as_posix(),
                            "--concurrency", str(args.concurrency),
                            "--host-delay", str(host_delay_ms),
                            "--timeout", str(args.timeout_ms),
                            "--max-retries", str(args.max_retries),
                            *host_scope_args,
                        ], cwd=paths.crawler_dir, runner=command_runner)
                        run_cmd(channels_cmd + ["--already-initialized"],
                                cwd=paths.crawler_dir, runner=command_runner)
                        run_cmd(channels_cmd + ["--check-health"],
                                cwd=paths.crawler_dir, runner=command_runner)
                    # Resolve only missing counts before videos-cli selects rows
                    # with videos_count > 0. Each successful channel write is its
                    # own resume checkpoint inside the count worker.
                    run_cmd(counts_cmd, cwd=paths.crawler_dir, runner=command_runner)

                    # Video progress stores the next page offset after every
                    # successful page, so a resumed run continues within a channel.
                    run_cmd(videos_cmd, cwd=paths.crawler_dir, runner=command_runner)

                if existing_scope:
                    # Separate existing-parent probe for the availability sweep;
                    # do not run count/video/new-ingest for these production hosts.
                    existing_file = write_hosts_file(existing_scope, "ptb-existing-parent-")
                    if existing_file is None:
                        raise RuntimeError("Failed to freeze existing-parent scope")
                    temp_files.append(existing_file)
                    existing_args = ["--hosts-file", existing_file.as_posix()]
                    base_channels = [
                        args.node_bin, (paths.crawler_dist / "channels-cli.js").as_posix(),
                        "--db", paths.staging_db.as_posix(), *existing_args
                    ]
                    run_cmd(base_channels + ["--initialize-only"],
                            cwd=paths.crawler_dir, runner=command_runner)
                    run_cmd([
                        args.node_bin,
                        (paths.crawler_dist / "instances-health-cli.js").as_posix(),
                        "--db", paths.staging_db.as_posix(),
                        "--concurrency", str(args.concurrency),
                        "--host-delay", str(host_delay_ms),
                        "--timeout", str(args.timeout_ms),
                        "--max-retries", str(args.max_retries), *existing_args
                    ], cwd=paths.crawler_dir, runner=command_runner)
                    run_cmd(base_channels + [
                        "--already-initialized", "--new-channels",
                        "--concurrency", str(args.concurrency),
                        "--host-concurrency", str(host_concurrency),
                        "--host-delay", str(host_delay_ms),
                        "--timeout", str(args.timeout_ms),
                        "--max-retries", str(args.max_retries),
                        "--max-channels", str(args.max_channels)
                    ], cwd=paths.crawler_dir, runner=command_runner)
                    run_cmd(base_channels + ["--check-health"],
                            cwd=paths.crawler_dir, runner=command_runner)

                if retry_errors:
                    # Error retry is deliberately a staging-repair operation.
                    # Keeping merge and derived builds for the following normal
                    # resume run lets operators inspect remaining failures first.
                    logging.info(
                        "retry-errors finished crawler stages; staging retained without merge"
                    )
                    return

            else:
                logging.info("sync-join ingest skipped: no new hosts after denylist filtering")
                if not sync_stale_hosts and not availability:
                    logging.info("sync-join no changes detected; finishing early")
                    return

            if availability and parent_scope:
                missing_uuid = materialize_video_availability_work(
                    paths.prod_db,
                    paths.staging_db,
                    included_hosts=parent_scope,
                    denied_hosts=denied_hosts,
                )
                run_cmd(
                    [
                        args.node_bin,
                        (paths.crawler_dist / "videos-cli.js").as_posix(),
                        "--check-availability",
                        "--db",
                        paths.staging_db.as_posix(),
                        "--concurrency",
                        str(args.concurrency),
                        "--host-concurrency",
                        str(host_concurrency),
                        "--host-delay",
                        str(host_delay_ms),
                        "--timeout",
                        str(args.timeout_ms),
                        "--max-retries",
                        str(args.max_retries),
                    ],
                    cwd=paths.crawler_dir,
                    runner=command_runner,
                )
                report = video_availability_report(paths.staging_db, missing_uuid=missing_uuid)
                logging.info("video_availability_report %s", json.dumps(report, sort_keys=True))
            elif availability:
                # Computed empty set is a no-work result, not an unscoped sweep.
                report = video_availability_report(paths.staging_db, missing_uuid=0)
                logging.info("video_availability_report %s", json.dumps(report, sort_keys=True))

            # Staging is disposable working state. Rebuild embeddings with the
            # currently deployed recipe immediately before every production merge,
            # including --resume-staging, so stale pre-deploy vectors can never leak
            # back into production. A failed rebuild naturally aborts before merge.
            embeddings_cmd = [
                args.python_bin,
                (paths.script_dir / "build-video-embeddings.py").as_posix(),
                "--db-path",
                paths.staging_db.as_posix(),
                "--force",
            ]
            if args.use_gpu:
                embeddings_cmd.append("--gpu")
            else:
                embeddings_cmd.append("--cpu")
            run_with_cpu_fallback(
                embeddings_cmd,
                stage="build-video-embeddings",
                cwd=paths.repo_root,
                runner=command_runner,
            )
            if args.inject_replace_embedding_for_test:
                inject_replace_embedding_for_test(
                    prod_db=paths.prod_db, staging_db=paths.staging_db
                )

            if availability:
                # One invocation scope survives operator-file deletion and embeddings.
                scoped_hosts = parent_scope
                deltas = count_staging_deltas(
                    paths.prod_db, paths.staging_db, scoped_hosts=scoped_hosts, json_host_scope=True
                )
            else:
                scoped_hosts = (
                    parent_scope
                )
                logging.info("staging delta summary start scoped_hosts=%d", len(scoped_hosts))
                deltas = count_staging_deltas(
                    paths.prod_db, paths.staging_db, scoped_hosts=scoped_hosts
                )
            logging.info(
                "staging delta instances=%d channels=%d videos=%d embeddings=%d",
                deltas["instances_new"],
                deltas["channels_new"],
                deltas["videos_new"],
                deltas["embeddings_new"],
            )

            if args.fail_before_merge:
                raise RuntimeError("Injected failure: before merge stage")

            try:
                if not args.skip_systemctl:
                    run_cmd(
                        systemctl_cmd(
                            systemctl_bin=args.systemctl_bin,
                            service_name=args.service_name,
                            action="stop",
                            use_sudo=args.systemctl_use_sudo,
                        ),
                        cwd=None,
                        runner=command_runner,
                    )
                    service_stopped = True

                if sync_stale_hosts:
                    stale_applied = purge_hosts(
                        prod_db=paths.prod_db,
                        similarity_db=paths.similarity_db,
                        hosts=sync_stale_hosts,
                        dry_run=False,
                    )
                    logging.info(
                        "sync-join stale purge hosts=%d deleted=%s",
                        len(sync_stale_hosts),
                        stale_applied,
                    )

                if parent_scope_file is None:
                    # An empty scoped publication is never an unscoped merge.
                    parent_scope_file = write_hosts_file(
                        set(), "ptb-parent-empty-", allow_empty=True
                    )
                    if parent_scope_file is None:
                        raise RuntimeError("Failed to freeze parent-health publication scope")
                    temp_files.append(parent_scope_file)
                run_cmd(
                    [
                        args.python_bin,
                        (paths.script_dir / "merge-staging-db.py").as_posix(),
                        "--prod-db",
                        paths.prod_db.as_posix(),
                        "--staging-db",
                        paths.staging_db.as_posix(),
                        "--rules",
                        paths.merge_rules.as_posix(),
                        "--parent-health-hosts-file", parent_scope_file.as_posix(),
                        *(["--availability-sweep-report-json", json.dumps(report, sort_keys=True)]
                          if apply_availability else []),
                    ],
                    cwd=paths.repo_root,
                    runner=command_runner,
                )

                if denied_hosts:
                    safety_prune = purge_hosts(
                        prod_db=paths.prod_db,
                        similarity_db=paths.similarity_db,
                        hosts=denied_hosts,
                        dry_run=False,
                    )
                    if safety_prune:
                        logging.info("post-merge denylist safety prune=%s", safety_prune)

                # Merge and availability are published by one merger transaction.
                # No second writer may commit canonical availability separately.

                run_cmd(
                    [
                        args.python_bin,
                        (paths.script_dir / "recompute-popularity.py").as_posix(),
                        "--db",
                        paths.prod_db.as_posix(),
                        "--incremental",
                    ],
                    cwd=paths.repo_root,
                    runner=command_runner,
                )
                run_cmd(
                    [
                        args.python_bin,
                        (paths.script_dir / "rebuild-video-discovery-data.py").as_posix(),
                        "--db",
                        paths.prod_db.as_posix(),
                    ],
                    cwd=paths.repo_root,
                    runner=command_runner,
                )
                run_cmd(
                    [
                        args.python_bin,
                        (paths.script_dir / "sync-video-index-ids.py").as_posix(),
                        "--db",
                        paths.prod_db.as_posix(),
                    ],
                    cwd=paths.repo_root,
                    runner=command_runner,
                )
                # Search v1 is a full-rebuild artifact: it depends on merged video
                # rows but not on ANN, random-cache, or similarity artifacts.
                run_cmd(
                    [
                        args.python_bin,
                        (paths.script_dir / "rebuild-video-search-index.py").as_posix(),
                        "--db",
                        paths.prod_db.as_posix(),
                    ],
                    cwd=paths.repo_root,
                    runner=command_runner,
                )
                if args.fail_during_ann_build:
                    raise RuntimeError("Injected failure: ANN build stage")
                ann_cmd = [
                    args.python_bin,
                    (paths.script_dir / "build-ann-index.py").as_posix(),
                    "--db-path",
                    paths.prod_db.as_posix(),
                    "--index-path",
                    paths.index_path.as_posix(),
                    "--meta-path",
                    paths.index_meta_path.as_posix(),
                    "--normalize",
                    "--nlist",
                    str(args.nlist),
                ]
                if args.use_gpu:
                    ann_cmd.append("--gpu")
                else:
                    ann_cmd.append("--cpu")
                run_with_cpu_fallback(
                    ann_cmd,
                    stage="build-ann-index",
                    cwd=paths.repo_root,
                    runner=command_runner,
                )
                # Updater/data-build is the sole production writer of the Random
                # artifact. Engine is stopped here, so copy-on-publish replacement is
                # an offline operation and runtime never hot-reloads a new generation.
                random_cache_cmd = [
                    args.python_bin,
                    (paths.script_dir / "precompute-random-index-ids.py").as_posix(),
                    "--db",
                    paths.prod_db.as_posix(),
                    "--out",
                    paths.random_cache_db.as_posix(),
                    "--size",
                    str(DEFAULT_RANDOM_CACHE_SIZE),
                    "--refresh",
                ]
                if DEFAULT_RANDOM_CACHE_FILTERED_MODE:
                    random_cache_cmd.extend(
                        [
                            "--filtered",
                            "--max-per-author",
                            str(DEFAULT_RANDOM_CACHE_MAX_PER_AUTHOR),
                            "--max-per-instance",
                            str(DEFAULT_RANDOM_CACHE_MAX_PER_INSTANCE),
                        ]
                    )
                run_cmd(random_cache_cmd, cwd=paths.repo_root, runner=command_runner)

                if args.fail_after_merge_before_similarity:
                    raise RuntimeError(
                        "Injected failure: after merge/ANN and before similarity precompute"
                    )
                precompute_cmd = [
                    args.python_bin,
                    (paths.script_dir / "precompute-similar-ann.py").as_posix(),
                    "--db",
                    paths.prod_db.as_posix(),
                    "--index",
                    paths.index_path.as_posix(),
                    "--out",
                    paths.similarity_db.as_posix(),
                    "--top-k",
                    "1000",
                    "--nprobe",
                    "16",
                    "--search-batch-size",
                    "1024",
                    # Refresh mode must retain the existing source set: the
                    # similarity job selects its work from similarity_sources.
                    # Recreating the DB here would erase that set first and
                    # silently turn every updater refresh into a no-op.
                    "--refresh-existing",
                ]
                if args.use_gpu:
                    precompute_cmd.extend(["--gpu", "--gpu-device", "0"])
                else:
                    precompute_cmd.append("--cpu")
                run_with_cpu_fallback(
                    precompute_cmd,
                    stage="precompute-similar-ann",
                    cwd=paths.repo_root,
                    runner=command_runner,
                )
            finally:
                if service_stopped and not args.skip_systemctl:
                    if _prepared_discovery_is_available(paths.prod_db):
                        run_cmd(
                            systemctl_cmd(
                                systemctl_bin=args.systemctl_bin,
                                service_name=args.service_name,
                                action="start",
                                use_sudo=args.systemctl_use_sudo,
                            ),
                            cwd=None,
                            runner=command_runner,
                        )
                        service_stopped = False
                    else:
                        logging.error(
                            "Engine remains stopped: prepared Discovery is unavailable in %s",
                            paths.prod_db,
                        )
    finally:
        for temp_path in temp_files:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                logging.warning("failed to remove temp file: %s", temp_path)

    total_ms = int((time.monotonic() - pipeline_start) * 1000)
    logging.info("worker completed in %dms", total_ms)
