#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$PROJECT_ROOT}"
SERVICE_USER="${SUDO_USER:-$(id -un)}"

MODE=""
ENGINE_SERVICE_NAME=""
UPDATER_SERVICE_NAME=""
UPDATER_TIMER_NAME=""
WITH_UPDATER_TIMER_SET=0
WITH_UPDATER_TIMER=0
UNINSTALL_UPDATER=0
FORCE_REINSTALL=0
DRY_RUN=0

PRINT_DEFAULT_ENGINE_SERVICE_NAME=0
PRINT_DEFAULT_UPDATER_SERVICE_NAME=0
PRINT_DEFAULT_UPDATER_TIMER_NAME=0

DEFAULT_PROD_ENGINE_SERVICE="peertube-engine"
DEFAULT_DEV_ENGINE_SERVICE="peertube-engine-dev"
DEFAULT_PROD_UPDATER_SERVICE="peertube-updater"
DEFAULT_DEV_UPDATER_SERVICE="peertube-updater-dev"
DEFAULT_PROD_UPDATER_TIMER="peertube-updater"
DEFAULT_DEV_UPDATER_TIMER="peertube-updater-dev"

UPDATER_TIMER_ONCALENDAR="${UPDATER_TIMER_ONCALENDAR:-Fri *-*-* 20:00:00}"
UPDATER_FLAGS="${UPDATER_FLAGS:---gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3}"

print_usage() {
  cat <<'EOF_USAGE'
Usage: sudo ./engine/install-updater-service.sh --mode <prod|dev> [options]

Install/update updater service+timer for selected contour.

Default behavior by mode:
  prod: engine=peertube-engine updater=peertube-updater timer=enabled force=reinstall
  dev : engine=peertube-engine-dev updater=peertube-updater-dev timer=disabled (uninstall)

Options:
  --mode <prod|dev>           Required contour mode
  --project-dir <path>        Project root path (default: script parent directory)
  --service-user <user>       Unix user to run updater service as

  --engine-service-name <name>  Engine systemd service to stop/start during merge
  --service-name <name>         Alias for --engine-service-name
  --updater-service-name <name> Updater service unit base name
  --updater-timer-name <name>   Updater timer unit base name
  --updater-oncalendar <expr>   Systemd OnCalendar expression
  --updater-flags <flags>       Extra flags for updater-worker.py

  --with-updater-timer        Enable/install timer+service
  --uninstall                 Uninstall/remove updater timer+service for selected --mode
  --force                     Force reinstall updater units
  --dry-run                   Print planned actions only

  --print-default-engine-service-name
  --print-default-updater-service-name
  --print-default-updater-timer-name
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
  local mode="$1"
  if [[ "${mode}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_ENGINE_SERVICE}"
  else
    printf '%s' "${DEFAULT_DEV_ENGINE_SERVICE}"
  fi
}

resolve_default_updater_service() {
  local mode="$1"
  if [[ "${mode}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_UPDATER_SERVICE}"
  else
    printf '%s' "${DEFAULT_DEV_UPDATER_SERVICE}"
  fi
}

resolve_default_updater_timer() {
  local mode="$1"
  if [[ "${mode}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_UPDATER_TIMER}"
  else
    printf '%s' "${DEFAULT_DEV_UPDATER_TIMER}"
  fi
}

resolve_default_with_updater_timer() {
  local mode="$1"
  if [[ "${mode}" == "prod" ]]; then
    printf '1'
  else
    printf '0'
  fi
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
    --engine-service-name|--service-name)
      ENGINE_SERVICE_NAME="${2:-}"
      shift 2
      ;;
    --updater-service-name)
      UPDATER_SERVICE_NAME="${2:-}"
      shift 2
      ;;
    --updater-timer-name)
      UPDATER_TIMER_NAME="${2:-}"
      shift 2
      ;;
    --updater-oncalendar)
      UPDATER_TIMER_ONCALENDAR="${2:-}"
      shift 2
      ;;
    --updater-flags)
      UPDATER_FLAGS="${2:-}"
      shift 2
      ;;
    --with-updater-timer)
      WITH_UPDATER_TIMER_SET=1
      WITH_UPDATER_TIMER=1
      shift
      ;;
    --uninstall)
      UNINSTALL_UPDATER=1
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
    --print-default-engine-service-name)
      PRINT_DEFAULT_ENGINE_SERVICE_NAME=1
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

if (( PRINT_DEFAULT_ENGINE_SERVICE_NAME == 1 )); then
  resolve_default_engine_service "${MODE}"
  echo
  exit 0
fi
if (( PRINT_DEFAULT_UPDATER_SERVICE_NAME == 1 )); then
  resolve_default_updater_service "${MODE}"
  echo
  exit 0
fi
if (( PRINT_DEFAULT_UPDATER_TIMER_NAME == 1 )); then
  resolve_default_updater_timer "${MODE}"
  echo
  exit 0
fi

PROJECT_DIR="$(realpath "${PROJECT_DIR}")"
[[ -d "${PROJECT_DIR}" ]] || fail "Project directory not found: ${PROJECT_DIR}"
[[ -n "${SERVICE_USER}" ]] || fail "--service-user cannot be empty"
id "${SERVICE_USER}" >/dev/null 2>&1 || fail "User does not exist: ${SERVICE_USER}"

if [[ -z "${ENGINE_SERVICE_NAME}" ]]; then
  ENGINE_SERVICE_NAME="$(resolve_default_engine_service "${MODE}")"
fi
if [[ -z "${UPDATER_SERVICE_NAME}" ]]; then
  UPDATER_SERVICE_NAME="$(resolve_default_updater_service "${MODE}")"
fi
if [[ -z "${UPDATER_TIMER_NAME}" ]]; then
  UPDATER_TIMER_NAME="$(resolve_default_updater_timer "${MODE}")"
fi

validate_service_name "${ENGINE_SERVICE_NAME}"
validate_service_name "${UPDATER_SERVICE_NAME}"
validate_service_name "${UPDATER_TIMER_NAME}"

with_timer="$(resolve_default_with_updater_timer "${MODE}")"
if (( WITH_UPDATER_TIMER_SET == 1 )); then
  with_timer="${WITH_UPDATER_TIMER}"
fi
if (( UNINSTALL_UPDATER == 1 && WITH_UPDATER_TIMER_SET == 1 )); then
  fail "Use either --with-updater-timer or --uninstall, not both."
fi
if (( UNINSTALL_UPDATER == 1 )); then
  with_timer=0
fi
if (( with_timer == 1 )); then
  if [[ "${MODE}" == "prod" ]]; then
    FORCE_REINSTALL=1
  elif (( FORCE_REINSTALL == 0 )); then
    fail "Dev updater install requires explicit --force with --with-updater-timer."
  fi
fi

updater_py="${PROJECT_DIR}/engine/server/db/jobs/updater-worker.py"
venv_py="${PROJECT_DIR}/venv/bin/python3"
systemctl_bin="$(command -v systemctl || true)"
[[ -n "${systemctl_bin}" ]] || fail "Required command not found: systemctl"
[[ -f "${updater_py}" ]] || fail "Missing updater worker entrypoint: ${updater_py}"
[[ -x "${venv_py}" ]] || fail "Missing python interpreter in venv: ${venv_py}"

updater_unit_path="/etc/systemd/system/${UPDATER_SERVICE_NAME}.service"
updater_timer_path="/etc/systemd/system/${UPDATER_TIMER_NAME}.timer"
updater_sudoers_path="/etc/sudoers.d/${UPDATER_SERVICE_NAME}-systemctl"

if (( DRY_RUN == 0 )); then
  [[ "${EUID}" -eq 0 ]] || fail "Run as root (use sudo)."
  require_cmd systemctl
  require_cmd journalctl
fi

if (( with_timer == 0 )); then
  echo "[install-updater-service] ${MODE}: uninstall requested, removing updater units if present"
  run_cmd systemctl stop "${UPDATER_TIMER_NAME}.timer" >/dev/null 2>&1 || true
  run_cmd systemctl stop "${UPDATER_SERVICE_NAME}.service" >/dev/null 2>&1 || true
  run_cmd systemctl disable "${UPDATER_TIMER_NAME}.timer" >/dev/null 2>&1 || true
  run_cmd rm -f "${updater_timer_path}"
  run_cmd rm -f "${updater_unit_path}"
  run_cmd rm -f "${updater_sudoers_path}"
  if (( DRY_RUN == 0 )); then
    systemctl daemon-reload
    systemctl reset-failed "${UPDATER_SERVICE_NAME}.service" >/dev/null 2>&1 || true
    systemctl reset-failed "${UPDATER_TIMER_NAME}.timer" >/dev/null 2>&1 || true
  fi
  exit 0
fi

if (( DRY_RUN == 0 )); then
  require_cmd visudo
fi

if (( FORCE_REINSTALL == 1 )); then
  echo "[install-updater-service] ${MODE}: force reinstall updater units"
  run_cmd systemctl stop "${UPDATER_TIMER_NAME}.timer" >/dev/null 2>&1 || true
  run_cmd systemctl stop "${UPDATER_SERVICE_NAME}.service" >/dev/null 2>&1 || true
  run_cmd systemctl disable "${UPDATER_TIMER_NAME}.timer" >/dev/null 2>&1 || true
  run_cmd rm -f "${updater_timer_path}"
  run_cmd rm -f "${updater_unit_path}"
  run_cmd rm -f "${updater_sudoers_path}"
fi

if (( DRY_RUN == 1 )); then
  echo "[dry-run] updater service=${UPDATER_SERVICE_NAME} timer=${UPDATER_TIMER_NAME} engine_service=${ENGINE_SERVICE_NAME}"
fi

updater_exec="${venv_py} ${updater_py} --mode ${MODE} --service-name ${ENGINE_SERVICE_NAME} --systemctl-bin ${systemctl_bin} --systemctl-use-sudo ${UPDATER_FLAGS}"

updater_unit_content="$(cat <<EOF_UPDATER_UNIT
[Unit]
Description=PeerTube Updater Worker (${MODE})
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/bash -lc 'set -euo pipefail; ${updater_exec}'
TimeoutStartSec=24h
EOF_UPDATER_UNIT
)"

updater_timer_content="$(cat <<EOF_UPDATER_TIMER
[Unit]
Description=PeerTube Updater Timer (${MODE})

[Timer]
OnCalendar=${UPDATER_TIMER_ONCALENDAR}
Persistent=false
RandomizedDelaySec=0
AccuracySec=1m
Unit=${UPDATER_SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF_UPDATER_TIMER
)"

if (( DRY_RUN == 1 )); then
  echo "----- updater service preview (${UPDATER_SERVICE_NAME}.service) -----"
  printf '%s\n' "${updater_unit_content}"
  echo "----- updater timer preview (${UPDATER_TIMER_NAME}.timer) -----"
  printf '%s\n' "${updater_timer_content}"
  echo "----- updater sudoers preview (${updater_sudoers_path}) -----"
  echo "${SERVICE_USER} ALL=(root) NOPASSWD: ${systemctl_bin} stop ${ENGINE_SERVICE_NAME}, ${systemctl_bin} start ${ENGINE_SERVICE_NAME}"
  exit 0
fi

echo "[install-updater-service] ${MODE}: writing updater unit ${updater_unit_path}"
printf '%s\n' "${updater_unit_content}" > "${updater_unit_path}"

echo "[install-updater-service] ${MODE}: writing updater timer ${updater_timer_path}"
printf '%s\n' "${updater_timer_content}" > "${updater_timer_path}"

echo "[install-updater-service] ${MODE}: writing updater sudoers ${updater_sudoers_path}"
tmp_sudoers="$(mktemp)"
printf '%s\n' "${SERVICE_USER} ALL=(root) NOPASSWD: ${systemctl_bin} stop ${ENGINE_SERVICE_NAME}, ${systemctl_bin} start ${ENGINE_SERVICE_NAME}" > "${tmp_sudoers}"
visudo -cf "${tmp_sudoers}" >/dev/null
install -m 0440 "${tmp_sudoers}" "${updater_sudoers_path}"
rm -f "${tmp_sudoers}"

systemctl daemon-reload
systemctl enable "${UPDATER_TIMER_NAME}.timer" >/dev/null
systemctl restart "${UPDATER_TIMER_NAME}.timer"

timer_enabled="$(systemctl is-enabled "${UPDATER_TIMER_NAME}.timer" 2>/dev/null || true)"
timer_active="$(systemctl is-active "${UPDATER_TIMER_NAME}.timer" 2>/dev/null || true)"
if [[ "${timer_enabled}" != "enabled" || "${timer_active}" != "active" ]]; then
  echo "Updater timer failed to start for mode=${MODE}." >&2
  journalctl -u "${UPDATER_TIMER_NAME}.timer" -n 80 --no-pager >&2 || true
  exit 1
fi

echo "Updater units installed: ${UPDATER_SERVICE_NAME}.service ${UPDATER_TIMER_NAME}.timer"
