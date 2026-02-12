#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="peertube-browser"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
UPDATER_SERVICE_NAME="peertube-updater"
UPDATER_TIMER_NAME="peertube-updater"
WITH_UPDATER_TIMER=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
FORCE_OVERWRITE=0
UPDATER_TIMER_ONCALENDAR="${UPDATER_TIMER_ONCALENDAR:-Fri *-*-* 20:00:00}"

# Updater worker flags.
# Edit this line to control updater behavior installed into systemd.
# Example: "--gpu --skip-local-dead --concurrency 2 --timeout-ms 15000 --max-retries 3"
UPDATER_FLAGS="--gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3"
# Updater timer schedule.
# OnCalendar format, local time.
# Default: daily at 20:00 with weekly success gate in service:
# - first successful run in current ISO week marks the week as done,
# - next days in same week are skipped,
# - if a run fails, next day at 20:00 retries automatically.
# Example override:
#   UPDATER_TIMER_ONCALENDAR='*-*-* 03:30:00' sudo ./install-service.sh --with-updater-timer
UPDATER_WEEK_STATE_DIR="${UPDATER_WEEK_STATE_DIR:-/var/lib/peertube-browser}"
UPDATER_WEEK_STATE_FILE="${UPDATER_WEEK_STATE_FILE:-${UPDATER_WEEK_STATE_DIR}/updater-last-success-week.txt}"

print_usage() {
  cat <<'EOF'
Usage: sudo ./install-service.sh [options]

Options:
  --project-dir <path>   Project root path (default: script directory)
  --service-user <user>  Unix user to run the service as (default: SUDO_USER/current user)
  --with-updater-timer   Install updater timer (20:00 daily trigger + weekly success gate)
  --updater-service-name <name>  Updater service unit name (default: peertube-updater)
  --updater-timer-name <name>    Updater timer unit name (default: peertube-updater)
  --force                Force full reinstall of selected unit files (stop/disable/remove/recreate)
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
    --with-updater-timer)
      WITH_UPDATER_TIMER=1
      shift
      ;;
    --updater-service-name)
      UPDATER_SERVICE_NAME="${2:-}"
      shift 2
      ;;
    --updater-timer-name)
      UPDATER_TIMER_NAME="${2:-}"
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

confirm_overwrite() {
  local target_path="$1"
  if [[ -f "${target_path}" && "${FORCE_OVERWRITE}" -ne 1 ]]; then
    read -r -p "File exists at ${target_path}. Overwrite? [y/N] " answer
    case "${answer}" in
      y|Y|yes|YES) ;;
      *) fail "Aborted by user." ;;
    esac
  fi
}

check_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

force_reinstall_units() {
  echo "[force] Removing existing units before reinstall"
  systemctl stop "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
  systemctl disable "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
  rm -f "${UNIT_PATH}"

  if [[ "${WITH_UPDATER_TIMER}" -eq 1 ]]; then
    systemctl stop "${UPDATER_TIMER_NAME}.timer" >/dev/null 2>&1 || true
    systemctl stop "${UPDATER_SERVICE_NAME}.service" >/dev/null 2>&1 || true
    systemctl disable "${UPDATER_TIMER_NAME}.timer" >/dev/null 2>&1 || true
    rm -f "${UPDATER_TIMER_PATH}"
    rm -f "${UPDATER_UNIT_PATH}"
  fi

  systemctl daemon-reload
  systemctl reset-failed "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
  if [[ "${WITH_UPDATER_TIMER}" -eq 1 ]]; then
    systemctl reset-failed "${UPDATER_SERVICE_NAME}.service" >/dev/null 2>&1 || true
    systemctl reset-failed "${UPDATER_TIMER_NAME}.timer" >/dev/null 2>&1 || true
  fi
}

echo "[1/8] Preflight checks"
[[ "${EUID}" -eq 0 ]] || fail "Run as root (use sudo)."
check_cmd systemctl
check_cmd journalctl

systemctl list-unit-files >/dev/null 2>&1 || fail "systemctl is not usable on this host."

[[ -n "${SERVICE_USER}" ]] || fail "--service-user cannot be empty."
id "${SERVICE_USER}" >/dev/null 2>&1 || fail "User does not exist: ${SERVICE_USER}"
[[ -n "${UPDATER_SERVICE_NAME}" ]] || fail "--updater-service-name cannot be empty."
[[ -n "${UPDATER_TIMER_NAME}" ]] || fail "--updater-timer-name cannot be empty."
[[ "${UPDATER_SERVICE_NAME}" =~ ^[a-zA-Z0-9_.@-]+$ ]] || fail "Invalid --updater-service-name."
[[ "${UPDATER_TIMER_NAME}" =~ ^[a-zA-Z0-9_.@-]+$ ]] || fail "Invalid --updater-timer-name."

PROJECT_DIR="$(realpath "${PROJECT_DIR}")"
[[ -d "${PROJECT_DIR}" ]] || fail "Project directory not found: ${PROJECT_DIR}"

SERVER_PY="${PROJECT_DIR}/server/api/server.py"
VENV_PY="${PROJECT_DIR}/venv/bin/python3"
UPDATER_PY="${PROJECT_DIR}/server/db/jobs/updater-worker.py"
UPDATER_UNIT_PATH="/etc/systemd/system/${UPDATER_SERVICE_NAME}.service"
UPDATER_TIMER_PATH="/etc/systemd/system/${UPDATER_TIMER_NAME}.timer"

[[ -f "${SERVER_PY}" ]] || fail "Missing server entrypoint: ${SERVER_PY}"
[[ -x "${VENV_PY}" ]] || fail "Missing python interpreter in venv: ${VENV_PY}"
if [[ "${WITH_UPDATER_TIMER}" -eq 1 ]]; then
  [[ -f "${UPDATER_PY}" ]] || fail "Missing updater worker entrypoint: ${UPDATER_PY}"
fi
[[ -w "/etc/systemd/system" ]] || fail "No write access to /etc/systemd/system."

if [[ "${FORCE_OVERWRITE}" -eq 1 ]]; then
  force_reinstall_units
fi

confirm_overwrite "${UNIT_PATH}"
if [[ "${WITH_UPDATER_TIMER}" -eq 1 ]]; then
  confirm_overwrite "${UPDATER_UNIT_PATH}"
  confirm_overwrite "${UPDATER_TIMER_PATH}"
fi

echo "[2/8] Writing API unit file: ${UNIT_PATH}"
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

if [[ "${WITH_UPDATER_TIMER}" -eq 1 ]]; then
  mkdir -p "${UPDATER_WEEK_STATE_DIR}"
  chown "${SERVICE_USER}:${SERVICE_USER}" "${UPDATER_WEEK_STATE_DIR}" || true
  chmod 755 "${UPDATER_WEEK_STATE_DIR}" || true

  echo "[3/8] Writing updater service: ${UPDATER_UNIT_PATH}"
  cat > "${UPDATER_UNIT_PATH}" <<EOF
[Unit]
Description=PeerTube Browser Updater Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/bash -lc 'set -euo pipefail; week_id="$$(date +%G-%V)"; state_file="${UPDATER_WEEK_STATE_FILE}"; if [[ -f "$$state_file" ]] && [[ "$$(cat "$$state_file" 2>/dev/null || true)" == "$$week_id" ]]; then echo "[updater] weekly gate: already successful in week $$week_id, skip"; exit 0; fi; ${VENV_PY} ${UPDATER_PY} ${UPDATER_FLAGS}; printf "%s\n" "$$week_id" > "$$state_file"'
TimeoutStartSec=24h
EOF

  echo "[4/8] Writing updater timer: ${UPDATER_TIMER_PATH}"
  cat > "${UPDATER_TIMER_PATH}" <<EOF
[Unit]
Description=PeerTube Browser Updater Weekly-Fallback Timer

[Timer]
OnCalendar=${UPDATER_TIMER_ONCALENDAR}
Persistent=false
RandomizedDelaySec=0
AccuracySec=1m
Unit=${UPDATER_SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF
else
  echo "[3/8] Skipping updater timer install"
  echo "[4/8] Skipping updater timer install"
fi

echo "[5/8] Reloading systemd"
systemctl daemon-reload

echo "[6/8] Enabling API service"
systemctl enable "${SERVICE_NAME}" >/dev/null
if [[ "${WITH_UPDATER_TIMER}" -eq 1 ]]; then
  systemctl enable "${UPDATER_TIMER_NAME}.timer" >/dev/null
fi

echo "[7/8] Starting services"
systemctl restart "${SERVICE_NAME}"
if [[ "${WITH_UPDATER_TIMER}" -eq 1 ]]; then
  systemctl restart "${UPDATER_TIMER_NAME}.timer"
fi

echo "[8/8] Post-checks"
ENABLED_STATE="$(systemctl is-enabled "${SERVICE_NAME}" 2>/dev/null || true)"
ACTIVE_STATE="$(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || true)"

echo "is-enabled: ${ENABLED_STATE}"
echo "is-active : ${ACTIVE_STATE}"

if [[ "${ENABLED_STATE}" != "enabled" || "${ACTIVE_STATE}" != "active" ]]; then
  echo "API service did not start correctly. Recent logs:"
  journalctl -u "${SERVICE_NAME}" -n 50 --no-pager || true
  exit 1
fi

if [[ "${WITH_UPDATER_TIMER}" -eq 1 ]]; then
  TIMER_ENABLED_STATE="$(systemctl is-enabled "${UPDATER_TIMER_NAME}.timer" 2>/dev/null || true)"
  TIMER_ACTIVE_STATE="$(systemctl is-active "${UPDATER_TIMER_NAME}.timer" 2>/dev/null || true)"
  echo "timer is-enabled: ${TIMER_ENABLED_STATE}"
  echo "timer is-active : ${TIMER_ACTIVE_STATE}"
  if [[ "${TIMER_ENABLED_STATE}" != "enabled" || "${TIMER_ACTIVE_STATE}" != "active" ]]; then
    echo "Updater timer did not start correctly. Recent logs:"
    journalctl -u "${UPDATER_TIMER_NAME}.timer" -n 50 --no-pager || true
    exit 1
  fi
  echo "next timer runs:"
  systemctl list-timers --all "${UPDATER_TIMER_NAME}.timer" --no-pager || true
fi

echo "API service installed and running."
echo "Check status: systemctl status ${SERVICE_NAME}"
echo "Tail logs   : journalctl -u ${SERVICE_NAME} -f"

if systemctl list-unit-files "${UPDATER_SERVICE_NAME}.service" >/dev/null 2>&1; then
  echo "Updater status: systemctl status ${UPDATER_SERVICE_NAME}.service"
  echo "Updater logs  : journalctl -u ${UPDATER_SERVICE_NAME}.service -f"
fi

if systemctl list-unit-files "${UPDATER_TIMER_NAME}.timer" >/dev/null 2>&1; then
  echo "Timer status  : systemctl status ${UPDATER_TIMER_NAME}.timer"
  echo "Timer logs    : journalctl -u ${UPDATER_TIMER_NAME}.timer -f"
  echo "Timer state   : ${UPDATER_WEEK_STATE_FILE}"
fi
