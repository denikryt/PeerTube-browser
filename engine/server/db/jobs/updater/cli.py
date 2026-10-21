"""CLI parsing and default resolution for the updater worker.

The module preserves the existing flags, defaults, and installer fallback logic
while making parser construction testable through an optional argv parameter.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .paths import JOBS_DIR, REPO_ROOT, SERVER_DIR

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from scripts.cli_format import CompactHelpFormatter  # noqa: E402


def resolve_default_engine_service_name(mode: str) -> str:
    """Resolve the default Engine service name with existing installer fallbacks."""

    installer = (REPO_ROOT / "engine" / "install-updater-service.sh").resolve()
    if not installer.exists():
        installer = (REPO_ROOT / "engine" / "install-engine-service.sh").resolve()
    if not installer.exists():
        return "peertube-engine-dev" if mode == "dev" else "peertube-engine"
    try:
        output = subprocess.check_output(
            ["bash", installer.as_posix(), "--mode", mode, "--print-default-engine-service-name"],
            text=True,
        )
    except Exception:
        if installer.name == "install-engine-service.sh":
            try:
                output = subprocess.check_output(
                    ["bash", installer.as_posix(), "--mode", mode, "--print-default-service-name"],
                    text=True,
                )
            except Exception:
                return "peertube-engine-dev" if mode == "dev" else "peertube-engine"
        else:
            return "peertube-engine-dev" if mode == "dev" else "peertube-engine"
    service_name = output.strip()
    if service_name:
        return service_name
    if mode == "dev":
        return "peertube-engine-dev"
    return "peertube-engine"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse updater CLI args while preserving current defaults and meanings."""

    api_dir = REPO_ROOT / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH, DEFAULT_INDEX_PATH, DEFAULT_SIMILARITY_DB_PATH

    default_prod = (REPO_ROOT / DEFAULT_DB_PATH).resolve()
    default_stage = (REPO_ROOT / "engine/server/db/staging-worker.db").resolve()
    default_index = (REPO_ROOT / DEFAULT_INDEX_PATH).resolve()
    default_index_meta = default_index.with_suffix(default_index.suffix + ".json")
    default_similarity = (REPO_ROOT / DEFAULT_SIMILARITY_DB_PATH).resolve()
    default_rules = (JOBS_DIR / "merge_rules.json").resolve()
    default_logs = (REPO_ROOT / "engine/server/db/updater-worker.log").resolve()
    default_lock = Path("/tmp/peertube-browser-staging-sync.lock")

    parser = argparse.ArgumentParser(
        description=(
            "Run staging ingest pipeline: crawl -> embeddings -> stop service -> "
            "merge -> incremental jobs -> full ANN rebuild -> start service."
        ),
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument("--prod-db", default=str(default_prod), help="Path to prod DB.")
    parser.add_argument("--staging-db", default=str(default_stage), help="Path to staging DB.")
    parser.add_argument(
        "--resume-staging",
        action="store_true",
        help=(
            "Reuse existing staging DB and crawler progress tables instead of "
            "recreating staging from scratch."
        ),
    )
    parser.add_argument("--index-path", default=str(default_index), help="Path to ANN index file.")
    parser.add_argument(
        "--index-meta-path", default=str(default_index_meta), help="Path to ANN metadata json file."
    )
    parser.add_argument(
        "--similarity-db", default=str(default_similarity), help="Path to similarity cache DB."
    )
    parser.add_argument(
        "--merge-rules", default=str(default_rules), help="Path to merge_rules.json."
    )
    parser.add_argument(
        "--mode",
        default="prod",
        choices=("prod", "dev"),
        help="Contour mode used to resolve default Engine service name.",
    )
    parser.add_argument(
        "--service-name", default=None, help="Systemd service name to stop/start during merge."
    )
    parser.add_argument(
        "--systemctl-bin", default="systemctl", help="Systemctl executable path/name."
    )
    parser.add_argument(
        "--systemctl-use-sudo",
        action="store_true",
        help="Run service stop/start as 'sudo -n <systemctl>'.",
    )
    parser.add_argument(
        "--skip-systemctl", action="store_true", help="Do not stop/start service automatically."
    )
    parser.add_argument("--logs", default=str(default_logs), help="Path to log file.")
    parser.add_argument(
        "--lock-file", default=str(default_lock), help="Lock file path to prevent overlapping runs."
    )
    parser.add_argument(
        "--crawler-dir",
        default=str((REPO_ROOT / "engine" / "crawler").resolve()),
        help="Path to crawler directory (must contain dist/*.js CLIs).",
    )
    parser.add_argument("--node-bin", default="node", help="Node executable.")
    parser.add_argument(
        "--python-bin", default=sys.executable, help="Python executable for DB jobs."
    )
    parser.add_argument("--concurrency", type=int, default=4, help="Crawler concurrency.")
    parser.add_argument("--timeout-ms", type=int, default=5000, help="HTTP timeout in ms.")
    parser.add_argument("--max-retries", type=int, default=3, help="HTTP retries.")
    parser.add_argument(
        "--videos-stop-after-full-pages",
        type=int,
        default=2,
        help="Early-stop threshold for videos CLI in new-only mode.",
    )
    parser.add_argument(
        "--max-instances",
        type=int,
        default=0,
        help="Test-only cap for number of instances processed by crawler CLIs (0 = no limit).",
    )
    parser.add_argument(
        "--max-channels",
        type=int,
        default=0,
        help="Test-only cap for number of channels processed by crawler CLIs (0 = no limit).",
    )
    parser.add_argument(
        "--max-videos-pages",
        type=int,
        default=0,
        help="Test-only cap for pages fetched per channel in videos crawl (0 = no limit).",
    )
    parser.add_argument(
        "--whitelist-url",
        default="https://instances.joinpeertube.org/api/v1/instances/hosts?count=5000&healthy=true",
        help="Whitelist URL for instances crawl.",
    )
    parser.add_argument(
        "--sync-join-whitelist",
        action="store_true",
        help=(
            "Strict sync mode: reconcile prod hosts with JoinPeerTube and "
            "ingest only missing hosts."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive host purge in --sync-join-whitelist mode.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print sync/purge plan and exit (only with --sync-join-whitelist).",
    )
    parser.add_argument(
        "--skip-local-dead",
        action="store_true",
        help=(
            "Before channels crawl, drop staging instances that are marked "
            "non-ok in local prod DB (instances.health_status != 'ok')."
        ),
    )
    parser.add_argument("--nlist", type=int, default=4096, help="FAISS nlist for ANN build step.")
    parser.add_argument(
        "--inject-replace-embedding-for-test",
        action="store_true",
        help=(
            "Test-only: inject one overlapping video_embeddings row into "
            "staging to validate INSERT_OR_REPLACE merge behavior."
        ),
    )
    parser.add_argument(
        "--fail-before-merge",
        action="store_true",
        help="Test-only: inject failure before merge stage.",
    )
    parser.add_argument(
        "--fail-during-ann-build",
        action="store_true",
        help="Test-only: inject failure at ANN build stage.",
    )
    parser.add_argument(
        "--fail-after-merge-before-similarity",
        action="store_true",
        help="Test-only: inject failure after merge/ANN and before similarity precompute.",
    )
    accel_group = parser.add_mutually_exclusive_group()
    accel_group.add_argument(
        "--gpu",
        dest="use_gpu",
        action="store_true",
        help=(
            "Run embeddings + FAISS build in GPU mode. If a GPU stage fails, "
            "updater retries that stage in CPU mode."
        ),
    )
    accel_group.add_argument(
        "--cpu",
        dest="use_gpu",
        action="store_false",
        help="Run embeddings + FAISS build in CPU mode only.",
    )
    parser.set_defaults(use_gpu=True)
    args = parser.parse_args(argv)
    if not args.service_name:
        args.service_name = resolve_default_engine_service_name(args.mode)
    return args
