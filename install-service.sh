#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
SERVICE_USER="${SUDO_USER:-$(id -un)}"

MODE="" # prod | dev | all
MODE_SET=0
DRY_RUN=0
FORCE_REINSTALL_SET=0
FORCE_REINSTALL=0
WITH_UPDATER_TIMER_SET=0
WITH_UPDATER_TIMER=0

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
CLIENT_ENGINE_URL=""
CLIENT_ENGINE_URL_SET=0
CLIENT_PUBLISH_MODE="bridge"

UPDATER_TIMER_ONCALENDAR="${UPDATER_TIMER_ONCALENDAR:-Fri *-*-* 20:00:00}"
UPDATER_FLAGS="${UPDATER_FLAGS:---gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3}"

DEFAULT_PROD_CLIENT_SERVICE="peertube-client"
DEFAULT_PROD_ENGINE_PORT=7070
DEFAULT_PROD_CLIENT_PORT=7072

DEFAULT_DEV_CLIENT_SERVICE="peertube-client-dev"
DEFAULT_DEV_ENGINE_PORT=7171
DEFAULT_DEV_CLIENT_PORT=7172

print_usage() {
  cat <<'EOF_USAGE'
Usage: sudo ./install-service.sh [options]

Centralized installer/orchestrator for Engine + Client contours.

Modes:
  --mode prod      Install/update prod contour
  --mode dev       Install/update dev contour
  --mode all       Install/update both prod and dev contours sequentially

Default contour behavior per selected --mode
(when --force/--no-force and --with-updater-timer/--uninstall are omitted):
  prod: --force + --with-updater-timer
  dev : --force + --uninstall

Options:
  --mode <prod|dev|all>       Required installation contour mode
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

  --client-engine-url <url>              Client -> Engine URL override
  --client-publish-mode <mode>           Client publish mode (default: bridge)

  --with-updater-timer      Enable contour updater timer/service
  --uninstall               Disable/remove contour updater timer/service
  --updater-oncalendar <expr>   Systemd OnCalendar expression for updater timer
  --updater-flags <flags>       Extra flags for updater-worker.py

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
  if (( MODE_SET == 0 )); then
    fail "Missing required --mode <prod|dev|all>."
  fi
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
  local engine_installer="${PROJECT_DIR}/engine/install-engine-service.sh"
  [[ -f "${engine_installer}" ]] || fail "Missing installer: ${engine_installer}"
  local resolved_name
  resolved_name="$(bash "${engine_installer}" --mode "${contour}" --print-default-service-name)" || fail "Failed to resolve default Engine service name from ${engine_installer} for mode=${contour}"
  [[ -n "${resolved_name}" ]] || fail "Resolved empty Engine service name for mode=${contour}"
  printf '%s' "${resolved_name}"
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
  local updater_installer="${PROJECT_DIR}/engine/install-updater-service.sh"
  [[ -f "${updater_installer}" ]] || fail "Missing installer: ${updater_installer}"
  local resolved_name
  resolved_name="$(bash "${updater_installer}" --mode "${contour}" --print-default-updater-service-name)" || fail "Failed to resolve default updater service name from ${updater_installer} for mode=${contour}"
  [[ -n "${resolved_name}" ]] || fail "Resolved empty updater service name for mode=${contour}"
  printf '%s' "${resolved_name}"
}

resolve_default_updater_timer() {
  local contour="$1"
  local updater_installer="${PROJECT_DIR}/engine/install-updater-service.sh"
  [[ -f "${updater_installer}" ]] || fail "Missing installer: ${updater_installer}"
  local resolved_name
  resolved_name="$(bash "${updater_installer}" --mode "${contour}" --print-default-updater-timer-name)" || fail "Failed to resolve default updater timer name from ${updater_installer} for mode=${contour}"
  [[ -n "${resolved_name}" ]] || fail "Resolved empty updater timer name for mode=${contour}"
  printf '%s' "${resolved_name}"
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

ensure_single_contour_overrides_only() {
  if [[ "${MODE}" != "all" ]]; then
    return
  fi
  if (( ENGINE_HOST_SET == 1 || CLIENT_HOST_SET == 1 || ENGINE_PORT_SET == 1 || CLIENT_PORT_SET == 1 || ENGINE_SERVICE_NAME_SET == 1 || CLIENT_SERVICE_NAME_SET == 1 || UPDATER_SERVICE_NAME_SET == 1 || UPDATER_TIMER_NAME_SET == 1 || CLIENT_ENGINE_URL_SET == 1 )); then
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
  local updater_cmd=(
    bash
    "${PROJECT_DIR}/engine/install-updater-service.sh"
    --mode "${contour}"
    --project-dir "${PROJECT_DIR}"
    --service-user "${SERVICE_USER}"
    --engine-service-name "${engine_service_name}"
    --updater-service-name "${updater_service_name}"
    --updater-timer-name "${updater_timer_name}"
    --updater-oncalendar "${UPDATER_TIMER_ONCALENDAR}"
    --updater-flags "${UPDATER_FLAGS}"
  )
  if (( with_timer == 1 )); then
    updater_cmd+=(--with-updater-timer)
  else
    updater_cmd+=(--uninstall)
  fi
  if (( force_reinstall == 1 )); then
    updater_cmd+=(--force)
  fi
  if (( DRY_RUN == 1 )); then
    updater_cmd+=(--dry-run)
  fi
  run_cmd "${updater_cmd[@]}"
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
  local engine_ingest_base
  local with_timer
  local force_reinstall

  engine_service_name="$(resolve_default_engine_service "${contour}")"
  client_service_name="$(resolve_default_client_service "${contour}")"
  updater_service_name="$(resolve_default_updater_service "${contour}")"
  updater_timer_name="$(resolve_default_updater_timer "${contour}")"
  engine_port="$(resolve_default_engine_port "${contour}")"
  client_port="$(resolve_default_client_port "${contour}")"
  engine_host="${ENGINE_HOST}"
  client_host="${CLIENT_HOST}"

  if [[ "${contour}" == "prod" ]]; then
    with_timer=1
    force_reinstall=1
  else
    with_timer=0
    force_reinstall=1
  fi

  if (( ENGINE_SERVICE_NAME_SET == 1 )); then engine_service_name="${ENGINE_SERVICE_NAME}"; fi
  if (( CLIENT_SERVICE_NAME_SET == 1 )); then client_service_name="${CLIENT_SERVICE_NAME}"; fi
  if (( UPDATER_SERVICE_NAME_SET == 1 )); then updater_service_name="${UPDATER_SERVICE_NAME}"; fi
  if (( UPDATER_TIMER_NAME_SET == 1 )); then updater_timer_name="${UPDATER_TIMER_NAME}"; fi
  if (( ENGINE_PORT_SET == 1 )); then engine_port="${ENGINE_PORT}"; fi
  if (( CLIENT_PORT_SET == 1 )); then client_port="${CLIENT_PORT}"; fi
  if (( FORCE_REINSTALL_SET == 1 )); then force_reinstall="${FORCE_REINSTALL}"; fi
  if (( WITH_UPDATER_TIMER_SET == 1 )); then with_timer="${WITH_UPDATER_TIMER}"; fi

  validate_service_name "${engine_service_name}"
  validate_service_name "${client_service_name}"
  validate_service_name "${updater_service_name}"
  validate_service_name "${updater_timer_name}"
  validate_port "${engine_port}"
  validate_port "${client_port}"

  if [[ "${engine_port}" == "${client_port}" ]]; then
    fail "Engine and Client ports must differ for contour=${contour}"
  fi

  if (( CLIENT_ENGINE_URL_SET == 1 )); then
    engine_ingest_base="${CLIENT_ENGINE_URL}"
  else
    engine_ingest_base="http://${engine_host}:${engine_port}"
  fi

  echo "[install-service] contour=${contour} force=${force_reinstall} updater_timer=${with_timer}"
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
    --engine-url "${engine_ingest_base}"
    --publish-mode "${CLIENT_PUBLISH_MODE}"
  )
  if (( force_reinstall == 1 )); then
    client_cmd+=(--force)
  fi
  if (( DRY_RUN == 1 )); then
    client_cmd+=(--dry-run)
  fi

  run_cmd "${engine_cmd[@]}"
  run_cmd "${client_cmd[@]}"

  install_updater_for_contour \
    "${contour}" \
    "${engine_service_name}" \
    "${updater_service_name}" \
    "${updater_timer_name}" \
    "${with_timer}" \
    "${force_reinstall}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode|--contour)
      MODE="${2:-}"
      MODE_SET=1
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
    --client-engine-url)
      CLIENT_ENGINE_URL="${2:-}"
      CLIENT_ENGINE_URL_SET=1
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
    --uninstall)
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
[[ -f "${PROJECT_DIR}/engine/install-updater-service.sh" ]] || fail "Missing installer: ${PROJECT_DIR}/engine/install-updater-service.sh"
[[ -f "${PROJECT_DIR}/client/install-client-service.sh" ]] || fail "Missing installer: ${PROJECT_DIR}/client/install-client-service.sh"

if (( DRY_RUN == 0 )); then
  [[ "${EUID}" -eq 0 ]] || fail "Run as root (use sudo)."
  require_cmd systemctl
  require_cmd journalctl
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
