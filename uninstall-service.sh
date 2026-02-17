#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"

MODE="prod" # prod | dev | all
DRY_RUN=0
PURGE_UPDATER_STATE=0

ENGINE_SERVICE_NAME=""
CLIENT_SERVICE_NAME=""
UPDATER_SERVICE_NAME=""
UPDATER_TIMER_NAME=""
UPDATER_WEEK_STATE_DIR=""

ENGINE_SERVICE_NAME_SET=0
CLIENT_SERVICE_NAME_SET=0
UPDATER_SERVICE_NAME_SET=0
UPDATER_TIMER_NAME_SET=0
UPDATER_WEEK_STATE_DIR_SET=0

DEFAULT_PROD_ENGINE_SERVICE="peertube-engine"
DEFAULT_PROD_CLIENT_SERVICE="peertube-client"
DEFAULT_PROD_UPDATER_SERVICE="peertube-updater"
DEFAULT_PROD_UPDATER_TIMER="peertube-updater"
DEFAULT_PROD_UPDATER_STATE_DIR="/var/lib/peertube-browser"

DEFAULT_DEV_ENGINE_SERVICE="peertube-engine-dev"
DEFAULT_DEV_CLIENT_SERVICE="peertube-client-dev"
DEFAULT_DEV_UPDATER_SERVICE="peertube-updater-dev"
DEFAULT_DEV_UPDATER_TIMER="peertube-updater-dev"
DEFAULT_DEV_UPDATER_STATE_DIR="/var/lib/peertube-browser-dev"

print_usage() {
  cat <<'EOF_USAGE'
Usage: sudo ./uninstall-service.sh [options]

Centralized uninstaller for Engine + Client contours.

Modes:
  --mode prod      Uninstall prod contour (default)
  --mode dev       Uninstall dev contour
  --mode all       Uninstall both prod and dev contours sequentially

Options:
  --mode <prod|dev|all>       Uninstall contour mode
  --contour <prod|dev|all>    Alias for --mode
  --project-dir <path>        Project root path (default: script directory)

  --engine-service-name <name>  Engine unit base name override (single-contour mode only)
  --client-service-name <name>  Client unit base name override (single-contour mode only)
  --updater-service-name <name> Updater service base name override (single-contour mode only)
  --updater-timer-name <name>   Updater timer base name override (single-contour mode only)
  --updater-week-state-dir <path> Updater week-state directory override (single-contour mode only)

  --purge-updater-state       Remove contour updater week-state file/empty dir
  --keep-updater-state        Keep updater week-state artifacts (default)
  --dry-run                   Print actions without changing system files
  -h, --help                  Show this help
EOF_USAGE
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

validate_mode() {
  case "${MODE}" in
    prod|dev|all) ;;
    *) fail "Invalid --mode: ${MODE} (expected prod|dev|all)" ;;
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

resolve_default_engine_service() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_ENGINE_SERVICE}"
  else
    printf '%s' "${DEFAULT_DEV_ENGINE_SERVICE}"
  fi
}

resolve_default_client_service() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_CLIENT_SERVICE}"
  else
    printf '%s' "${DEFAULT_DEV_CLIENT_SERVICE}"
  fi
}

resolve_default_updater_service() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_UPDATER_SERVICE}"
  else
    printf '%s' "${DEFAULT_DEV_UPDATER_SERVICE}"
  fi
}

resolve_default_updater_timer() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_UPDATER_TIMER}"
  else
    printf '%s' "${DEFAULT_DEV_UPDATER_TIMER}"
  fi
}

resolve_default_updater_state_dir() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_UPDATER_STATE_DIR}"
  else
    printf '%s' "${DEFAULT_DEV_UPDATER_STATE_DIR}"
  fi
}

ensure_single_contour_overrides_only() {
  if [[ "${MODE}" != "all" ]]; then
    return
  fi
  if (( ENGINE_SERVICE_NAME_SET == 1 || CLIENT_SERVICE_NAME_SET == 1 || UPDATER_SERVICE_NAME_SET == 1 || UPDATER_TIMER_NAME_SET == 1 || UPDATER_WEEK_STATE_DIR_SET == 1 )); then
    fail "Contour-specific overrides are not allowed with --mode all. Run per contour or use defaults."
  fi
}

uninstall_updater_for_contour() {
  local contour="$1"
  local updater_service_name="$2"
  local updater_timer_name="$3"
  local week_state_dir="$4"

  local updater_unit_path="/etc/systemd/system/${updater_service_name}.service"
  local updater_timer_path="/etc/systemd/system/${updater_timer_name}.timer"
  local updater_sudoers_path="/etc/sudoers.d/${updater_service_name}-systemctl"
  local week_state_file="${week_state_dir}/updater-last-success-week.txt"

  validate_service_name "${updater_service_name}"
  validate_service_name "${updater_timer_name}"

  echo "[uninstall-service] ${contour}: removing updater ${updater_service_name}.service / ${updater_timer_name}.timer"
  run_cmd systemctl stop "${updater_timer_name}.timer" >/dev/null 2>&1 || true
  run_cmd systemctl stop "${updater_service_name}.service" >/dev/null 2>&1 || true
  run_cmd systemctl disable "${updater_timer_name}.timer" >/dev/null 2>&1 || true
  run_cmd rm -f "${updater_timer_path}"
  run_cmd rm -f "${updater_unit_path}"
  run_cmd rm -f "${updater_sudoers_path}"

  if (( PURGE_UPDATER_STATE == 1 )); then
    echo "[uninstall-service] ${contour}: purging updater state ${week_state_file}"
    run_cmd rm -f "${week_state_file}"
    run_cmd rmdir "${week_state_dir}" >/dev/null 2>&1 || true
  fi

  if (( DRY_RUN == 0 )); then
    systemctl daemon-reload
    systemctl reset-failed "${updater_service_name}.service" >/dev/null 2>&1 || true
    systemctl reset-failed "${updater_timer_name}.timer" >/dev/null 2>&1 || true
  fi
}

uninstall_contour() {
  local contour="$1"

  local engine_service_name
  local client_service_name
  local updater_service_name
  local updater_timer_name
  local week_state_dir

  engine_service_name="$(resolve_default_engine_service "${contour}")"
  client_service_name="$(resolve_default_client_service "${contour}")"
  updater_service_name="$(resolve_default_updater_service "${contour}")"
  updater_timer_name="$(resolve_default_updater_timer "${contour}")"
  week_state_dir="$(resolve_default_updater_state_dir "${contour}")"

  if (( ENGINE_SERVICE_NAME_SET == 1 )); then engine_service_name="${ENGINE_SERVICE_NAME}"; fi
  if (( CLIENT_SERVICE_NAME_SET == 1 )); then client_service_name="${CLIENT_SERVICE_NAME}"; fi
  if (( UPDATER_SERVICE_NAME_SET == 1 )); then updater_service_name="${UPDATER_SERVICE_NAME}"; fi
  if (( UPDATER_TIMER_NAME_SET == 1 )); then updater_timer_name="${UPDATER_TIMER_NAME}"; fi
  if (( UPDATER_WEEK_STATE_DIR_SET == 1 )); then week_state_dir="${UPDATER_WEEK_STATE_DIR}"; fi

  validate_service_name "${engine_service_name}"
  validate_service_name "${client_service_name}"
  validate_service_name "${updater_service_name}"
  validate_service_name "${updater_timer_name}"

  echo "[uninstall-service] contour=${contour} engine=${engine_service_name} client=${client_service_name}"

  local client_cmd=(
    bash
    "${PROJECT_DIR}/client/uninstall-client-service.sh"
    --mode "${contour}"
    --project-dir "${PROJECT_DIR}"
    --service-name "${client_service_name}"
  )
  local engine_cmd=(
    bash
    "${PROJECT_DIR}/engine/uninstall-engine-service.sh"
    --mode "${contour}"
    --project-dir "${PROJECT_DIR}"
    --service-name "${engine_service_name}"
  )

  if (( DRY_RUN == 1 )); then
    client_cmd+=(--dry-run)
    engine_cmd+=(--dry-run)
  fi

  run_cmd "${client_cmd[@]}"
  run_cmd "${engine_cmd[@]}"
  uninstall_updater_for_contour "${contour}" "${updater_service_name}" "${updater_timer_name}" "${week_state_dir}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode|--contour)
      MODE="${2:-}"
      shift 2
      ;;
    --project-dir)
      PROJECT_DIR="${2:-}"
      shift 2
      ;;
    --engine-service-name)
      ENGINE_SERVICE_NAME="${2:-}"
      ENGINE_SERVICE_NAME_SET=1
      shift 2
      ;;
    --client-service-name)
      CLIENT_SERVICE_NAME="${2:-}"
      CLIENT_SERVICE_NAME_SET=1
      shift 2
      ;;
    --updater-service-name)
      UPDATER_SERVICE_NAME="${2:-}"
      UPDATER_SERVICE_NAME_SET=1
      shift 2
      ;;
    --updater-timer-name)
      UPDATER_TIMER_NAME="${2:-}"
      UPDATER_TIMER_NAME_SET=1
      shift 2
      ;;
    --updater-week-state-dir)
      UPDATER_WEEK_STATE_DIR="${2:-}"
      UPDATER_WEEK_STATE_DIR_SET=1
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
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

validate_mode
PROJECT_DIR="$(realpath "${PROJECT_DIR}")"
[[ -d "${PROJECT_DIR}" ]] || fail "Project directory not found: ${PROJECT_DIR}"
[[ -f "${PROJECT_DIR}/engine/uninstall-engine-service.sh" ]] || fail "Missing uninstaller: ${PROJECT_DIR}/engine/uninstall-engine-service.sh"
[[ -f "${PROJECT_DIR}/client/uninstall-client-service.sh" ]] || fail "Missing uninstaller: ${PROJECT_DIR}/client/uninstall-client-service.sh"

if (( DRY_RUN == 0 )); then
  [[ "${EUID}" -eq 0 ]] || fail "Run as root (use sudo)."
  require_cmd systemctl
fi

ensure_single_contour_overrides_only

if [[ "${MODE}" == "all" ]]; then
  uninstall_contour "prod"
  uninstall_contour "dev"
else
  uninstall_contour "${MODE}"
fi

echo "[uninstall-service] Completed mode=${MODE}"
