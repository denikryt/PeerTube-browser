#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
SERVICE_USER="${SUDO_USER:-$(id -un)}"

MODE="prod"
CLIENT_SERVICE_NAME=""
CLIENT_HOST="127.0.0.1"
CLIENT_PORT=""
ENGINE_INGEST_BASE=""
USERS_DB_PATH=""
PUBLISH_MODE="bridge"
FORCE_REINSTALL=0
DRY_RUN=0

DEFAULT_PROD_CLIENT_PORT=7072
DEFAULT_DEV_CLIENT_PORT=7172
DEFAULT_PROD_ENGINE_PORT=7070
DEFAULT_DEV_ENGINE_PORT=7171
DEFAULT_USERS_DB_PROD="client/backend/db/users.db"
DEFAULT_USERS_DB_DEV="client/backend/db/users-dev.db"

print_usage() {
  cat <<'EOF_USAGE'
Usage: sudo ./client/install-client-service.sh [options]

Install/update Client backend systemd service for prod/dev contour.

Options:
  --mode <prod|dev>           Contour mode (default: prod)
  --project-dir <path>        Project root path (default: script directory)
  --service-user <user>       Unix user to run service as (default: SUDO_USER/current user)
  --service-name <name>       Override Client unit base name (default: peertube-client[-dev])
  --host <host>               Client bind host (default: 127.0.0.1)
  --port <port>               Client bind port (default: 7072 prod, 7172 dev)
  --engine-ingest-base <url>  Engine ingest base URL for Client bridge (default: contour-local)
  --users-db <path>           Users DB path relative to project root (default: contour-specific)
  --publish-mode <mode>       Client publish mode (default: bridge)
  --force                     Force reinstall selected service unit (stop/disable/remove/recreate)
  --dry-run                   Print planned actions without writing system files
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
      CLIENT_SERVICE_NAME="${2:-}"
      shift 2
      ;;
    --host)
      CLIENT_HOST="${2:-}"
      shift 2
      ;;
    --port)
      CLIENT_PORT="${2:-}"
      shift 2
      ;;
    --engine-ingest-base)
      ENGINE_INGEST_BASE="${2:-}"
      shift 2
      ;;
    --users-db)
      USERS_DB_PATH="${2:-}"
      shift 2
      ;;
    --publish-mode)
      PUBLISH_MODE="${2:-}"
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

if [[ -z "${CLIENT_SERVICE_NAME}" ]]; then
  if [[ "${MODE}" == "prod" ]]; then
    CLIENT_SERVICE_NAME="peertube-client"
  else
    CLIENT_SERVICE_NAME="peertube-client-dev"
  fi
fi
validate_service_name "${CLIENT_SERVICE_NAME}"

if [[ -z "${CLIENT_PORT}" ]]; then
  if [[ "${MODE}" == "prod" ]]; then
    CLIENT_PORT="${DEFAULT_PROD_CLIENT_PORT}"
  else
    CLIENT_PORT="${DEFAULT_DEV_CLIENT_PORT}"
  fi
fi
validate_port "${CLIENT_PORT}"

if [[ -z "${ENGINE_INGEST_BASE}" ]]; then
  if [[ "${MODE}" == "prod" ]]; then
    ENGINE_INGEST_BASE="http://127.0.0.1:${DEFAULT_PROD_ENGINE_PORT}"
  else
    ENGINE_INGEST_BASE="http://127.0.0.1:${DEFAULT_DEV_ENGINE_PORT}"
  fi
fi

if [[ -z "${USERS_DB_PATH}" ]]; then
  if [[ "${MODE}" == "prod" ]]; then
    USERS_DB_PATH="${DEFAULT_USERS_DB_PROD}"
  else
    USERS_DB_PATH="${DEFAULT_USERS_DB_DEV}"
  fi
fi

[[ -n "${CLIENT_HOST}" ]] || fail "--host cannot be empty"
[[ -n "${SERVICE_USER}" ]] || fail "--service-user cannot be empty"
[[ -n "${ENGINE_INGEST_BASE}" ]] || fail "--engine-ingest-base cannot be empty"
[[ -n "${USERS_DB_PATH}" ]] || fail "--users-db cannot be empty"
[[ -n "${PUBLISH_MODE}" ]] || fail "--publish-mode cannot be empty"

PROJECT_DIR="$(realpath "${PROJECT_DIR}")"
[[ -d "${PROJECT_DIR}" ]] || fail "Project directory not found: ${PROJECT_DIR}"

CLIENT_PY="${PROJECT_DIR}/client/backend/server.py"
VENV_PY="${PROJECT_DIR}/venv/bin/python3"
UNIT_PATH="/etc/systemd/system/${CLIENT_SERVICE_NAME}.service"

[[ -f "${CLIENT_PY}" ]] || fail "Missing client backend entrypoint: ${CLIENT_PY}"
[[ -x "${VENV_PY}" ]] || fail "Missing python interpreter in venv: ${VENV_PY}"
id "${SERVICE_USER}" >/dev/null 2>&1 || fail "User does not exist: ${SERVICE_USER}"

UNIT_CONTENT="[Unit]
Description=PeerTube Client Backend (${MODE})
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=CLIENT_PUBLISH_MODE=${PUBLISH_MODE}
ExecStart=${VENV_PY} ${CLIENT_PY} --host ${CLIENT_HOST} --port ${CLIENT_PORT} --users-db ${USERS_DB_PATH} --engine-ingest-base ${ENGINE_INGEST_BASE} --publish-mode ${PUBLISH_MODE}
Restart=on-failure
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
"

if (( DRY_RUN == 1 )); then
  echo "[dry-run] install-client-service"
  echo "  mode=${MODE}"
  echo "  service=${CLIENT_SERVICE_NAME}"
  echo "  host=${CLIENT_HOST}"
  echo "  port=${CLIENT_PORT}"
  echo "  engine_ingest_base=${ENGINE_INGEST_BASE}"
  echo "  users_db=${USERS_DB_PATH}"
  echo "  publish_mode=${PUBLISH_MODE}"
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
  echo "[force] Reinstalling ${CLIENT_SERVICE_NAME}.service"
  systemctl stop "${CLIENT_SERVICE_NAME}.service" >/dev/null 2>&1 || true
  systemctl disable "${CLIENT_SERVICE_NAME}.service" >/dev/null 2>&1 || true
  rm -f "${UNIT_PATH}"
  systemctl daemon-reload
  systemctl reset-failed "${CLIENT_SERVICE_NAME}.service" >/dev/null 2>&1 || true
fi

echo "[client-install] Writing unit: ${UNIT_PATH}"
printf '%s\n' "${UNIT_CONTENT}" > "${UNIT_PATH}"

echo "[client-install] Reloading systemd"
systemctl daemon-reload

echo "[client-install] Enabling and restarting ${CLIENT_SERVICE_NAME}.service"
systemctl enable "${CLIENT_SERVICE_NAME}.service" >/dev/null
systemctl restart "${CLIENT_SERVICE_NAME}.service"

enabled_state="$(systemctl is-enabled "${CLIENT_SERVICE_NAME}.service" 2>/dev/null || true)"
active_state="$(systemctl is-active "${CLIENT_SERVICE_NAME}.service" 2>/dev/null || true)"

echo "is-enabled: ${enabled_state}"
echo "is-active : ${active_state}"

if [[ "${enabled_state}" != "enabled" || "${active_state}" != "active" ]]; then
  echo "Client service failed to start. Recent logs:" >&2
  journalctl -u "${CLIENT_SERVICE_NAME}.service" -n 80 --no-pager >&2 || true
  exit 1
fi

echo "Client service installed: ${CLIENT_SERVICE_NAME}.service"
echo "Status: systemctl status ${CLIENT_SERVICE_NAME}.service"
echo "Logs  : journalctl -u ${CLIENT_SERVICE_NAME}.service -f"
