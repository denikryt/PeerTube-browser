#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
SERVICE_USER="${SUDO_USER:-$(id -un)}"

MODE="prod" # prod | dev | all
DRY_RUN=0
FORCE_REINSTALL_SET=0
FORCE_REINSTALL=0
WITH_UPDATER_TIMER_SET=0
WITH_UPDATER_TIMER=0
REINSTALL_UPDATER_ONLY=0

ENGINE_HOST="127.0.0.1"
CLIENT_HOST="127.0.0.1"
ENGINE_HOST_SET=0
CLIENT_HOST_SET=0
ENGINE_PORT=""
CLIENT_PORT=""
ENGINE_PORT_SET=0
CLIENT_PORT_SET=0
ENGINE_SERVICE_NAME=""
CLIENT_SERVICE_NAME=""
UPDATER_SERVICE_NAME=""
UPDATER_TIMER_NAME=""
ENGINE_SERVICE_NAME_SET=0
CLIENT_SERVICE_NAME_SET=0
UPDATER_SERVICE_NAME_SET=0
UPDATER_TIMER_NAME_SET=0
CLIENT_ENGINE_INGEST_BASE_URL=""
CLIENT_ENGINE_INGEST_BASE_URL_SET=0
CLIENT_USERS_DB=""
CLIENT_USERS_DB_SET=0
CLIENT_PUBLISH_MODE="bridge"

UPDATER_TIMER_ONCALENDAR="${UPDATER_TIMER_ONCALENDAR:-Fri *-*-* 20:00:00}"
UPDATER_FLAGS="${UPDATER_FLAGS:---gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3}"
UPDATER_WEEK_STATE_DIR=""
UPDATER_WEEK_STATE_DIR_SET=0

DEFAULT_PROD_ENGINE_SERVICE="peertube-engine"
DEFAULT_PROD_CLIENT_SERVICE="peertube-client"
DEFAULT_PROD_UPDATER_SERVICE="peertube-updater"
DEFAULT_PROD_UPDATER_TIMER="peertube-updater"
DEFAULT_PROD_ENGINE_PORT=7070
DEFAULT_PROD_CLIENT_PORT=7072
DEFAULT_PROD_USERS_DB="client/backend/db/users.db"
DEFAULT_PROD_UPDATER_STATE_DIR="/var/lib/peertube-browser"

DEFAULT_DEV_ENGINE_SERVICE="peertube-engine-dev"
DEFAULT_DEV_CLIENT_SERVICE="peertube-client-dev"
DEFAULT_DEV_UPDATER_SERVICE="peertube-updater-dev"
DEFAULT_DEV_UPDATER_TIMER="peertube-updater-dev"
DEFAULT_DEV_ENGINE_PORT=7171
DEFAULT_DEV_CLIENT_PORT=7172
DEFAULT_DEV_USERS_DB="client/backend/db/users-dev.db"
DEFAULT_DEV_UPDATER_STATE_DIR="/var/lib/peertube-browser-dev"

print_usage() {
  cat <<'EOF_USAGE'
Usage: sudo ./install-service.sh [options]

Centralized installer/orchestrator for Engine + Client contours.

Modes:
  --mode prod      Install/update prod contour (default)
  --mode dev       Install/update dev contour
  --mode all       Install/update both prod and dev contours sequentially

Options:
  --mode <prod|dev|all>       Installation contour mode
  --contour <prod|dev|all>    Alias for --mode
  --project-dir <path>        Project root path (default: script directory)
  --service-user <user>       Unix user for Engine/Client/updater units

  --engine-host <host>        Engine host override (single-contour mode only)
  --engine-port <port>        Engine port override (single-contour mode only)
  --client-host <host>        Client host override (single-contour mode only)
  --client-port <port>        Client port override (single-contour mode only)

  --engine-service-name <name>  Engine unit base name override (single-contour mode only)
  --client-service-name <name>  Client unit base name override (single-contour mode only)
  --updater-service-name <name> Updater service base name override (single-contour mode only)
  --updater-timer-name <name>   Updater timer base name override (single-contour mode only)

  --client-engine-ingest-base-url <url>  Client -> Engine ingest base override
  --client-users-db <path>               Client users DB path relative to project root
  --client-publish-mode <mode>           Client publish mode (default: bridge)

  --with-updater-timer      Enable contour updater timer/service
  --without-updater-timer   Disable/remove contour updater timer/service
  --updater-oncalendar <expr>   Systemd OnCalendar expression for updater timer
  --updater-flags <flags>       Extra flags for updater-worker.py
  --updater-week-state-dir <path>  Week-state directory path for updater gate
  --reinstall-updater-only     Reinstall only updater units (skip Engine/Client installers)

  --force                  Force reinstall selected contour units
  --no-force               Disable force reinstall
  --dry-run                Print actions and generated units without applying
  -h, --help               Show this help
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

validate_port() {
  local value="$1"
  [[ "${value}" =~ ^[0-9]+$ ]] || fail "Port must be numeric: ${value}"
  (( value >= 1 && value <= 65535 )) || fail "Port must be in range 1..65535: ${value}"
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

resolve_default_engine_port() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_ENGINE_PORT}"
  else
    printf '%s' "${DEFAULT_DEV_ENGINE_PORT}"
  fi
}

resolve_default_client_port() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_CLIENT_PORT}"
  else
    printf '%s' "${DEFAULT_DEV_CLIENT_PORT}"
  fi
}

resolve_default_users_db() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${DEFAULT_PROD_USERS_DB}"
  else
    printf '%s' "${DEFAULT_DEV_USERS_DB}"
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
  if (( ENGINE_HOST_SET == 1 || CLIENT_HOST_SET == 1 || ENGINE_PORT_SET == 1 || CLIENT_PORT_SET == 1 || ENGINE_SERVICE_NAME_SET == 1 || CLIENT_SERVICE_NAME_SET == 1 || UPDATER_SERVICE_NAME_SET == 1 || UPDATER_TIMER_NAME_SET == 1 || CLIENT_ENGINE_INGEST_BASE_URL_SET == 1 || CLIENT_USERS_DB_SET == 1 )); then
    fail "Contour-specific overrides are not allowed with --mode all. Run per contour or use defaults."
  fi
}

install_updater_for_contour() {
  local contour="$1"
  local engine_service_name="$2"
  local updater_service_name="$3"
  local updater_timer_name="$4"
  local with_timer="$5"
  local force_reinstall="$6"
  local week_state_dir="$7"

  local updater_py="${PROJECT_DIR}/engine/server/db/jobs/updater-worker.py"
  local venv_py="${PROJECT_DIR}/venv/bin/python3"
  local systemctl_bin
  systemctl_bin="$(command -v systemctl)"

  local updater_unit_path="/etc/systemd/system/${updater_service_name}.service"
  local updater_timer_path="/etc/systemd/system/${updater_timer_name}.timer"
  local updater_sudoers_path="/etc/sudoers.d/${updater_service_name}-systemctl"
  local week_state_file="${week_state_dir}/updater-last-success-week.txt"

  validate_service_name "${updater_service_name}"
  validate_service_name "${updater_timer_name}"

  if (( with_timer == 0 )); then
    echo "[install-service] ${contour}: updater timer disabled, removing updater units if present"
    run_cmd systemctl stop "${updater_timer_name}.timer" >/dev/null 2>&1 || true
    run_cmd systemctl stop "${updater_service_name}.service" >/dev/null 2>&1 || true
    run_cmd systemctl disable "${updater_timer_name}.timer" >/dev/null 2>&1 || true
    run_cmd rm -f "${updater_timer_path}"
    run_cmd rm -f "${updater_unit_path}"
    run_cmd rm -f "${updater_sudoers_path}"
    if (( DRY_RUN == 0 )); then
      systemctl daemon-reload
      systemctl reset-failed "${updater_service_name}.service" >/dev/null 2>&1 || true
      systemctl reset-failed "${updater_timer_name}.timer" >/dev/null 2>&1 || true
    fi
    return
  fi

  [[ -f "${updater_py}" ]] || fail "Missing updater worker entrypoint: ${updater_py}"
  [[ -x "${venv_py}" ]] || fail "Missing python interpreter in venv: ${venv_py}"
  if (( DRY_RUN == 0 )); then
    require_cmd visudo
  fi

  if (( force_reinstall == 1 )); then
    echo "[install-service] ${contour}: force reinstall updater units"
    run_cmd systemctl stop "${updater_timer_name}.timer" >/dev/null 2>&1 || true
    run_cmd systemctl stop "${updater_service_name}.service" >/dev/null 2>&1 || true
    run_cmd systemctl disable "${updater_timer_name}.timer" >/dev/null 2>&1 || true
    run_cmd rm -f "${updater_timer_path}"
    run_cmd rm -f "${updater_unit_path}"
    run_cmd rm -f "${updater_sudoers_path}"
  fi

  if (( DRY_RUN == 1 )); then
    echo "[dry-run] updater service=${updater_service_name} timer=${updater_timer_name} engine_service=${engine_service_name}"
    echo "[dry-run] updater state dir=${week_state_dir} file=${week_state_file}"
  else
    mkdir -p "${week_state_dir}"
    chown "${SERVICE_USER}:${SERVICE_USER}" "${week_state_dir}" || true
    chmod 755 "${week_state_dir}" || true
  fi

  local updater_exec
  updater_exec="${venv_py} ${updater_py} --service-name ${engine_service_name} --systemctl-bin ${systemctl_bin} --systemctl-use-sudo ${UPDATER_FLAGS}"

  local updater_unit_content
  updater_unit_content="$(cat <<EOF_UPDATER_UNIT
[Unit]
Description=PeerTube Updater Worker (${contour})
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/bash -lc 'set -euo pipefail; week_id="\\\$(date +%G-%V)"; state_file="${week_state_file}"; if [[ -f "\\\$state_file" ]] && [[ "\\\$(cat "\\\$state_file" 2>/dev/null || true)" == "\\\$week_id" ]]; then echo "[updater] weekly gate: already successful in week \\\$week_id, skip"; exit 0; fi; ${updater_exec}; printf "%s\\n" "\\\$week_id" > "\\\$state_file"'
TimeoutStartSec=24h
EOF_UPDATER_UNIT
)"

  local updater_timer_content
  updater_timer_content="$(cat <<EOF_UPDATER_TIMER
[Unit]
Description=PeerTube Updater Timer (${contour})

[Timer]
OnCalendar=${UPDATER_TIMER_ONCALENDAR}
Persistent=false
RandomizedDelaySec=0
AccuracySec=1m
Unit=${updater_service_name}.service

[Install]
WantedBy=timers.target
EOF_UPDATER_TIMER
)"

  if (( DRY_RUN == 1 )); then
    echo "----- updater service preview (${updater_service_name}.service) -----"
    printf '%s\n' "${updater_unit_content}"
    echo "----- updater timer preview (${updater_timer_name}.timer) -----"
    printf '%s\n' "${updater_timer_content}"
    echo "----- updater sudoers preview (${updater_sudoers_path}) -----"
    echo "${SERVICE_USER} ALL=(root) NOPASSWD: ${systemctl_bin} stop ${engine_service_name}, ${systemctl_bin} start ${engine_service_name}"
    return
  fi

  echo "[install-service] ${contour}: writing updater unit ${updater_unit_path}"
  printf '%s\n' "${updater_unit_content}" > "${updater_unit_path}"

  echo "[install-service] ${contour}: writing updater timer ${updater_timer_path}"
  printf '%s\n' "${updater_timer_content}" > "${updater_timer_path}"

  echo "[install-service] ${contour}: writing updater sudoers ${updater_sudoers_path}"
  local tmp_sudoers
  tmp_sudoers="$(mktemp)"
  printf '%s\n' "${SERVICE_USER} ALL=(root) NOPASSWD: ${systemctl_bin} stop ${engine_service_name}, ${systemctl_bin} start ${engine_service_name}" > "${tmp_sudoers}"
  visudo -cf "${tmp_sudoers}" >/dev/null
  install -m 0440 "${tmp_sudoers}" "${updater_sudoers_path}"
  rm -f "${tmp_sudoers}"

  systemctl daemon-reload
  systemctl enable "${updater_timer_name}.timer" >/dev/null
  systemctl restart "${updater_timer_name}.timer"

  local timer_enabled
  local timer_active
  timer_enabled="$(systemctl is-enabled "${updater_timer_name}.timer" 2>/dev/null || true)"
  timer_active="$(systemctl is-active "${updater_timer_name}.timer" 2>/dev/null || true)"
  if [[ "${timer_enabled}" != "enabled" || "${timer_active}" != "active" ]]; then
    echo "Updater timer failed to start for contour=${contour}." >&2
    journalctl -u "${updater_timer_name}.timer" -n 80 --no-pager >&2 || true
    exit 1
  fi
}

install_contour() {
  local contour="$1"

  local engine_service_name
  local client_service_name
  local updater_service_name
  local updater_timer_name
  local engine_port
  local client_port
  local engine_host
  local client_host
  local users_db
  local engine_ingest_base
  local with_timer
  local force_reinstall
  local updater_force_reinstall
  local week_state_dir

  engine_service_name="$(resolve_default_engine_service "${contour}")"
  client_service_name="$(resolve_default_client_service "${contour}")"
  updater_service_name="$(resolve_default_updater_service "${contour}")"
  updater_timer_name="$(resolve_default_updater_timer "${contour}")"
  engine_port="$(resolve_default_engine_port "${contour}")"
  client_port="$(resolve_default_client_port "${contour}")"
  engine_host="${ENGINE_HOST}"
  client_host="${CLIENT_HOST}"
  users_db="$(resolve_default_users_db "${contour}")"
  week_state_dir="$(resolve_default_updater_state_dir "${contour}")"

  if [[ "${contour}" == "prod" ]]; then
    with_timer=1
    force_reinstall=1
  else
    with_timer=0
    force_reinstall=0
  fi

  if (( ENGINE_SERVICE_NAME_SET == 1 )); then engine_service_name="${ENGINE_SERVICE_NAME}"; fi
  if (( CLIENT_SERVICE_NAME_SET == 1 )); then client_service_name="${CLIENT_SERVICE_NAME}"; fi
  if (( UPDATER_SERVICE_NAME_SET == 1 )); then updater_service_name="${UPDATER_SERVICE_NAME}"; fi
  if (( UPDATER_TIMER_NAME_SET == 1 )); then updater_timer_name="${UPDATER_TIMER_NAME}"; fi
  if (( ENGINE_PORT_SET == 1 )); then engine_port="${ENGINE_PORT}"; fi
  if (( CLIENT_PORT_SET == 1 )); then client_port="${CLIENT_PORT}"; fi
  if (( CLIENT_USERS_DB_SET == 1 )); then users_db="${CLIENT_USERS_DB}"; fi
  if (( UPDATER_WEEK_STATE_DIR_SET == 1 )); then week_state_dir="${UPDATER_WEEK_STATE_DIR}"; fi

  if (( FORCE_REINSTALL_SET == 1 )); then force_reinstall="${FORCE_REINSTALL}"; fi
  if (( WITH_UPDATER_TIMER_SET == 1 )); then with_timer="${WITH_UPDATER_TIMER}"; fi
  if (( REINSTALL_UPDATER_ONLY == 1 && WITH_UPDATER_TIMER_SET == 0 )); then
    with_timer=1
  fi
  updater_force_reinstall="${force_reinstall}"
  if (( REINSTALL_UPDATER_ONLY == 1 )); then
    updater_force_reinstall=1
  fi

  validate_service_name "${engine_service_name}"
  validate_service_name "${client_service_name}"
  validate_service_name "${updater_service_name}"
  validate_service_name "${updater_timer_name}"
  validate_port "${engine_port}"
  validate_port "${client_port}"

  if [[ "${engine_port}" == "${client_port}" ]]; then
    fail "Engine and Client ports must differ for contour=${contour}"
  fi

  if (( CLIENT_ENGINE_INGEST_BASE_URL_SET == 1 )); then
    engine_ingest_base="${CLIENT_ENGINE_INGEST_BASE_URL}"
  else
    engine_ingest_base="http://${engine_host}:${engine_port}"
  fi

  echo "[install-service] contour=${contour} force=${force_reinstall} updater_timer=${with_timer} updater_only=${REINSTALL_UPDATER_ONLY}"
  echo "[install-service] contour=${contour} engine=${engine_service_name} ${engine_host}:${engine_port}"
  echo "[install-service] contour=${contour} client=${client_service_name} ${client_host}:${client_port} ingest=${engine_ingest_base}"

  local engine_cmd=(
    bash
    "${PROJECT_DIR}/engine/install-engine-service.sh"
    --mode "${contour}"
    --project-dir "${PROJECT_DIR}"
    --service-user "${SERVICE_USER}"
    --service-name "${engine_service_name}"
    --host "${engine_host}"
    --port "${engine_port}"
  )
  if (( force_reinstall == 1 )); then
    engine_cmd+=(--force)
  fi
  if (( DRY_RUN == 1 )); then
    engine_cmd+=(--dry-run)
  fi

  local client_cmd=(
    bash
    "${PROJECT_DIR}/client/install-client-service.sh"
    --mode "${contour}"
    --project-dir "${PROJECT_DIR}"
    --service-user "${SERVICE_USER}"
    --service-name "${client_service_name}"
    --host "${client_host}"
    --port "${client_port}"
    --engine-ingest-base "${engine_ingest_base}"
    --users-db "${users_db}"
    --publish-mode "${CLIENT_PUBLISH_MODE}"
  )
  if (( force_reinstall == 1 )); then
    client_cmd+=(--force)
  fi
  if (( DRY_RUN == 1 )); then
    client_cmd+=(--dry-run)
  fi

  if (( REINSTALL_UPDATER_ONLY == 0 )); then
    run_cmd "${engine_cmd[@]}"
    run_cmd "${client_cmd[@]}"
  fi

  install_updater_for_contour \
    "${contour}" \
    "${engine_service_name}" \
    "${updater_service_name}" \
    "${updater_timer_name}" \
    "${with_timer}" \
    "${updater_force_reinstall}" \
    "${week_state_dir}"
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
    --service-user)
      SERVICE_USER="${2:-}"
      shift 2
      ;;
    --engine-host)
      ENGINE_HOST="${2:-}"
      ENGINE_HOST_SET=1
      shift 2
      ;;
    --engine-port)
      ENGINE_PORT="${2:-}"
      ENGINE_PORT_SET=1
      shift 2
      ;;
    --client-host)
      CLIENT_HOST="${2:-}"
      CLIENT_HOST_SET=1
      shift 2
      ;;
    --client-port)
      CLIENT_PORT="${2:-}"
      CLIENT_PORT_SET=1
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
    --client-engine-ingest-base-url)
      CLIENT_ENGINE_INGEST_BASE_URL="${2:-}"
      CLIENT_ENGINE_INGEST_BASE_URL_SET=1
      shift 2
      ;;
    --client-users-db)
      CLIENT_USERS_DB="${2:-}"
      CLIENT_USERS_DB_SET=1
      shift 2
      ;;
    --client-publish-mode)
      CLIENT_PUBLISH_MODE="${2:-}"
      shift 2
      ;;
    --with-updater-timer)
      WITH_UPDATER_TIMER_SET=1
      WITH_UPDATER_TIMER=1
      shift
      ;;
    --without-updater-timer)
      WITH_UPDATER_TIMER_SET=1
      WITH_UPDATER_TIMER=0
      shift
      ;;
    --updater-oncalendar)
      UPDATER_TIMER_ONCALENDAR="${2:-}"
      shift 2
      ;;
    --updater-flags)
      UPDATER_FLAGS="${2:-}"
      shift 2
      ;;
    --updater-week-state-dir)
      UPDATER_WEEK_STATE_DIR="${2:-}"
      UPDATER_WEEK_STATE_DIR_SET=1
      shift 2
      ;;
    --reinstall-updater-only)
      REINSTALL_UPDATER_ONLY=1
      shift
      ;;
    --force)
      FORCE_REINSTALL_SET=1
      FORCE_REINSTALL=1
      shift
      ;;
    --no-force)
      FORCE_REINSTALL_SET=1
      FORCE_REINSTALL=0
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
[[ -n "${SERVICE_USER}" ]] || fail "--service-user cannot be empty"
[[ -n "${ENGINE_HOST}" ]] || fail "--engine-host cannot be empty"
[[ -n "${CLIENT_HOST}" ]] || fail "--client-host cannot be empty"
[[ -n "${CLIENT_PUBLISH_MODE}" ]] || fail "--client-publish-mode cannot be empty"

PROJECT_DIR="$(realpath "${PROJECT_DIR}")"
[[ -d "${PROJECT_DIR}" ]] || fail "Project directory not found: ${PROJECT_DIR}"
[[ -f "${PROJECT_DIR}/engine/install-engine-service.sh" ]] || fail "Missing installer: ${PROJECT_DIR}/engine/install-engine-service.sh"
[[ -f "${PROJECT_DIR}/client/install-client-service.sh" ]] || fail "Missing installer: ${PROJECT_DIR}/client/install-client-service.sh"

if (( DRY_RUN == 0 )); then
  [[ "${EUID}" -eq 0 ]] || fail "Run as root (use sudo)."
  require_cmd systemctl
  require_cmd journalctl
  require_cmd visudo
fi
id "${SERVICE_USER}" >/dev/null 2>&1 || fail "User does not exist: ${SERVICE_USER}"

ensure_single_contour_overrides_only

if [[ "${MODE}" == "all" ]]; then
  install_contour "prod"
  install_contour "dev"
else
  install_contour "${MODE}"
fi

echo "[install-service] Completed mode=${MODE}"
