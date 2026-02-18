#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR/..}"

MODE="prod"
ENGINE_SERVICE_NAME=""
DRY_RUN=0

print_usage() {
  cat <<'EOF_USAGE'
Usage: sudo ./engine/uninstall-engine-service.sh [options]

Uninstall Engine systemd service for prod/dev contour.

Options:
  --mode <prod|dev>         Contour mode (default: prod)
  --project-dir <path>      Project root path (accepted for symmetry)
  --service-name <name>     Override Engine unit base name (default: peertube-engine[-dev])
  --dry-run                 Print planned actions without changing system files
  -h, --help                Show this help
EOF_USAGE
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

log_lifecycle() {
  local message="$1"
  echo "${message}"
  if command -v logger >/dev/null 2>&1; then
    logger -t peertube-service-lifecycle "${message}" || true
  fi
}

validate_mode() {
  case "${MODE}" in
    prod|dev) ;;
    *) fail "Invalid --mode: ${MODE} (expected prod|dev)" ;;
  esac
}

validate_service_name() {
  local name="$1"
  [[ -n "${name}" ]] || fail "Service name cannot be empty"
  [[ "${name}" =~ ^[a-zA-Z0-9_.@-]+$ ]] || fail "Invalid service name: ${name}"
}

quoted_cmd() {
  local out=""
  local arg
  for arg in "$@"; do
    out+="$(printf '%q' "${arg}") "
  done
  printf '%s' "${out% }"
}

run_cmd() {
  if (( DRY_RUN == 1 )); then
    echo "[dry-run] $(quoted_cmd "$@")"
    return 0
  fi
  "$@"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --project-dir)
      PROJECT_DIR="${2:-}"
      shift 2
      ;;
    --service-name)
      ENGINE_SERVICE_NAME="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

validate_mode
PROJECT_DIR="$(realpath "${PROJECT_DIR}")"
[[ -d "${PROJECT_DIR}" ]] || fail "Project directory not found: ${PROJECT_DIR}"

if [[ -z "${ENGINE_SERVICE_NAME}" ]]; then
  if [[ "${MODE}" == "prod" ]]; then
    ENGINE_SERVICE_NAME="peertube-engine"
  else
    ENGINE_SERVICE_NAME="peertube-engine-dev"
  fi
fi
validate_service_name "${ENGINE_SERVICE_NAME}"

UNIT_PATH="/etc/systemd/system/${ENGINE_SERVICE_NAME}.service"

if (( DRY_RUN == 1 )); then
  echo "[dry-run] uninstall-engine-service"
  echo "  mode=${MODE}"
  echo "  service=${ENGINE_SERVICE_NAME}"
  echo "  unit=${UNIT_PATH}"
fi

if (( DRY_RUN == 0 )); then
  [[ "${EUID}" -eq 0 ]] || fail "Run as root (use sudo)."
  require_cmd systemctl
fi

log_lifecycle "[engine-uninstall] begin service=${ENGINE_SERVICE_NAME}.service mode=${MODE}"
log_lifecycle "[engine-uninstall] stopping service=${ENGINE_SERVICE_NAME}.service"
run_cmd systemctl stop "${ENGINE_SERVICE_NAME}.service" >/dev/null 2>&1 || true
log_lifecycle "[engine-uninstall] disabling service=${ENGINE_SERVICE_NAME}.service"
run_cmd systemctl disable "${ENGINE_SERVICE_NAME}.service" >/dev/null 2>&1 || true
run_cmd rm -f "${UNIT_PATH}"

if (( DRY_RUN == 0 )); then
  systemctl daemon-reload
  systemctl reset-failed "${ENGINE_SERVICE_NAME}.service" >/dev/null 2>&1 || true
fi

echo "Engine service removed: ${ENGINE_SERVICE_NAME}.service"
log_lifecycle "[engine-uninstall] removed service=${ENGINE_SERVICE_NAME}.service mode=${MODE}"
