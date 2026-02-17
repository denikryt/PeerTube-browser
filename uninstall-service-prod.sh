#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_UNINSTALL="${SCRIPT_DIR}/uninstall-service.sh"

PROJECT_DIR=""
PROJECT_DIR_SET=0
PURGE_UPDATER_STATE=0
DRY_RUN=0

print_usage() {
  cat <<'EOF_USAGE'
Usage: sudo ./uninstall-service-prod.sh [options] [-- <extra uninstall-service.sh args>]

Prod preset wrapper over uninstall-service.sh.
Defaults:
- mode=prod
- keep updater state

Options:
  --project-dir <path>      Override project dir
  --purge-updater-state     Remove prod updater state artifacts
  --keep-updater-state      Keep updater state artifacts (default)
  --dry-run                 Forward dry-run mode
  -h, --help                Show this help
EOF_USAGE
}

EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      PROJECT_DIR="${2:-}"
      PROJECT_DIR_SET=1
      shift 2
      ;;
    --purge-updater-state)
      PURGE_UPDATER_STATE=1
      shift
      ;;
    --keep-updater-state)
      PURGE_UPDATER_STATE=0
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    --)
      shift
      EXTRA_ARGS+=("$@")
      break
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

CMD=(
  bash
  "${BASE_UNINSTALL}"
  --mode prod
)

if [[ "${PROJECT_DIR_SET}" -eq 1 ]]; then
  CMD+=(--project-dir "${PROJECT_DIR}")
fi

if [[ "${PURGE_UPDATER_STATE}" -eq 1 ]]; then
  CMD+=(--purge-updater-state)
else
  CMD+=(--keep-updater-state)
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  CMD+=(--dry-run)
fi

CMD+=("${EXTRA_ARGS[@]}")
exec "${CMD[@]}"
