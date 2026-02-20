#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$PROJECT_ROOT}"
SERVICE_USER="${SUDO_USER:-$(id -un)}"

MODE=""
ENGINE_SERVICE_NAME=""
ENGINE_HOST="127.0.0.1"
ENGINE_PORT=""
FORCE_REINSTALL=0
DRY_RUN=0
INSTALL_WITH_UPDATER_TIMER=0

PRINT_DEFAULT_SERVICE_NAME=0
PRINT_DEFAULT_UPDATER_SERVICE_NAME=0
PRINT_DEFAULT_UPDATER_TIMER_NAME=0

DEFAULT_PROD_ENGINE_SERVICE="peertube-engine"
DEFAULT_DEV_ENGINE_SERVICE="peertube-engine-dev"
DEFAULT_PROD_ENGINE_PORT=7070
DEFAULT_DEV_ENGINE_PORT=7171

print_usage() {
  cat <<'EOF_USAGE'
Usage: sudo ./engine/install-engine-service.sh --mode <prod|dev> [options]

Install/update Engine systemd service for prod/dev contour.
Updater install has been moved to: ./engine/install-updater-service.sh

Default behavior by mode:
  Engine install:
    prod: service=peertube-engine host=127.0.0.1 port=7070
    dev : service=peertube-engine-dev host=127.0.0.1 port=7171

Options:
  --mode <prod|dev>         Required contour mode
  --project-dir <path>      Project root path (default: script parent directory)
  --service-user <user>     Unix user to run service as (default: SUDO_USER/current user)
  --service-name <name>     Override Engine unit base name (default: peertube-engine[-dev])
  --host <host>             Engine bind host (default: 127.0.0.1)
  --port <port>             Engine bind port (default: 7070 prod, 7171 dev)
  --with-updater-timer      Also install updater via install-updater-service.sh in same --mode (dev requires --force)

  --print-default-service-name
  --print-default-updater-service-name
  --print-default-updater-timer-name

  --force                   Force reinstall selected service/timer unit(s)
  --dry-run                 Print planned actions without writing system files
  -h, --help                Show this help

Examples:
  sudo ./engine/install-engine-service.sh --mode prod
  sudo ./engine/install-engine-service.sh --mode dev --service-name peertube-engine-dev --port 7171
  sudo ./engine/install-engine-service.sh --mode prod --with-updater-timer
  sudo ./engine/install-updater-service.sh --mode prod --with-updater-timer
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
  if [[ -z "${MODE}" ]]; then
    fail "Missing required --mode <prod|dev>. Example: --mode prod"
  fi
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

validate_port() {
  local value="$1"
  [[ "${value}" =~ ^[0-9]+$ ]] || fail "Port must be numeric: ${value}"
  (( value >= 1 && value <= 65535 )) || fail "Port must be in range 1..65535: ${value}"
}

resolve_default_engine_service() {
  local mode="$1"
  if [[ "${mode}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_ENGINE_SERVICE}"
  else
    printf '%s' "${DEFAULT_DEV_ENGINE_SERVICE}"
  fi
}

resolve_default_engine_port() {
  local mode="$1"
  if [[ "${mode}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_ENGINE_PORT}"
  else
    printf '%s' "${DEFAULT_DEV_ENGINE_PORT}"
  fi
}

resolve_updater_installer() {
  local path="${PROJECT_DIR}/engine/install-updater-service.sh"
  [[ -f "${path}" ]] || fail "Missing installer: ${path}"
  printf '%s' "${path}"
}

install_updater_with_timer() {
  local updater_installer
  updater_installer="$(resolve_updater_installer)"
  local cmd=(
    bash
    "${updater_installer}"
    --mode "${MODE}"
    --project-dir "${PROJECT_DIR}"
    --service-user "${SERVICE_USER}"
    --engine-service-name "${ENGINE_SERVICE_NAME}"
    --with-updater-timer
  )
  if (( FORCE_REINSTALL == 1 )); then
    cmd+=(--force)
  fi
  if (( DRY_RUN == 1 )); then
    cmd+=(--dry-run)
  fi
  "${cmd[@]}"
}

install_engine_service() {
  if [[ -z "${ENGINE_SERVICE_NAME}" ]]; then
    ENGINE_SERVICE_NAME="$(resolve_default_engine_service "${MODE}")"
  fi
  validate_service_name "${ENGINE_SERVICE_NAME}"

  if [[ -z "${ENGINE_PORT}" ]]; then
    ENGINE_PORT="$(resolve_default_engine_port "${MODE}")"
  fi
  validate_port "${ENGINE_PORT}"

  [[ -n "${ENGINE_HOST}" ]] || fail "--host cannot be empty"
  [[ -n "${SERVICE_USER}" ]] || fail "--service-user cannot be empty"
  [[ -f "${SERVER_PY}" ]] || fail "Missing server entrypoint: ${SERVER_PY}"
  [[ -x "${VENV_PY}" ]] || fail "Missing python interpreter in venv: ${VENV_PY}"

  if (( DRY_RUN == 0 )); then
    [[ "${EUID}" -eq 0 ]] || fail "Run as root (use sudo)."
    require_cmd systemctl
    require_cmd journalctl
  fi
  id "${SERVICE_USER}" >/dev/null 2>&1 || fail "User does not exist: ${SERVICE_USER}"

  local unit_path="/etc/systemd/system/${ENGINE_SERVICE_NAME}.service"
  local unit_content
  unit_content="[Unit]
Description=PeerTube Engine (${MODE})
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=ENGINE_INGEST_MODE=bridge
ExecStart=${VENV_PY} ${SERVER_PY} --host ${ENGINE_HOST} --port ${ENGINE_PORT}
Restart=on-failure
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
"

  if (( DRY_RUN == 1 )); then
    echo "[dry-run] install-engine-service"
    echo "  mode=${MODE}"
    echo "  service=${ENGINE_SERVICE_NAME}"
    echo "  host=${ENGINE_HOST}"
    echo "  port=${ENGINE_PORT}"
    echo "  user=${SERVICE_USER}"
    echo "  unit=${unit_path}"
    echo "----- unit preview -----"
    printf '%s\n' "${unit_content}"
    echo "----- end preview -----"
    return
  fi

  if (( FORCE_REINSTALL == 1 )); then
    log_lifecycle "[engine-install] force reinstall begin service=${ENGINE_SERVICE_NAME}.service mode=${MODE}"
    log_lifecycle "[engine-install] stopping service=${ENGINE_SERVICE_NAME}.service"
    systemctl stop "${ENGINE_SERVICE_NAME}.service" >/dev/null 2>&1 || true
    log_lifecycle "[engine-install] disabling service=${ENGINE_SERVICE_NAME}.service"
    systemctl disable "${ENGINE_SERVICE_NAME}.service" >/dev/null 2>&1 || true
    rm -f "${unit_path}"
    systemctl daemon-reload
    systemctl reset-failed "${ENGINE_SERVICE_NAME}.service" >/dev/null 2>&1 || true
  fi

  echo "[engine-install] Writing unit: ${unit_path}"
  printf '%s\n' "${unit_content}" > "${unit_path}"

  echo "[engine-install] Reloading systemd"
  systemctl daemon-reload

  log_lifecycle "[engine-install] enabling service=${ENGINE_SERVICE_NAME}.service"
  systemctl enable "${ENGINE_SERVICE_NAME}.service" >/dev/null
  log_lifecycle "[engine-install] restarting service=${ENGINE_SERVICE_NAME}.service"
  systemctl restart "${ENGINE_SERVICE_NAME}.service"

  local enabled_state
  local active_state
  enabled_state="$(systemctl is-enabled "${ENGINE_SERVICE_NAME}.service" 2>/dev/null || true)"
  active_state="$(systemctl is-active "${ENGINE_SERVICE_NAME}.service" 2>/dev/null || true)"

  echo "is-enabled: ${enabled_state}"
  echo "is-active : ${active_state}"

  if [[ "${enabled_state}" != "enabled" || "${active_state}" != "active" ]]; then
    echo "Engine service failed to start. Recent logs:" >&2
    journalctl -u "${ENGINE_SERVICE_NAME}.service" -n 80 --no-pager >&2 || true
    exit 1
  fi

  echo "Engine service installed: ${ENGINE_SERVICE_NAME}.service"
  log_lifecycle "[engine-install] service active service=${ENGINE_SERVICE_NAME}.service mode=${MODE}"
  echo "Status: systemctl status ${ENGINE_SERVICE_NAME}.service"
  echo "Logs  : journalctl -u ${ENGINE_SERVICE_NAME}.service -f"
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
    --service-user)
      SERVICE_USER="${2:-}"
      shift 2
      ;;
    --service-name)
      ENGINE_SERVICE_NAME="${2:-}"
      shift 2
      ;;
    --host)
      ENGINE_HOST="${2:-}"
      shift 2
      ;;
    --port)
      ENGINE_PORT="${2:-}"
      shift 2
      ;;
    --with-updater-timer)
      INSTALL_WITH_UPDATER_TIMER=1
      shift
      ;;
    --print-default-service-name)
      PRINT_DEFAULT_SERVICE_NAME=1
      shift
      ;;
    --print-default-updater-service-name)
      PRINT_DEFAULT_UPDATER_SERVICE_NAME=1
      shift
      ;;
    --print-default-updater-timer-name)
      PRINT_DEFAULT_UPDATER_TIMER_NAME=1
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
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

validate_mode
PROJECT_DIR="$(realpath "${PROJECT_DIR}")"
[[ -d "${PROJECT_DIR}" ]] || fail "Project directory not found: ${PROJECT_DIR}"

if (( PRINT_DEFAULT_SERVICE_NAME == 1 )); then
  resolve_default_engine_service "${MODE}"
  echo
  exit 0
fi

if (( PRINT_DEFAULT_UPDATER_SERVICE_NAME == 1 || PRINT_DEFAULT_UPDATER_TIMER_NAME == 1 )); then
  updater_installer="$(resolve_updater_installer)"
  if (( PRINT_DEFAULT_UPDATER_SERVICE_NAME == 1 )); then
    bash "${updater_installer}" --mode "${MODE}" --print-default-updater-service-name
    exit 0
  fi
  if (( PRINT_DEFAULT_UPDATER_TIMER_NAME == 1 )); then
    bash "${updater_installer}" --mode "${MODE}" --print-default-updater-timer-name
    exit 0
  fi
fi

SERVER_PY="${PROJECT_DIR}/engine/server/api/server.py"
VENV_PY="${PROJECT_DIR}/venv/bin/python3"

install_engine_service
if (( INSTALL_WITH_UPDATER_TIMER == 1 )); then
  install_updater_with_timer
fi
