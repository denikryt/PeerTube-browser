"""Updater pipeline orchestration and command construction.

This module preserves the historical updater stage order while moving the large
operational flow out of ``updater-worker.py``.  Tests inject fake command
runners and monkeypatch helper boundaries; production defaults still call the
same subprocess jobs and crawler CLIs.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .commands import CommandRun, run_cmd, run_with_cpu_fallback, systemctl_cmd
from .locks import single_run_lock
from .paths import from_args, validate_required_files
from .staging import (
    count_staging_deltas,
    init_staging_db,
    inject_replace_embedding_for_test,
    prune_staging_local_non_ok_instances,
    seed_staging_from_prod,
)
from .sync import (
    fetch_join_hosts,
    list_prod_hosts,
    load_denied_hosts,
    purge_hosts,
    purge_hosts_from_staging,
    write_hosts_file,
)


def _run_cmd(cmd: list[str], *, cwd: Path | None, runner: CommandRun | None) -> None:
    """Run a command through the injectable shell boundary."""

    run_cmd(cmd, cwd=cwd, runner=runner)


def _run_with_fallback(
    cmd: list[str], *, stage: str, cwd: Path | None, runner: CommandRun | None
) -> None:
    """Run a GPU-aware command through the injectable shell boundary."""

    run_with_cpu_fallback(cmd, stage=stage, cwd=cwd, runner=runner)


def run_pipeline(
    args, *, command_runner: CommandRun | None = None, validate_files: bool = True
) -> None:
    """Run the updater pipeline with current stage order and compatibility behavior."""

    paths = from_args(args)
    if validate_files:
        validate_required_files(paths)

    logging.info("worker start prod_db=%s staging_db=%s", paths.prod_db, paths.staging_db)
    service_stopped = False
    pipeline_start = time.monotonic()
    if args.dry_run and not args.sync_join_whitelist:
        raise RuntimeError("--dry-run is supported only together with --sync-join-whitelist.")

    temp_files: list[Path] = []
    try:
        with single_run_lock(paths.lock_file):
            denied_hosts = load_denied_hosts(paths.prod_db)
            logging.info("moderation deny_hosts_active=%d", len(denied_hosts))

            sync_new_hosts: set[str] = set()
            sync_stale_hosts: set[str] = set()
            if args.sync_join_whitelist:
                join_hosts = fetch_join_hosts(args.whitelist_url)
                effective_join_hosts = join_hosts - denied_hosts
                prod_hosts = list_prod_hosts(paths.prod_db)
                sync_stale_hosts = prod_hosts - effective_join_hosts
                sync_new_hosts = effective_join_hosts - prod_hosts
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

            if args.resume_staging and paths.staging_db.exists():
                logging.info("staging reused from previous run: %s", paths.staging_db)
            else:
                init_staging_db(paths.staging_db, paths.schema_path)
                logging.info("staging initialized")
                if not args.sync_join_whitelist:
                    seed_staging_from_prod(paths.prod_db, paths.staging_db)
                    logging.info("staging seeded from prod (instances + channels)")

            if denied_hosts:
                staging_prune = purge_hosts_from_staging(paths.staging_db, denied_hosts)
                if staging_prune:
                    logging.info("staging denylist prune=%s", staging_prune)

            exclude_hosts_file = write_hosts_file(denied_hosts, "ptb-exclude-hosts-")
            if exclude_hosts_file is not None:
                temp_files.append(exclude_hosts_file)
            whitelist_hosts_file = None
            if args.sync_join_whitelist:
                whitelist_hosts_file = write_hosts_file(sync_new_hosts, "ptb-whitelist-hosts-")
                if whitelist_hosts_file is not None:
                    temp_files.append(whitelist_hosts_file)

            run_crawl_stages = (not args.sync_join_whitelist) or bool(sync_new_hosts)
            if run_crawl_stages:
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
                    "--timeout",
                    str(args.timeout_ms),
                    "--max-retries",
                    str(args.max_retries),
                ]
                if whitelist_hosts_file is not None:
                    instances_cmd.extend(["--whitelist-file", whitelist_hosts_file.as_posix()])
                else:
                    instances_cmd.extend(["--whitelist-url", args.whitelist_url])
                if exclude_hosts_file is not None:
                    instances_cmd.extend(["--exclude-hosts-file", exclude_hosts_file.as_posix()])
                _run_cmd(instances_cmd, cwd=paths.crawler_dir, runner=command_runner)

                if args.skip_local_dead:
                    prune_staging_local_non_ok_instances(
                        prod_db=paths.prod_db, staging_db=paths.staging_db
                    )

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
                    "--timeout",
                    str(args.timeout_ms),
                    "--max-retries",
                    str(args.max_retries),
                ]
                if exclude_hosts_file is not None:
                    channels_cmd.extend(["--exclude-hosts-file", exclude_hosts_file.as_posix()])
                _run_cmd(channels_cmd, cwd=paths.crawler_dir, runner=command_runner)

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
                    "--timeout",
                    str(args.timeout_ms),
                    "--max-retries",
                    str(args.max_retries),
                ]
                if exclude_hosts_file is not None:
                    videos_cmd.extend(["--exclude-hosts-file", exclude_hosts_file.as_posix()])
                _run_cmd(videos_cmd, cwd=paths.crawler_dir, runner=command_runner)

                counts_cmd = [
                    args.node_bin,
                    (paths.crawler_dist / "channels-videos-count-cli.js").as_posix(),
                    "--db",
                    paths.staging_db.as_posix(),
                    "--resume",
                    "--concurrency",
                    str(args.concurrency),
                    "--timeout",
                    str(args.timeout_ms),
                    "--max-retries",
                    str(args.max_retries),
                ]
                if exclude_hosts_file is not None:
                    counts_cmd.extend(["--exclude-hosts-file", exclude_hosts_file.as_posix()])
                _run_cmd(counts_cmd, cwd=paths.crawler_dir, runner=command_runner)

                embeddings_cmd = [
                    args.python_bin,
                    (paths.script_dir / "build-video-embeddings.py").as_posix(),
                    "--db-path",
                    paths.staging_db.as_posix(),
                ]
                if args.use_gpu:
                    embeddings_cmd.append("--gpu")
                else:
                    embeddings_cmd.append("--cpu")
                _run_with_fallback(
                    embeddings_cmd,
                    stage="build-video-embeddings",
                    cwd=paths.repo_root,
                    runner=command_runner,
                )
                if args.inject_replace_embedding_for_test:
                    inject_replace_embedding_for_test(
                        prod_db=paths.prod_db, staging_db=paths.staging_db
                    )

                deltas = count_staging_deltas(paths.prod_db, paths.staging_db)
                logging.info(
                    "staging delta instances=%d channels=%d videos=%d embeddings=%d",
                    deltas["instances_new"],
                    deltas["channels_new"],
                    deltas["videos_new"],
                    deltas["embeddings_new"],
                )
            else:
                logging.info("sync-join ingest skipped: no new hosts after denylist filtering")
                if not sync_stale_hosts:
                    logging.info("sync-join no changes detected; finishing early")
                    return

            if args.fail_before_merge:
                raise RuntimeError("Injected failure: before merge stage")

            try:
                if not args.skip_systemctl:
                    _run_cmd(
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

                _run_cmd(
                    [
                        args.python_bin,
                        (paths.script_dir / "merge-staging-db.py").as_posix(),
                        "--prod-db",
                        paths.prod_db.as_posix(),
                        "--staging-db",
                        paths.staging_db.as_posix(),
                        "--rules",
                        paths.merge_rules.as_posix(),
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

                _run_cmd(
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
                _run_with_fallback(
                    ann_cmd,
                    stage="build-ann-index",
                    cwd=paths.repo_root,
                    runner=command_runner,
                )
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
                    paths.index_path.as_posix(),
                    "--out",
                    paths.similarity_db.as_posix(),
                    "--top-k",
                    "1000",
                    "--nprobe",
                    "16",
                    "--search-batch-size",
                    "1024",
                    "--recreate-out-db",
                    "--refresh-existing",
                ]
                if args.use_gpu:
                    precompute_cmd.extend(["--gpu", "--gpu-device", "0"])
                else:
                    precompute_cmd.append("--cpu")
                _run_with_fallback(
                    precompute_cmd,
                    stage="precompute-similar-ann",
                    cwd=paths.repo_root,
                    runner=command_runner,
                )
            finally:
                if service_stopped and not args.skip_systemctl:
                    _run_cmd(
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
    finally:
        for temp_path in temp_files:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                logging.warning("failed to remove temp file: %s", temp_path)

    total_ms = int((time.monotonic() - pipeline_start) * 1000)
    logging.info("worker completed in %dms", total_ms)
