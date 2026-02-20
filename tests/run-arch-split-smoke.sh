#!/usr/bin/env bash
set -uo pipefail

ENGINE_URL="${ENGINE_URL:-http://127.0.0.1:7072}"
CLIENT_URL="${CLIENT_URL:-http://127.0.0.1:7272}"
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-30}"
CURL_MAX_TIME="${CURL_MAX_TIME:-10}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_PY=""

TMP_DIR="$(mktemp -d /tmp/arch-split-smoke.XXXXXX)"
ENGINE_LOG="${TMP_DIR}/engine.log"
CLIENT_LOG="${TMP_DIR}/client.log"
LOG_ROOT_DIR="${ROOT_DIR}/tmp/arch-split-smoke-logs"
RUN_LOG="${LOG_ROOT_DIR}/run-arch-split-smoke.run.log"
CHECK_LOG="${LOG_ROOT_DIR}/run-arch-split-smoke.checks.log"
ERROR_LOG="${LOG_ROOT_DIR}/run-arch-split-smoke.errors.log"

ENGINE_PID=""
CLIENT_PID=""
CHECK_COUNT=0
ERROR_COUNT=0
LAST_NAME=""
LAST_METHOD=""
LAST_URL=""
LAST_STATUS=""
LAST_BODY_FILE=""
REQUEST_STATUS=""
CLEANUP_DONE=0

declare -a ERRORS=()

mkdir -p "${LOG_ROOT_DIR}"
: > "${RUN_LOG}"
: > "${CHECK_LOG}"
: > "${ERROR_LOG}"

print_help() {
  cat <<'EOF'
Usage: tests/run-arch-split-smoke.sh [options]

This smoke script:
1) starts Engine and Client processes,
2) runs split-boundary + bridge-flow checks,
3) collects all check failures,
4) prints full failure summary,
5) always stops started processes on exit.

Options:
  --engine-url <url>      Engine base URL (default: http://127.0.0.1:7072)
  --client-url <url>      Client base URL (default: http://127.0.0.1:7272)
  --startup-timeout <s>   Max wait for process readiness (default: 30)
  --max-time <seconds>    curl timeout per request (default: 10)
  -h, --help              Show this help

Environment overrides:
  ENGINE_URL
  CLIENT_URL
  STARTUP_TIMEOUT_SECONDS
  CURL_MAX_TIME
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --engine-url)
      ENGINE_URL="${2:-}"
      shift 2
      ;;
    --client-url)
      CLIENT_URL="${2:-}"
      shift 2
      ;;
    --startup-timeout)
      STARTUP_TIMEOUT_SECONDS="${2:-}"
      shift 2
      ;;
    --max-time)
      CURL_MAX_TIME="${2:-}"
      shift 2
      ;;
    -h|--help)
      print_help
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      print_help
      exit 1
      ;;
  esac
done

ENGINE_URL="${ENGINE_URL%/}"
CLIENT_URL="${CLIENT_URL%/}"

log() {
  local message="[arch-split-smoke] $*"
  echo "${message}"
  printf '%s\n' "${message}" >> "${RUN_LOG}"
}

record_error() {
  local message="$1"
  ERROR_COUNT=$((ERROR_COUNT + 1))
  ERRORS+=("${message}")
  printf '%s\n' "${message}" >> "${ERROR_LOG}"
  printf '[arch-split-smoke] ERROR: %s\n' "${message}" >> "${RUN_LOG}"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "[arch-split-smoke] ERROR: Missing required command: $1" >&2
    exit 1
  }
}

resolve_runtime_python() {
  if [[ -x "${ROOT_DIR}/venv/bin/python3" ]]; then
    echo "${ROOT_DIR}/venv/bin/python3"
    return
  fi
  if [[ -x "${ROOT_DIR}/venv/bin/python" ]]; then
    echo "${ROOT_DIR}/venv/bin/python"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  echo ""
}

url_part() {
  local url="$1"
  local part="$2"
  python3 - "$url" "$part" <<'PY'
import sys
from urllib.parse import urlparse

url = sys.argv[1]
part = sys.argv[2]
parsed = urlparse(url)
if part == "host":
    print(parsed.hostname or "")
elif part == "port":
    if parsed.port is not None:
        print(parsed.port)
    elif parsed.scheme == "https":
        print(443)
    else:
        print(80)
else:
    print("")
PY
}

is_port_free() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq ":${port}\$"; then
      return 1
    fi
    return 0
  fi
  if command -v lsof >/dev/null 2>&1; then
    if lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
      return 1
    fi
    return 0
  fi
  return 0
}

stop_process() {
  local name="$1"
  local pid="$2"
  if [[ -z "${pid}" ]]; then
    return
  fi
  if ! kill -0 "${pid}" >/dev/null 2>&1; then
    return
  fi
  log "Stopping ${name} pid=${pid}"
  kill "${pid}" >/dev/null 2>&1 || true
  for _ in {1..30}; do
    if ! kill -0 "${pid}" >/dev/null 2>&1; then
      return
    fi
    sleep 0.2
  done
  kill -9 "${pid}" >/dev/null 2>&1 || true
}

cleanup() {
  if (( CLEANUP_DONE == 1 )); then
    return
  fi
  CLEANUP_DONE=1

  stop_process "Client" "${CLIENT_PID}"
  stop_process "Engine" "${ENGINE_PID}"

  if (( ERROR_COUNT > 0 )); then
    echo "[arch-split-smoke] Logs saved in ${TMP_DIR}" >&2
  else
    rm -rf "${TMP_DIR}"
  fi
}

on_signal() {
  record_error "Interrupted by signal"
  exit 130
}

trap cleanup EXIT
trap on_signal INT TERM

request_json() {
  local name="$1"
  local method="$2"
  local url="$3"
  local body="${4-}"

  local body_file="${TMP_DIR}/${name}.json"
  local status=""
  local curl_exit=0

  if [[ -n "${body}" ]]; then
    status="$(curl -sS --max-time "${CURL_MAX_TIME}" \
      -X "${method}" \
      -H "content-type: application/json" \
      --data "${body}" \
      -o "${body_file}" \
      -w "%{http_code}" \
      "${url}")" || curl_exit=$?
  else
    status="$(curl -sS --max-time "${CURL_MAX_TIME}" \
      -X "${method}" \
      -o "${body_file}" \
      -w "%{http_code}" \
      "${url}")" || curl_exit=$?
  fi

  LAST_NAME="${name}"
  LAST_METHOD="${method}"
  LAST_URL="${url}"
  LAST_BODY_FILE="${body_file}"

  if (( curl_exit != 0 )); then
    REQUEST_STATUS="CURL_ERROR:${curl_exit}"
    LAST_STATUS="${REQUEST_STATUS}"
    return 0
  fi

  REQUEST_STATUS="${status}"
  LAST_STATUS="${REQUEST_STATUS}"
}

wait_for_health_200() {
  local name="$1"
  local url="$2"
  local timeout="$3"
  local status=""
  for ((i = 0; i < timeout; i++)); do
    request_json "${name}" GET "${url}"
    status="${REQUEST_STATUS}"
    if [[ "${status}" == "200" ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

log_check_result() {
  local result="$1"
  local name="$2"
  local method="$3"
  local url="$4"
  local status="$5"
  local expectation="$6"
  local line="${result} check=${name} method=${method} url=${url} status=${status} expect=${expectation}"
  printf '%s\n' "${line}" >> "${CHECK_LOG}"
  printf '[arch-split-smoke] %s\n' "${line}" >> "${RUN_LOG}"
}

extract_seed_uuid_host() {
  local file_path="$1"
  python3 - "$file_path" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)

rows = payload.get("rows") if isinstance(payload, dict) else payload
if not isinstance(rows, list) or not rows:
    raise SystemExit("recommendations response has empty rows")

for row in rows:
    if not isinstance(row, dict):
        continue
    uuid = row.get("video_uuid") or row.get("videoUuid") or row.get("uuid")
    host = row.get("instance_domain") or row.get("instanceDomain") or row.get("host")
    if uuid and host:
        print(uuid)
        print(host)
        raise SystemExit(0)

raise SystemExit("no row with both uuid and host found in recommendations")
PY
}

validate_user_action_response() {
  local file_path="$1"
  python3 - "$file_path" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)

if not isinstance(payload, dict):
    raise SystemExit("user-action response is not an object")
if payload.get("ok") is not True:
    raise SystemExit("user-action response field ok is not true")
if payload.get("bridge_ok") is not True:
    raise SystemExit("user-action response field bridge_ok is not true")
bridge_error = payload.get("bridge_error")
if bridge_error not in (None, ""):
    raise SystemExit(f"user-action bridge_error is not empty: {bridge_error}")
PY
}

validate_profile_likes_response() {
  local file_path="$1"
  python3 - "$file_path" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)

if not isinstance(payload, dict):
    raise SystemExit("profile likes response is not an object")
likes = payload.get("likes")
if not isinstance(likes, list):
    raise SystemExit("profile likes response field likes is not an array")
if len(likes) < 1:
    raise SystemExit("profile likes array is empty after like flow")
PY
}

check_status_eq() {
  local name="$1"
  local method="$2"
  local url="$3"
  local expected="$4"
  local body="${5-}"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  local status
  request_json "${name}" "${method}" "${url}" "${body}"
  status="${REQUEST_STATUS}"
  if [[ "${status}" == CURL_ERROR:* ]]; then
    log_check_result "FAIL" "${name}" "${method}" "${url}" "${status}" "=${expected}"
    record_error "${name}: request failed (${status})"
    return
  fi
  if [[ "${status}" != "${expected}" ]]; then
    log_check_result "FAIL" "${name}" "${method}" "${url}" "${status}" "=${expected}"
    record_error "${name}: expected HTTP ${expected}, got ${status}"
    return
  fi
  log_check_result "PASS" "${name}" "${method}" "${url}" "${status}" "=${expected}"
}

check_status_non_success() {
  local name="$1"
  local method="$2"
  local url="$3"
  local body="${4-}"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  local status
  request_json "${name}" "${method}" "${url}" "${body}"
  status="${REQUEST_STATUS}"
  if [[ "${status}" == CURL_ERROR:* ]]; then
    log_check_result "FAIL" "${name}" "${method}" "${url}" "${status}" ">=400"
    record_error "${name}: request failed (${status})"
    return
  fi
  if [[ ! "${status}" =~ ^[0-9]+$ ]]; then
    log_check_result "FAIL" "${name}" "${method}" "${url}" "${status}" ">=400"
    record_error "${name}: non-numeric status ${status}"
    return
  fi
  if (( status < 400 )); then
    log_check_result "FAIL" "${name}" "${method}" "${url}" "${status}" ">=400"
    record_error "${name}: expected non-success status, got ${status}"
    return
  fi
  log_check_result "PASS" "${name}" "${method}" "${url}" "${status}" ">=400"
}

run_boundary_contract_check() {
  local name="client_engine_boundary_contract"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  if bash "${ROOT_DIR}/tests/check-client-engine-boundary.sh" >"${TMP_DIR}/${name}.log" 2>&1; then
    log_check_result "PASS" "${name}" "CHECK" "${ROOT_DIR}/tests/check-client-engine-boundary.sh" "OK" "no direct engine.server imports or Engine DB paths in client/backend"
    return
  fi
  log_check_result "FAIL" "${name}" "CHECK" "${ROOT_DIR}/tests/check-client-engine-boundary.sh" "ERROR" "no direct engine.server imports or Engine DB paths in client/backend"
  record_error "${name}: $(sed -n '1,120p' "${TMP_DIR}/${name}.log" | tr '\n' ' ' | sed 's/[[:space:]]\\+/ /g')"
}

run_frontend_gateway_contract_check() {
  local name="frontend_client_gateway_contract"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  if bash "${ROOT_DIR}/tests/check-frontend-client-gateway.sh" >"${TMP_DIR}/${name}.log" 2>&1; then
    log_check_result "PASS" "${name}" "CHECK" "${ROOT_DIR}/tests/check-frontend-client-gateway.sh" "OK" "no direct Engine API base usage in frontend src"
    return
  fi
  log_check_result "FAIL" "${name}" "CHECK" "${ROOT_DIR}/tests/check-frontend-client-gateway.sh" "ERROR" "no direct Engine API base usage in frontend src"
  record_error "${name}: $(sed -n '1,120p' "${TMP_DIR}/${name}.log" | tr '\n' ' ' | sed 's/[[:space:]]\\+/ /g')"
}

run_engine_users_db_fd_check() {
  local name="engine_users_db_fd_absent"
  local users_db_path="${ROOT_DIR}/engine/server/db/users.db"
  CHECK_COUNT=$((CHECK_COUNT + 1))

  if [[ -z "${ENGINE_PID}" ]]; then
    log_check_result "FAIL" "${name}" "CHECK" "/proc/<engine-pid>/fd" "ERROR" "Engine process pid is set"
    record_error "${name}: Engine pid is empty"
    return
  fi
  if [[ ! -d "/proc/${ENGINE_PID}/fd" ]]; then
    log_check_result "FAIL" "${name}" "CHECK" "/proc/${ENGINE_PID}/fd" "ERROR" "Engine /proc fd directory exists"
    record_error "${name}: missing /proc/${ENGINE_PID}/fd"
    return
  fi

  if python3 - "${ENGINE_PID}" "${users_db_path}" >"${TMP_DIR}/${name}.log" 2>&1 <<'PY'
import os
import sys

pid = sys.argv[1]
users_db = os.path.realpath(sys.argv[2])
fd_dir = f"/proc/{pid}/fd"

for fd_name in os.listdir(fd_dir):
    fd_path = os.path.join(fd_dir, fd_name)
    try:
        target = os.path.realpath(os.readlink(fd_path))
    except OSError:
        continue
    if target == users_db:
        print(f"opened users.db fd={fd_path} target={target}")
        raise SystemExit(1)
raise SystemExit(0)
PY
  then
    log_check_result "PASS" "${name}" "CHECK" "/proc/${ENGINE_PID}/fd" "OK" "engine/server/db/users.db is not opened by Engine"
    return
  fi

  log_check_result "FAIL" "${name}" "CHECK" "/proc/${ENGINE_PID}/fd" "ERROR" "engine/server/db/users.db is not opened by Engine"
  record_error "${name}: $(sed -n '1,60p' "${TMP_DIR}/${name}.log" | tr '\n' ' ' | sed 's/[[:space:]]\\+/ /g')"
}

ENGINE_HOST="$(url_part "${ENGINE_URL}" host)"
ENGINE_PORT="$(url_part "${ENGINE_URL}" port)"
CLIENT_HOST="$(url_part "${CLIENT_URL}" host)"
CLIENT_PORT="$(url_part "${CLIENT_URL}" port)"

require_cmd curl
require_cmd python3
RUNTIME_PY="$(resolve_runtime_python)"
[[ -n "${RUNTIME_PY}" ]] || {
  echo "[arch-split-smoke] ERROR: Could not resolve runtime python (venv/bin/python3, venv/bin/python, or python3)" >&2
  exit 1
}

log "Engine URL: ${ENGINE_URL} (host=${ENGINE_HOST} port=${ENGINE_PORT})"
log "Client URL: ${CLIENT_URL} (host=${CLIENT_HOST} port=${CLIENT_PORT})"

if [[ -z "${ENGINE_HOST}" || -z "${ENGINE_PORT}" ]]; then
  record_error "Invalid ENGINE_URL: ${ENGINE_URL}"
fi
if [[ -z "${CLIENT_HOST}" || -z "${CLIENT_PORT}" ]]; then
  record_error "Invalid CLIENT_URL: ${CLIENT_URL}"
fi

if (( ERROR_COUNT == 0 )); then
  if ! is_port_free "${ENGINE_PORT}"; then
    record_error "Engine port is already in use: ${ENGINE_HOST}:${ENGINE_PORT}"
  fi
  if ! is_port_free "${CLIENT_PORT}"; then
    record_error "Client port is already in use: ${CLIENT_HOST}:${CLIENT_PORT}"
  fi
fi

if (( ERROR_COUNT == 0 )); then
  run_boundary_contract_check
  run_frontend_gateway_contract_check
fi

if (( ERROR_COUNT == 0 )); then
  log "Starting Engine process"
  ENGINE_INGEST_MODE=bridge "${RUNTIME_PY}" "${ROOT_DIR}/engine/server/api/server.py" \
    --host "${ENGINE_HOST}" --port "${ENGINE_PORT}" >"${ENGINE_LOG}" 2>&1 &
  ENGINE_PID="$!"

  CHECK_COUNT=$((CHECK_COUNT + 1))
  if ! wait_for_health_200 "engine_start_health" "${ENGINE_URL}/api/health" "${STARTUP_TIMEOUT_SECONDS}"; then
    log_check_result "FAIL" "engine_start_health" "GET" "${ENGINE_URL}/api/health" "TIMEOUT" "=200"
    record_error "Engine failed to become healthy within ${STARTUP_TIMEOUT_SECONDS}s"
  else
    log_check_result "PASS" "engine_start_health" "GET" "${ENGINE_URL}/api/health" "200" "=200"
    run_engine_users_db_fd_check
  fi
fi

if (( ERROR_COUNT == 0 )); then
  log "Starting Client process"
  CLIENT_PUBLISH_MODE=bridge "${RUNTIME_PY}" "${ROOT_DIR}/client/backend/server.py" \
    --host "${CLIENT_HOST}" --port "${CLIENT_PORT}" \
    --engine-url "${ENGINE_URL}" >"${CLIENT_LOG}" 2>&1 &
  CLIENT_PID="$!"

  CHECK_COUNT=$((CHECK_COUNT + 1))
  if ! wait_for_health_200 "client_start_health" "${CLIENT_URL}/api/health" "${STARTUP_TIMEOUT_SECONDS}"; then
    log_check_result "FAIL" "client_start_health" "GET" "${CLIENT_URL}/api/health" "TIMEOUT" "=200"
    record_error "Client failed to become healthy within ${STARTUP_TIMEOUT_SECONDS}s"
  else
    log_check_result "PASS" "client_start_health" "GET" "${CLIENT_URL}/api/health" "200" "=200"
  fi
fi

log "Running split-boundary checks"
check_status_eq "engine_health" GET "${ENGINE_URL}/api/health" "200"
check_status_eq "client_health" GET "${CLIENT_URL}/api/health" "200"
check_status_non_success "engine_reject_profile" GET "${ENGINE_URL}/api/user-profile"
check_status_non_success "engine_reject_write" POST "${ENGINE_URL}/api/user-action" "{}"
check_status_eq "client_channels_proxy" GET "${CLIENT_URL}/api/channels?limit=1" "200"
check_status_eq "client_recommendations_proxy" POST "${CLIENT_URL}/recommendations" "200" "{}"
client_recommendations_status="${LAST_STATUS}"
check_status_eq "client_similar_proxy" POST "${CLIENT_URL}/videos/similar" "200" "{}"

check_status_eq "engine_recommendations" POST "${ENGINE_URL}/recommendations" "200" "{}"
if [[ "${client_recommendations_status}" == "200" ]]; then
  CHECK_COUNT=$((CHECK_COUNT + 1))
  seed_output="$(extract_seed_uuid_host "${TMP_DIR}/client_recommendations_proxy.json" 2>&1)"
  if [[ $? -ne 0 ]]; then
    log_check_result "FAIL" "client_recommendations_seed_extract" "PARSE" "${TMP_DIR}/client_recommendations_proxy.json" "ERROR" "uuid+host"
    record_error "client_recommendations_proxy: ${seed_output}"
  else
    seed_uuid="$(printf '%s\n' "${seed_output}" | sed -n '1p')"
    seed_host="$(printf '%s\n' "${seed_output}" | sed -n '2p')"
    if [[ -z "${seed_uuid}" || -z "${seed_host}" ]]; then
      log_check_result "FAIL" "client_recommendations_seed_extract" "PARSE" "${TMP_DIR}/client_recommendations_proxy.json" "EMPTY" "uuid+host"
      record_error "client_recommendations_proxy: empty uuid/host"
    else
      log_check_result "PASS" "client_recommendations_seed_extract" "PARSE" "${TMP_DIR}/client_recommendations_proxy.json" "OK" "uuid+host"
      log "Selected seed: uuid=${seed_uuid} host=${seed_host}"
      check_status_eq "client_video_proxy" GET "${CLIENT_URL}/api/video?id=${seed_uuid}&host=${seed_host}" "200"

      like_payload="$(printf '{"uuid":"%s","host":"%s","action":"like"}' "${seed_uuid}" "${seed_host}")"
      check_status_eq "client_user_action" POST "${CLIENT_URL}/api/user-action" "200" "${like_payload}"
      if [[ "${LAST_NAME}" == "client_user_action" && "${LAST_STATUS}" == "200" ]]; then
        CHECK_COUNT=$((CHECK_COUNT + 1))
        validate_user_action_response "${TMP_DIR}/client_user_action.json" 2>"${TMP_DIR}/client_user_action.validate.err"
        if [[ $? -ne 0 ]]; then
          log_check_result "FAIL" "client_user_action_validate" "VALIDATE" "${TMP_DIR}/client_user_action.json" "ERROR" "ok+bridge_ok+bridge_error"
          record_error "client_user_action: $(cat "${TMP_DIR}/client_user_action.validate.err")"
        else
          log_check_result "PASS" "client_user_action_validate" "VALIDATE" "${TMP_DIR}/client_user_action.json" "OK" "ok+bridge_ok+bridge_error"
        fi
      fi

      check_status_eq "client_profile_likes" GET "${CLIENT_URL}/api/user-profile/likes" "200"
      if [[ "${LAST_NAME}" == "client_profile_likes" && "${LAST_STATUS}" == "200" ]]; then
        CHECK_COUNT=$((CHECK_COUNT + 1))
        validate_profile_likes_response "${TMP_DIR}/client_profile_likes.json" 2>"${TMP_DIR}/client_profile_likes.validate.err"
        if [[ $? -ne 0 ]]; then
          log_check_result "FAIL" "client_profile_likes_validate" "VALIDATE" "${TMP_DIR}/client_profile_likes.json" "ERROR" "likes[] non-empty"
          record_error "client_profile_likes: $(cat "${TMP_DIR}/client_profile_likes.validate.err")"
        else
          log_check_result "PASS" "client_profile_likes_validate" "VALIDATE" "${TMP_DIR}/client_profile_likes.json" "OK" "likes[] non-empty"
        fi
      fi
    fi
  fi
fi

if (( ERROR_COUNT > 0 )); then
  echo "[arch-split-smoke] FAILED: ${ERROR_COUNT} error(s), ${CHECK_COUNT} check(s) executed." >&2
  for idx in "${!ERRORS[@]}"; do
    echo "  $((idx + 1)). ${ERRORS[$idx]}" >&2
  done
  if [[ -f "${LAST_BODY_FILE}" ]]; then
    echo "--- Last response (${LAST_NAME} ${LAST_METHOD} ${LAST_URL} status=${LAST_STATUS}) ---" >&2
    sed -n '1,60p' "${LAST_BODY_FILE}" >&2 || true
  fi
  if [[ -f "${ENGINE_LOG}" ]]; then
    echo "--- Engine log tail ---" >&2
    tail -n 80 "${ENGINE_LOG}" >&2 || true
  fi
  if [[ -f "${CLIENT_LOG}" ]]; then
    echo "--- Client log tail ---" >&2
    tail -n 80 "${CLIENT_LOG}" >&2 || true
  fi
  echo "[arch-split-smoke] Check log: ${CHECK_LOG}" >&2
  echo "[arch-split-smoke] Error log: ${ERROR_LOG}" >&2
  echo "[arch-split-smoke] Run log: ${RUN_LOG}" >&2
  exit 1
fi

echo "NO_ERRORS" >> "${ERROR_LOG}"
log "PASS: all ${CHECK_COUNT} checks succeeded."
log "Check log: ${CHECK_LOG}"
log "Error log: ${ERROR_LOG}"
log "Run log: ${RUN_LOG}"
exit 0
