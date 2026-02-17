#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_INSTALL="${SCRIPT_DIR}/install-service.sh"

PROJECT_DIR=""
PROJECT_DIR_SET=0
FORCE_REINSTALL=0
WITH_UPDATER_TIMER=0
DRY_RUN=0

print_usage() {
  cat <<'EOF_USAGE'
Usage: sudo ./install-service-dev.sh [options] [-- <extra install-service.sh args>]

Dev preset wrapper over install-service.sh.
Defaults:
- mode=dev
- force reinstall disabled
- updater timer disabled

Options:
  --project-dir <path>      Override project dir
  --with-updater-timer      Enable updater timer in dev run
  --without-updater-timer   Disable updater timer in dev run (default)
  --no-force                Disable force reinstall (default)
  --force                   Enable force reinstall
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
    --with-updater-timer)
      WITH_UPDATER_TIMER=1
      shift
      ;;
    --without-updater-timer)
      WITH_UPDATER_TIMER=0
      shift
      ;;
    --no-force)
      FORCE_REINSTALL=0
      shift
      ;;
    --force)
      FORCE_REINSTALL=1
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
  "${BASE_INSTALL}"
  --mode dev
)

if [[ "${PROJECT_DIR_SET}" -eq 1 ]]; then
  CMD+=(--project-dir "${PROJECT_DIR}")
fi

if [[ "${WITH_UPDATER_TIMER}" -eq 1 ]]; then
  CMD+=(--with-updater-timer)
else
  CMD+=(--without-updater-timer)
fi

if [[ "${FORCE_REINSTALL}" -eq 1 ]]; then
  CMD+=(--force)
else
  CMD+=(--no-force)
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  CMD+=(--dry-run)
fi

CMD+=("${EXTRA_ARGS[@]}")
exec "${CMD[@]}"
