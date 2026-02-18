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

DEFAULT_PROD_ENGINE_PORT=7070
DEFAULT_DEV_ENGINE_PORT=7171

print_usage() {
  cat <<'EOF_USAGE'
Usage: sudo ./engine/install-engine-service.sh --mode <prod|dev> [options]

Install/update Engine systemd service for prod/dev contour.

Options:
  --mode <prod|dev>         Required contour mode
  --project-dir <path>      Project root path (default: script parent directory)
  --service-user <user>     Unix user to run service as (default: SUDO_USER/current user)
  --service-name <name>     Override Engine unit base name (default: peertube-engine[-dev])
  --host <host>             Engine bind host (default: 127.0.0.1)
  --port <port>             Engine bind port (default: 7070 prod, 7171 dev)
  --force                   Force reinstall selected service unit (stop/disable/remove/recreate)
  --dry-run                 Print planned actions without writing system files
  -h, --help                Show this help

Examples:
  sudo ./engine/install-engine-service.sh --mode prod
  sudo ./engine/install-engine-service.sh --mode dev
  sudo ./engine/install-engine-service.sh --mode dev --service-name peertube-engine-dev --port 7171
  sudo ./engine/install-engine-service.sh --mode prod --host 127.0.0.1 --port 7070
  sudo ./engine/install-engine-service.sh --mode dev --dry-run
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

if [[ -z "${ENGINE_SERVICE_NAME}" ]]; then
  if [[ "${MODE}" == "prod" ]]; then
    ENGINE_SERVICE_NAME="peertube-engine"
  else
    ENGINE_SERVICE_NAME="peertube-engine-dev"
  fi
fi
validate_service_name "${ENGINE_SERVICE_NAME}"

if [[ -z "${ENGINE_PORT}" ]]; then
  if [[ "${MODE}" == "prod" ]]; then
    ENGINE_PORT="${DEFAULT_PROD_ENGINE_PORT}"
  else
    ENGINE_PORT="${DEFAULT_DEV_ENGINE_PORT}"
  fi
fi
validate_port "${ENGINE_PORT}"

[[ -n "${ENGINE_HOST}" ]] || fail "--host cannot be empty"
[[ -n "${SERVICE_USER}" ]] || fail "--service-user cannot be empty"

PROJECT_DIR="$(realpath "${PROJECT_DIR}")"
[[ -d "${PROJECT_DIR}" ]] || fail "Project directory not found: ${PROJECT_DIR}"

SERVER_PY="${PROJECT_DIR}/engine/server/api/server.py"
VENV_PY="${PROJECT_DIR}/venv/bin/python3"
UNIT_PATH="/etc/systemd/system/${ENGINE_SERVICE_NAME}.service"

[[ -f "${SERVER_PY}" ]] || fail "Missing server entrypoint: ${SERVER_PY}"
[[ -x "${VENV_PY}" ]] || fail "Missing python interpreter in venv: ${VENV_PY}"
id "${SERVICE_USER}" >/dev/null 2>&1 || fail "User does not exist: ${SERVICE_USER}"

UNIT_CONTENT="[Unit]
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
  echo "  unit=${UNIT_PATH}"
  echo "----- unit preview -----"
  printf '%s\n' "${UNIT_CONTENT}"
  echo "----- end preview -----"
  exit 0
fi

[[ "${EUID}" -eq 0 ]] || fail "Run as root (use sudo)."
require_cmd systemctl
require_cmd journalctl

if (( FORCE_REINSTALL == 1 )); then
  echo "[force] Reinstalling ${ENGINE_SERVICE_NAME}.service"
  systemctl stop "${ENGINE_SERVICE_NAME}.service" >/dev/null 2>&1 || true
  systemctl disable "${ENGINE_SERVICE_NAME}.service" >/dev/null 2>&1 || true
  rm -f "${UNIT_PATH}"
  systemctl daemon-reload
  systemctl reset-failed "${ENGINE_SERVICE_NAME}.service" >/dev/null 2>&1 || true
fi

echo "[engine-install] Writing unit: ${UNIT_PATH}"
printf '%s\n' "${UNIT_CONTENT}" > "${UNIT_PATH}"

echo "[engine-install] Reloading systemd"
systemctl daemon-reload

echo "[engine-install] Enabling and restarting ${ENGINE_SERVICE_NAME}.service"
systemctl enable "${ENGINE_SERVICE_NAME}.service" >/dev/null
systemctl restart "${ENGINE_SERVICE_NAME}.service"

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
echo "Status: systemctl status ${ENGINE_SERVICE_NAME}.service"
echo "Logs  : journalctl -u ${ENGINE_SERVICE_NAME}.service -f"
