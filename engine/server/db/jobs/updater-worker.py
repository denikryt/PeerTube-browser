#!/usr/bin/env python3
"""Compatibility CLI wrapper for the updater worker.

The executable path is intentionally stable for systemd, installer, and manual
operator workflows.  Stage 9 moves operational internals into
``engine.server.db.jobs.updater`` modules while this wrapper keeps import-path and
CLI compatibility for existing scripts.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from updater.cli import parse_args, resolve_default_engine_service_name  # noqa: E402
from updater.commands import (  # noqa: E402
    _to_cpu_cmd,
    run_cmd,
    run_with_cpu_fallback,
    systemctl_cmd,
)
from updater.locks import _pid_alive, single_run_lock  # noqa: E402
from updater.pipeline import run_pipeline  # noqa: E402
from updater.staging import (  # noqa: E402
    count_staging_deltas,
    init_staging_db,
    inject_replace_embedding_for_test,
    prune_staging_local_non_ok_instances,
    remove_db_with_sidecars,
    seed_staging_from_prod,
    shared_columns,
)
from updater.sync import (  # noqa: E402
    fetch_join_hosts,
    list_prod_hosts,
    load_denied_hosts,
    purge_hosts,
    purge_hosts_from_staging,
    write_hosts_file,
)

__all__ = [
    "_pid_alive",
    "_to_cpu_cmd",
    "count_staging_deltas",
    "fetch_join_hosts",
    "init_staging_db",
    "inject_replace_embedding_for_test",
    "list_prod_hosts",
    "load_denied_hosts",
    "main",
    "parse_args",
    "prune_staging_local_non_ok_instances",
    "purge_hosts",
    "purge_hosts_from_staging",
    "remove_db_with_sidecars",
    "resolve_default_engine_service_name",
    "run_cmd",
    "run_with_cpu_fallback",
    "seed_staging_from_prod",
    "setup_logging",
    "shared_columns",
    "single_run_lock",
    "systemctl_cmd",
    "write_hosts_file",
]


def setup_logging(log_path: Path) -> None:
    """Configure current updater stdout and file logging behavior."""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, "a")]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def main() -> None:
    """Parse CLI args, configure logging, and run the updater pipeline."""

    args = parse_args()
    setup_logging(Path(args.logs).resolve())
    run_pipeline(args)


if __name__ == "__main__":
    main()
