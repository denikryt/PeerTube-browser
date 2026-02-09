#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="peertube-browser"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
FORCE_OVERWRITE=0

print_usage() {
  cat <<'EOF'
Usage: sudo ./install-service.sh [options]

Options:
  --project-dir <path>   Project root path (default: script directory)
  --service-user <user>  Unix user to run the service as (default: SUDO_USER/current user)
  --force                Overwrite existing service file without prompt
  -h, --help             Show this help
EOF
}

SERVICE_USER="${SUDO_USER:-$(id -un)}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      PROJECT_DIR="${2:-}"
      shift 2
      ;;
    --service-user)
      SERVICE_USER="${2:-}"
      shift 2
      ;;
    --force)
      FORCE_OVERWRITE=1
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      print_usage
      exit 1
      ;;
  esac
done

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

check_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

echo "[1/6] Preflight checks"
[[ "${EUID}" -eq 0 ]] || fail "Run as root (use sudo)."
check_cmd systemctl
check_cmd journalctl

systemctl list-unit-files >/dev/null 2>&1 || fail "systemctl is not usable on this host."

[[ -n "${SERVICE_USER}" ]] || fail "--service-user cannot be empty."
id "${SERVICE_USER}" >/dev/null 2>&1 || fail "User does not exist: ${SERVICE_USER}"

PROJECT_DIR="$(realpath "${PROJECT_DIR}")"
[[ -d "${PROJECT_DIR}" ]] || fail "Project directory not found: ${PROJECT_DIR}"

SERVER_PY="${PROJECT_DIR}/server/api/server.py"
VENV_PY="${PROJECT_DIR}/venv/bin/python3"

[[ -f "${SERVER_PY}" ]] || fail "Missing server entrypoint: ${SERVER_PY}"
[[ -x "${VENV_PY}" ]] || fail "Missing python interpreter in venv: ${VENV_PY}"

if [[ -f "${UNIT_PATH}" && "${FORCE_OVERWRITE}" -ne 1 ]]; then
  read -r -p "Service file exists at ${UNIT_PATH}. Overwrite? [y/N] " answer
  case "${answer}" in
    y|Y|yes|YES) ;;
    *) fail "Aborted by user." ;;
  esac
fi

echo "[2/6] Writing unit file: ${UNIT_PATH}"
cat > "${UNIT_PATH}" <<EOF
[Unit]
Description=PeerTube Browser API Server
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${VENV_PY} ${SERVER_PY}
Restart=on-failure
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF

echo "[3/6] Reloading systemd"
systemctl daemon-reload

echo "[4/6] Enabling service"
systemctl enable "${SERVICE_NAME}" >/dev/null

echo "[5/6] Starting service"
systemctl restart "${SERVICE_NAME}"

echo "[6/6] Post-checks"
ENABLED_STATE="$(systemctl is-enabled "${SERVICE_NAME}" 2>/dev/null || true)"
ACTIVE_STATE="$(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || true)"

echo "is-enabled: ${ENABLED_STATE}"
echo "is-active : ${ACTIVE_STATE}"

if [[ "${ENABLED_STATE}" != "enabled" || "${ACTIVE_STATE}" != "active" ]]; then
  echo "Service did not start correctly. Recent logs:"
  journalctl -u "${SERVICE_NAME}" -n 50 --no-pager || true
  exit 1
fi

echo "Service installed and running."
echo "Check status: systemctl status ${SERVICE_NAME}"
echo "Tail logs   : journalctl -u ${SERVICE_NAME} -f"

