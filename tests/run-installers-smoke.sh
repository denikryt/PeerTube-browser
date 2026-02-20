#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

MODE="dev" # dev | prod | all
ALLOW_PROD=0
DRY_RUN_ONLY=0
CHECK_PUBLISH=1
CURL_MAX_TIME="${CURL_MAX_TIME:-8}"
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-90}"
ENGINE_DB_PATH="${ENGINE_DB_PATH:-${ROOT_DIR}/engine/server/db/whitelist.db}"

LOG_ROOT_DIR="${ROOT_DIR}/tmp/installers-smoke-logs"
RUN_LOG="${LOG_ROOT_DIR}/run-installers-smoke.run.log"
CHECK_LOG="${LOG_ROOT_DIR}/run-installers-smoke.checks.log"
ERROR_LOG="${LOG_ROOT_DIR}/run-installers-smoke.errors.log"
TMP_DIR="$(mktemp -d /tmp/installers-smoke.XXXXXX)"

CHECK_COUNT=0
ERROR_COUNT=0
CLEANUP_DONE=0
LAST_NAME=""
LAST_DETAILS=""
REQUEST_STATUS=""
LAST_BODY_FILE=""
LIVE_STAGE_CONTOUR=""
LIVE_STAGE_KIND=""

declare -a ERRORS=()

PROD_ENGINE_SERVICE="peertube-engine"
PROD_CLIENT_SERVICE="peertube-client"
PROD_UPDATER_SERVICE="peertube-updater"
PROD_UPDATER_TIMER="peertube-updater"
PROD_ENGINE_PORT=7070
PROD_CLIENT_PORT=7072
PROD_STATE_DIR="/var/lib/peertube-browser"

DEV_ENGINE_SERVICE="peertube-engine-dev"
DEV_CLIENT_SERVICE="peertube-client-dev"
DEV_UPDATER_SERVICE="peertube-updater-dev"
DEV_UPDATER_TIMER="peertube-updater-dev"
DEV_ENGINE_PORT=7171
DEV_CLIENT_PORT=7172
DEV_STATE_DIR="/var/lib/peertube-browser-dev"

mkdir -p "${LOG_ROOT_DIR}"
: > "${RUN_LOG}"
: > "${CHECK_LOG}"
: > "${ERROR_LOG}"

print_help() {
  cat <<'EOF'
Usage: tests/run-installers-smoke.sh [options]

Smoke test A: full installer/uninstaller contract matrix and runtime checks.

What it does:
1) checks --help and --dry-run contracts for all installer/uninstaller entrypoints,
2) (live mode) runs install/verify/uninstall/verify for selected contour(s),
3) validates idempotency, contour isolation, HTTP readiness, and Client->Engine bridge path,
4) always performs teardown for touched contour(s).

Options:
  --mode <dev|prod|all>     Contours to test live (default: dev)
  --allow-prod              Allow live modifications of prod contour (required for prod/all)
  --dry-run-only            Run only contract checks (--help/--dry-run), skip live systemd stage
  --skip-publish-check      Skip Client->Engine publish/e2e check
  --engine-db-path <path>   Engine SQLite DB path for ingest verification
  --startup-timeout <sec>   Wait timeout for service readiness checks (default: 90)
  --max-time <seconds>      curl timeout per request (default: 8)
  -h, --help                Show this help

Examples:
  bash tests/run-installers-smoke.sh --dry-run-only
  sudo bash tests/run-installers-smoke.sh --mode dev
  sudo bash tests/run-installers-smoke.sh --mode all --allow-prod
EOF
}

log() {
  local message="[installers-smoke] $*"
  echo "${message}"
  printf '%s\n' "${message}" >> "${RUN_LOG}"
}

record_error() {
  local message="$1"
  ERROR_COUNT=$((ERROR_COUNT + 1))
  ERRORS+=("${message}")
  printf '%s\n' "${message}" >> "${ERROR_LOG}"
  printf '[installers-smoke] ERROR: %s\n' "${message}" >> "${RUN_LOG}"
}

log_check() {
  local result="$1"
  local name="$2"
  local details="$3"
  local line="${result} check=${name} details=${details}"
  printf '%s\n' "${line}" >> "${CHECK_LOG}"
  printf '[installers-smoke] %s\n' "${line}" >> "${RUN_LOG}"
}

check_cmd_success() {
  local name="$1"
  shift
  CHECK_COUNT=$((CHECK_COUNT + 1))
  local output_file="${TMP_DIR}/${name}.log"
  if "$@" >"${output_file}" 2>&1; then
    log_check "PASS" "${name}" "exit=0"
    return 0
  fi
  log_check "FAIL" "${name}" "exit!=0"
  record_error "${name}: command failed. Output: $(sed -n '1,80p' "${output_file}" | tr '\n' ' ' | sed 's/[[:space:]]\\+/ /g')"
  return 1
}

check_output_contains() {
  local name="$1"
  local file_path="$2"
  local needle="$3"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  if grep -Fq -- "${needle}" "${file_path}"; then
    log_check "PASS" "${name}" "contains='${needle}'"
    return 0
  fi
  log_check "FAIL" "${name}" "missing='${needle}'"
  record_error "${name}: expected '${needle}' in ${file_path}"
  return 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "[installers-smoke] ERROR: missing command: $1" >&2
    exit 1
  }
}

mode_is_selected() {
  local contour="$1"
  if [[ "${MODE}" == "all" ]]; then
    return 0
  fi
  [[ "${MODE}" == "${contour}" ]]
}

contour_engine_service() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${PROD_ENGINE_SERVICE}"
  else
    printf '%s' "${DEV_ENGINE_SERVICE}"
  fi
}

contour_client_service() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${PROD_CLIENT_SERVICE}"
  else
    printf '%s' "${DEV_CLIENT_SERVICE}"
  fi
}

contour_updater_service() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${PROD_UPDATER_SERVICE}"
  else
    printf '%s' "${DEV_UPDATER_SERVICE}"
  fi
}

contour_updater_timer() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${PROD_UPDATER_TIMER}"
  else
    printf '%s' "${DEV_UPDATER_TIMER}"
  fi
}

contour_engine_port() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${PROD_ENGINE_PORT}"
  else
    printf '%s' "${DEV_ENGINE_PORT}"
  fi
}

contour_client_port() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${PROD_CLIENT_PORT}"
  else
    printf '%s' "${DEV_CLIENT_PORT}"
  fi
}

contour_state_dir() {
  local contour="$1"
  if [[ "${contour}" == "prod" ]]; then
    printf '%s' "${PROD_STATE_DIR}"
  else
    printf '%s' "${DEV_STATE_DIR}"
  fi
}

unit_active_state() {
  local unit="$1"
  systemctl is-active "${unit}" 2>/dev/null || true
}

unit_enabled_state() {
  local unit="$1"
  systemctl is-enabled "${unit}" 2>/dev/null || true
}

file_flag() {
  local path="$1"
  if [[ -f "${path}" ]]; then
    printf '1'
  else
    printf '0'
  fi
}

capture_contour_signature() {
  local contour="$1"
  local engine_service
  local client_service
  local updater_service
  local updater_timer
  local state_dir
  engine_service="$(contour_engine_service "${contour}")"
  client_service="$(contour_client_service "${contour}")"
  updater_service="$(contour_updater_service "${contour}")"
  updater_timer="$(contour_updater_timer "${contour}")"
  state_dir="$(contour_state_dir "${contour}")"

  local week_state_file="${state_dir}/updater-last-success-week.txt"
  local sudoers_file="/etc/sudoers.d/${updater_service}-systemctl"

  printf 'engine_active=%s|engine_enabled=%s|client_active=%s|client_enabled=%s|updater_active=%s|updater_enabled=%s|timer_active=%s|timer_enabled=%s|engine_unit_file=%s|client_unit_file=%s|updater_unit_file=%s|timer_unit_file=%s|sudoers=%s|week_state=%s' \
    "$(unit_active_state "${engine_service}.service")" \
    "$(unit_enabled_state "${engine_service}.service")" \
    "$(unit_active_state "${client_service}.service")" \
    "$(unit_enabled_state "${client_service}.service")" \
    "$(unit_active_state "${updater_service}.service")" \
    "$(unit_enabled_state "${updater_service}.service")" \
    "$(unit_active_state "${updater_timer}.timer")" \
    "$(unit_enabled_state "${updater_timer}.timer")" \
    "$(file_flag "/etc/systemd/system/${engine_service}.service")" \
    "$(file_flag "/etc/systemd/system/${client_service}.service")" \
    "$(file_flag "/etc/systemd/system/${updater_service}.service")" \
    "$(file_flag "/etc/systemd/system/${updater_timer}.timer")" \
    "$(file_flag "${sudoers_file}")" \
    "$(file_flag "${week_state_file}")"
}

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
  LAST_DETAILS="${method} ${url}"
  LAST_BODY_FILE="${body_file}"

  if (( curl_exit != 0 )); then
    REQUEST_STATUS="CURL_ERROR:${curl_exit}"
    return 0
  fi
  REQUEST_STATUS="${status}"
}

wait_for_health_200() {
  local name="$1"
  local url="$2"
  local timeout="$3"
  local status=""
  local i=0
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

check_http_status() {
  local name="$1"
  local method="$2"
  local url="$3"
  local expected="$4"
  local body="${5-}"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  request_json "${name}" "${method}" "${url}" "${body}"
  if [[ "${REQUEST_STATUS}" != "${expected}" ]]; then
    log_check "FAIL" "${name}" "status=${REQUEST_STATUS} expected=${expected}"
    record_error "${name}: expected HTTP ${expected}, got ${REQUEST_STATUS}"
    return 1
  fi
  log_check "PASS" "${name}" "status=${REQUEST_STATUS}"
  return 0
}

check_http_unreachable() {
  local name="$1"
  local url="$2"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  local status
  status="$(curl -sS --max-time 2 -o /dev/null -w "%{http_code}" "${url}" 2>/dev/null || true)"
  if [[ "${status}" == "000" || "${status}" == "" ]]; then
    log_check "PASS" "${name}" "unreachable"
    return 0
  fi
  log_check "FAIL" "${name}" "status=${status}"
  record_error "${name}: expected endpoint down, got status ${status}"
  return 1
}

check_json_field_equals() {
  local name="$1"
  local file_path="$2"
  local field="$3"
  local expected="$4"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  if python3 - "${file_path}" "${field}" "${expected}" >"${TMP_DIR}/${name}.validate.log" 2>&1 <<'PY'
import json
import sys

path, field, expected = sys.argv[1:4]
with open(path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)
actual = payload.get(field)
if str(actual) != expected:
    raise SystemExit(f"{field} mismatch: expected={expected!r}, actual={actual!r}")
PY
  then
    log_check "PASS" "${name}" "field=${field} value=${expected}"
    return 0
  fi
  log_check "FAIL" "${name}" "field=${field} value!=${expected}"
  record_error "${name}: $(sed -n '1,40p' "${TMP_DIR}/${name}.validate.log" | tr '\n' ' ' | sed 's/[[:space:]]\\+/ /g')"
  return 1
}

extract_seed_uuid_host() {
  local file_path="$1"
  python3 - "${file_path}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)

rows = payload.get("rows") if isinstance(payload, dict) else None
if not isinstance(rows, list) or not rows:
    raise SystemExit("rows is empty")
for row in rows:
    if not isinstance(row, dict):
        continue
    uuid = row.get("video_uuid") or row.get("videoUuid") or row.get("uuid")
    host = row.get("instance_domain") or row.get("instanceDomain") or row.get("host")
    if uuid and host:
        print(uuid)
        print(host)
        raise SystemExit(0)
raise SystemExit("no row with uuid+host")
PY
}

validate_user_action_ok() {
  local file_path="$1"
  python3 - "${file_path}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)
if not isinstance(payload, dict):
    raise SystemExit("payload is not object")
if payload.get("ok") is not True:
    raise SystemExit("ok is not true")
if payload.get("bridge_ok") is not True:
    raise SystemExit("bridge_ok is not true")
if payload.get("bridge_error") not in (None, ""):
    raise SystemExit(f"bridge_error is not empty: {payload.get('bridge_error')}")
PY
}

validate_likes_non_empty() {
  local file_path="$1"
  python3 - "${file_path}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)
likes = payload.get("likes")
if not isinstance(likes, list):
    raise SystemExit("likes is not a list")
if not likes:
    raise SystemExit("likes is empty")
PY
}

reset_client_test_profile() {
  local name="$1"
  local client_url="$2"
  local user_id="$3"
  local payload
  payload="$(printf '{"user_id":"%s"}' "${user_id}")"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  request_json "${name}" POST "${client_url}/api/user-profile/reset" "${payload}"
  if [[ "${REQUEST_STATUS}" == "200" ]]; then
    log_check "PASS" "${name}" "status=200"
    return 0
  fi
  log_check "FAIL" "${name}" "status=${REQUEST_STATUS}"
  record_error "${name}: failed to reset client test profile for user_id=${user_id} (status=${REQUEST_STATUS})"
  return 1
}

verify_engine_event_recorded() {
  local name="$1"
  local db_path="$2"
  local user_id="$3"
  local video_uuid="$4"
  local host="$5"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  if python3 - "${db_path}" "${user_id}" "${video_uuid}" "${host}" >"${TMP_DIR}/${name}.db.log" 2>&1 <<'PY'
import sqlite3
import sys

db_path, user_id, video_uuid, host = sys.argv[1:5]
conn = sqlite3.connect(db_path)
try:
    cur = conn.execute(
        """
        SELECT COUNT(*)
        FROM interaction_raw_events
        WHERE actor_id = ? AND video_uuid = ? AND instance_domain = ?
        """,
        (user_id, video_uuid, host),
    )
    count = int(cur.fetchone()[0])
finally:
    conn.close()

if count < 1:
    raise SystemExit("event not found in interaction_raw_events")
print(count)
PY
  then
    log_check "PASS" "${name}" "engine_db_event_present"
    return 0
  fi
  log_check "FAIL" "${name}" "engine_db_event_missing"
  record_error "${name}: $(sed -n '1,40p' "${TMP_DIR}/${name}.db.log" | tr '\n' ' ' | sed 's/[[:space:]]\\+/ /g')"
  return 1
}

cleanup_engine_test_events() {
  local name="$1"
  local db_path="$2"
  local user_id="$3"
  local video_uuid="$4"
  local host="$5"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  if python3 - "${db_path}" "${user_id}" "${video_uuid}" "${host}" >"${TMP_DIR}/${name}.cleanup.log" 2>&1 <<'PY'
import sqlite3
import sys
import time

db_path, user_id, video_uuid, host = sys.argv[1:5]
conn = sqlite3.connect(db_path)
try:
    cur = conn.execute(
        """
        DELETE FROM interaction_raw_events
        WHERE actor_id = ? AND video_uuid = ? AND instance_domain = ?
        """,
        (user_id, video_uuid, host),
    )
    deleted = int(cur.rowcount or 0)

    agg_cur = conn.execute(
        """
        SELECT
          SUM(CASE WHEN event_type = 'Like' THEN 1 ELSE 0 END) AS likes_count,
          SUM(CASE WHEN event_type = 'UndoLike' THEN 1 ELSE 0 END) AS undo_likes_count,
          SUM(CASE WHEN event_type = 'Comment' THEN 1 ELSE 0 END) AS comments_count
        FROM interaction_raw_events
        WHERE video_uuid = ? AND instance_domain = ?
        """,
        (video_uuid, host),
    )
    likes_count, undo_likes_count, comments_count = agg_cur.fetchone()
    likes_count = int(likes_count or 0)
    undo_likes_count = int(undo_likes_count or 0)
    comments_count = int(comments_count or 0)
    signal_score = float(likes_count) - float(undo_likes_count) + float(comments_count) * 0.25
    updated_at = int(time.time() * 1000)

    if likes_count == 0 and undo_likes_count == 0 and comments_count == 0:
      conn.execute(
          """
          DELETE FROM interaction_signals
          WHERE video_uuid = ? AND instance_domain = ?
          """,
          (video_uuid, host),
      )
    else:
      conn.execute(
          """
          INSERT INTO interaction_signals (
            video_uuid,
            instance_domain,
            likes_count,
            undo_likes_count,
            comments_count,
            signal_score,
            updated_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(video_uuid, instance_domain) DO UPDATE SET
            likes_count = excluded.likes_count,
            undo_likes_count = excluded.undo_likes_count,
            comments_count = excluded.comments_count,
            signal_score = excluded.signal_score,
            updated_at = excluded.updated_at
          """,
          (video_uuid, host, likes_count, undo_likes_count, comments_count, signal_score, updated_at),
      )

    conn.commit()
finally:
    conn.close()

print(deleted)
PY
  then
    log_check "PASS" "${name}" "engine_db_test_events_cleaned"
    return 0
  fi
  log_check "FAIL" "${name}" "engine_db_cleanup_failed"
  record_error "${name}: $(sed -n '1,40p' "${TMP_DIR}/${name}.cleanup.log" | tr '\n' ' ' | sed 's/[[:space:]]\\+/ /g')"
  return 1
}

run_interaction_check_for_contour() {
  local contour="$1"
  local engine_port
  local client_port
  engine_port="$(contour_engine_port "${contour}")"
  client_port="$(contour_client_port "${contour}")"
  local engine_url="http://127.0.0.1:${engine_port}"
  local client_url="http://127.0.0.1:${client_port}"
  local expected_ingest_base="http://127.0.0.1:${engine_port}"
  local ready_name=""

  CHECK_COUNT=$((CHECK_COUNT + 1))
  ready_name="${contour}_engine_health_wait"
  if wait_for_health_200 "${ready_name}" "${engine_url}/api/health" "${STARTUP_TIMEOUT_SECONDS}"; then
    log_check "PASS" "${ready_name}" "status=200 timeout=${STARTUP_TIMEOUT_SECONDS}s"
  else
    log_check "FAIL" "${ready_name}" "status=${REQUEST_STATUS} timeout=${STARTUP_TIMEOUT_SECONDS}s"
    record_error "${ready_name}: engine did not become healthy in ${STARTUP_TIMEOUT_SECONDS}s (last=${REQUEST_STATUS})"
    dump_diagnostics "${contour}"
    return 0
  fi

  CHECK_COUNT=$((CHECK_COUNT + 1))
  ready_name="${contour}_client_health_wait"
  if wait_for_health_200 "${ready_name}" "${client_url}/api/health" "${STARTUP_TIMEOUT_SECONDS}"; then
    log_check "PASS" "${ready_name}" "status=200 timeout=${STARTUP_TIMEOUT_SECONDS}s"
  else
    log_check "FAIL" "${ready_name}" "status=${REQUEST_STATUS} timeout=${STARTUP_TIMEOUT_SECONDS}s"
    record_error "${ready_name}: client did not become healthy in ${STARTUP_TIMEOUT_SECONDS}s (last=${REQUEST_STATUS})"
    dump_diagnostics "${contour}"
    return 0
  fi

  check_http_status "${contour}_engine_health" GET "${engine_url}/api/health" "200" || true
  check_http_status "${contour}_client_health" GET "${client_url}/api/health" "200" || true
  check_json_field_equals "${contour}_client_health_ingest_base" "${TMP_DIR}/${contour}_client_health.json" "engine_ingest_base" "${expected_ingest_base}" || true
  check_http_status "${contour}_client_channels_proxy" GET "${client_url}/api/channels?limit=1" "200" || true

  if (( CHECK_PUBLISH == 0 )); then
    return 0
  fi

  check_http_status "${contour}_client_recommendations_proxy" POST "${client_url}/recommendations" "200" "{}" || true
  if [[ "${REQUEST_STATUS}" != "200" ]]; then
    return 0
  fi

  CHECK_COUNT=$((CHECK_COUNT + 1))
  local seed_output
  seed_output="$(extract_seed_uuid_host "${TMP_DIR}/${contour}_client_recommendations_proxy.json" 2>&1)"
  if [[ $? -ne 0 ]]; then
    log_check "FAIL" "${contour}_seed_extract" "parse_error"
    record_error "${contour}_seed_extract: ${seed_output}"
    return 0
  fi
  log_check "PASS" "${contour}_seed_extract" "ok"
  local seed_uuid
  local seed_host
  seed_uuid="$(printf '%s\n' "${seed_output}" | sed -n '1p')"
  seed_host="$(printf '%s\n' "${seed_output}" | sed -n '2p')"
  check_http_status "${contour}_client_video_proxy" GET "${client_url}/api/video?id=${seed_uuid}&host=${seed_host}" "200" || true

  local user_id="smoke-${contour}-$(date +%s)-$$"
  local like_payload
  like_payload="$(printf '{"uuid":"%s","host":"%s","action":"like","user_id":"%s"}' "${seed_uuid}" "${seed_host}" "${user_id}")"
  check_http_status "${contour}_user_action" POST "${client_url}/api/user-action" "200" "${like_payload}" || true
  if [[ "${REQUEST_STATUS}" == "200" ]]; then
    CHECK_COUNT=$((CHECK_COUNT + 1))
    if validate_user_action_ok "${TMP_DIR}/${contour}_user_action.json" >"${TMP_DIR}/${contour}_user_action.validate.log" 2>&1; then
      log_check "PASS" "${contour}_user_action_validate" "ok"
    else
      log_check "FAIL" "${contour}_user_action_validate" "invalid_response"
      record_error "${contour}_user_action_validate: $(sed -n '1,40p' "${TMP_DIR}/${contour}_user_action.validate.log" | tr '\n' ' ' | sed 's/[[:space:]]\\+/ /g')"
    fi
  fi

  check_http_status "${contour}_profile_likes" GET "${client_url}/api/user-profile/likes?user_id=${user_id}" "200" || true
  if [[ "${REQUEST_STATUS}" == "200" ]]; then
    CHECK_COUNT=$((CHECK_COUNT + 1))
    if validate_likes_non_empty "${TMP_DIR}/${contour}_profile_likes.json" >"${TMP_DIR}/${contour}_profile_likes.validate.log" 2>&1; then
      log_check "PASS" "${contour}_profile_likes_validate" "non_empty"
    else
      log_check "FAIL" "${contour}_profile_likes_validate" "empty_or_invalid"
      record_error "${contour}_profile_likes_validate: $(sed -n '1,40p' "${TMP_DIR}/${contour}_profile_likes.validate.log" | tr '\n' ' ' | sed 's/[[:space:]]\\+/ /g')"
    fi
  fi

  verify_engine_event_recorded "${contour}_engine_ingest_db" "${ENGINE_DB_PATH}" "${user_id}" "${seed_uuid}" "${seed_host}" || true
  reset_client_test_profile "${contour}_client_profile_reset" "${client_url}" "${user_id}" || true
  cleanup_engine_test_events "${contour}_engine_ingest_db_cleanup" "${ENGINE_DB_PATH}" "${user_id}" "${seed_uuid}" "${seed_host}" || true
}

assert_service_active() {
  local name="$1"
  local unit="$2"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  local state
  state="$(systemctl is-active "${unit}" 2>/dev/null || true)"
  if [[ "${state}" == "active" ]]; then
    log_check "PASS" "${name}" "state=active unit=${unit}"
    return 0
  fi
  log_check "FAIL" "${name}" "state=${state} unit=${unit}"
  record_error "${name}: expected ${unit} active, got ${state}"
  return 1
}

assert_service_not_active() {
  local name="$1"
  local unit="$2"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  local state
  state="$(systemctl is-active "${unit}" 2>/dev/null || true)"
  if [[ "${state}" != "active" ]]; then
    log_check "PASS" "${name}" "state=${state} unit=${unit}"
    return 0
  fi
  log_check "FAIL" "${name}" "state=active unit=${unit}"
  record_error "${name}: expected ${unit} not active after uninstall"
  return 1
}

assert_file_absent() {
  local name="$1"
  local path="$2"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  if [[ ! -e "${path}" ]]; then
    log_check "PASS" "${name}" "absent=${path}"
    return 0
  fi
  log_check "FAIL" "${name}" "present=${path}"
  record_error "${name}: path still exists: ${path}"
  return 1
}

dump_diagnostics() {
  local contour="$1"
  local unit
  for unit in \
    "$(contour_engine_service "${contour}").service" \
    "$(contour_client_service "${contour}").service" \
    "$(contour_updater_service "${contour}").service" \
    "$(contour_updater_timer "${contour}").timer"; do
    {
      echo "--- systemctl status ${unit} ---"
      systemctl status "${unit}" --no-pager 2>&1 || true
      echo "--- journalctl -u ${unit} -n 80 ---"
      journalctl -u "${unit}" -n 80 --no-pager 2>&1 || true
    } >> "${RUN_LOG}"
  done
}

cleanup_contour_fallback() {
  local contour="$1"
  local engine_service
  local client_service
  local updater_service
  local updater_timer
  local state_dir

  engine_service="$(contour_engine_service "${contour}")"
  client_service="$(contour_client_service "${contour}")"
  updater_service="$(contour_updater_service "${contour}")"
  updater_timer="$(contour_updater_timer "${contour}")"
  state_dir="$(contour_state_dir "${contour}")"

  systemctl stop "${client_service}.service" >/dev/null 2>&1 || true
  systemctl stop "${engine_service}.service" >/dev/null 2>&1 || true
  systemctl stop "${updater_timer}.timer" >/dev/null 2>&1 || true
  systemctl stop "${updater_service}.service" >/dev/null 2>&1 || true

  systemctl disable "${client_service}.service" >/dev/null 2>&1 || true
  systemctl disable "${engine_service}.service" >/dev/null 2>&1 || true
  systemctl disable "${updater_timer}.timer" >/dev/null 2>&1 || true

  rm -f "/etc/systemd/system/${client_service}.service"
  rm -f "/etc/systemd/system/${engine_service}.service"
  rm -f "/etc/systemd/system/${updater_service}.service"
  rm -f "/etc/systemd/system/${updater_timer}.timer"
  rm -f "/etc/sudoers.d/${updater_service}-systemctl"
  rm -f "${state_dir}/updater-last-success-week.txt"
  rmdir "${state_dir}" >/dev/null 2>&1 || true
}

cleanup() {
  if (( CLEANUP_DONE == 1 )); then
    return
  fi
  CLEANUP_DONE=1

  if (( DRY_RUN_ONLY == 0 )) && [[ "${EUID}" -eq 0 ]]; then
    log "Cleanup: running final uninstall for selected contour(s)"
    if mode_is_selected "dev"; then
      bash "${ROOT_DIR}/uninstall-service.sh" --mode dev --project-dir "${ROOT_DIR}" --purge-updater-state >/dev/null 2>&1 || true
      cleanup_contour_fallback "dev"
    fi
    if mode_is_selected "prod"; then
      bash "${ROOT_DIR}/uninstall-service.sh" --mode prod --project-dir "${ROOT_DIR}" --purge-updater-state >/dev/null 2>&1 || true
      cleanup_contour_fallback "prod"
    fi
    systemctl daemon-reload >/dev/null 2>&1 || true
  fi

  if (( ERROR_COUNT > 0 )); then
    echo "[installers-smoke] Temp logs: ${TMP_DIR}" >&2
  else
    rm -rf "${TMP_DIR}"
  fi
}

trap cleanup EXIT
trap 'record_error "Interrupted by signal"; exit 130' INT TERM

run_contract_matrix() {
  log "Running --help / --dry-run matrix checks for all entrypoints"

  check_cmd_success "help_install_service" bash "${ROOT_DIR}/install-service.sh" --help || true
  check_output_contains "help_install_service_mode_flag" "${TMP_DIR}/help_install_service.log" "--mode <prod|dev|all>" || true
  check_cmd_success "help_uninstall_service" bash "${ROOT_DIR}/uninstall-service.sh" --help || true
  check_output_contains "help_uninstall_service_purge_flag" "${TMP_DIR}/help_uninstall_service.log" "--purge-updater-state" || true
  check_cmd_success "help_install_prod_wrapper" bash "${ROOT_DIR}/install-service-prod.sh" --help || true
  check_output_contains "help_install_prod_wrapper_flag" "${TMP_DIR}/help_install_prod_wrapper.log" "--with-updater-timer" || true
  check_cmd_success "help_install_dev_wrapper" bash "${ROOT_DIR}/install-service-dev.sh" --help || true
  check_output_contains "help_install_dev_wrapper_flag" "${TMP_DIR}/help_install_dev_wrapper.log" "--without-updater-timer" || true
  check_cmd_success "help_uninstall_prod_wrapper" bash "${ROOT_DIR}/uninstall-service-prod.sh" --help || true
  check_output_contains "help_uninstall_prod_wrapper_flag" "${TMP_DIR}/help_uninstall_prod_wrapper.log" "--purge-updater-state" || true
  check_cmd_success "help_uninstall_dev_wrapper" bash "${ROOT_DIR}/uninstall-service-dev.sh" --help || true
  check_output_contains "help_uninstall_dev_wrapper_flag" "${TMP_DIR}/help_uninstall_dev_wrapper.log" "--purge-updater-state" || true
  check_cmd_success "help_install_engine" bash "${ROOT_DIR}/engine/install-engine-service.sh" --help || true
  check_output_contains "help_install_engine_mode_flag" "${TMP_DIR}/help_install_engine.log" "--mode <prod|dev>" || true
  check_cmd_success "help_install_client" bash "${ROOT_DIR}/client/install-client-service.sh" --help || true
  check_output_contains "help_install_client_engine_url_flag" "${TMP_DIR}/help_install_client.log" "--engine-url" || true
  check_cmd_success "help_uninstall_engine" bash "${ROOT_DIR}/engine/uninstall-engine-service.sh" --help || true
  check_output_contains "help_uninstall_engine_mode_flag" "${TMP_DIR}/help_uninstall_engine.log" "--mode <prod|dev>" || true
  check_cmd_success "help_uninstall_client" bash "${ROOT_DIR}/client/uninstall-client-service.sh" --help || true
  check_output_contains "help_uninstall_client_mode_flag" "${TMP_DIR}/help_uninstall_client.log" "--mode <prod|dev>" || true

  check_cmd_success "dry_install_prod" bash "${ROOT_DIR}/install-service.sh" --mode prod --project-dir "${ROOT_DIR}" --dry-run --with-updater-timer || true
  check_output_contains "dry_install_prod_has_prod_unit" "${TMP_DIR}/dry_install_prod.log" "peertube-engine" || true
  check_output_contains "dry_install_prod_has_prod_client" "${TMP_DIR}/dry_install_prod.log" "peertube-client" || true
  check_output_contains "dry_install_prod_engine_port" "${TMP_DIR}/dry_install_prod.log" "127.0.0.1:7070" || true
  check_output_contains "dry_install_prod_client_port" "${TMP_DIR}/dry_install_prod.log" "127.0.0.1:7072" || true

  check_cmd_success "dry_install_dev" bash "${ROOT_DIR}/install-service.sh" --mode dev --project-dir "${ROOT_DIR}" --dry-run --with-updater-timer || true
  check_output_contains "dry_install_dev_has_dev_unit" "${TMP_DIR}/dry_install_dev.log" "peertube-engine-dev" || true
  check_output_contains "dry_install_dev_has_dev_client" "${TMP_DIR}/dry_install_dev.log" "peertube-client-dev" || true
  check_output_contains "dry_install_dev_engine_port" "${TMP_DIR}/dry_install_dev.log" "127.0.0.1:7171" || true
  check_output_contains "dry_install_dev_client_port" "${TMP_DIR}/dry_install_dev.log" "127.0.0.1:7172" || true

  check_cmd_success "dry_install_all" bash "${ROOT_DIR}/install-service.sh" --mode all --project-dir "${ROOT_DIR}" --dry-run --with-updater-timer || true
  check_output_contains "dry_install_all_prod" "${TMP_DIR}/dry_install_all.log" "contour=prod" || true
  check_output_contains "dry_install_all_dev" "${TMP_DIR}/dry_install_all.log" "contour=dev" || true

  check_cmd_success "dry_uninstall_prod" bash "${ROOT_DIR}/uninstall-service.sh" --mode prod --project-dir "${ROOT_DIR}" --dry-run --purge-updater-state || true
  check_output_contains "dry_uninstall_prod_unit" "${TMP_DIR}/dry_uninstall_prod.log" "peertube-engine" || true

  check_cmd_success "dry_uninstall_dev" bash "${ROOT_DIR}/uninstall-service.sh" --mode dev --project-dir "${ROOT_DIR}" --dry-run --purge-updater-state || true
  check_output_contains "dry_uninstall_dev_unit" "${TMP_DIR}/dry_uninstall_dev.log" "peertube-engine-dev" || true

  check_cmd_success "dry_uninstall_all" bash "${ROOT_DIR}/uninstall-service.sh" --mode all --project-dir "${ROOT_DIR}" --dry-run --purge-updater-state || true
  check_output_contains "dry_uninstall_all_prod" "${TMP_DIR}/dry_uninstall_all.log" "contour=prod" || true
  check_output_contains "dry_uninstall_all_dev" "${TMP_DIR}/dry_uninstall_all.log" "contour=dev" || true

  check_cmd_success "dry_wrapper_install_prod" bash "${ROOT_DIR}/install-service-prod.sh" --project-dir "${ROOT_DIR}" --dry-run || true
  check_output_contains "dry_wrapper_install_prod_contour" "${TMP_DIR}/dry_wrapper_install_prod.log" "contour=prod" || true
  check_cmd_success "dry_wrapper_install_dev" bash "${ROOT_DIR}/install-service-dev.sh" --project-dir "${ROOT_DIR}" --dry-run || true
  check_output_contains "dry_wrapper_install_dev_contour" "${TMP_DIR}/dry_wrapper_install_dev.log" "contour=dev" || true

  check_cmd_success "dry_wrapper_uninstall_prod" bash "${ROOT_DIR}/uninstall-service-prod.sh" --project-dir "${ROOT_DIR}" --dry-run || true
  check_output_contains "dry_wrapper_uninstall_prod_contour" "${TMP_DIR}/dry_wrapper_uninstall_prod.log" "contour=prod" || true
  check_cmd_success "dry_wrapper_uninstall_dev" bash "${ROOT_DIR}/uninstall-service-dev.sh" --project-dir "${ROOT_DIR}" --dry-run || true
  check_output_contains "dry_wrapper_uninstall_dev_contour" "${TMP_DIR}/dry_wrapper_uninstall_dev.log" "contour=dev" || true

  check_cmd_success "dry_install_engine_prod" bash "${ROOT_DIR}/engine/install-engine-service.sh" --mode prod --project-dir "${ROOT_DIR}" --dry-run || true
  check_output_contains "dry_install_engine_prod_unit" "${TMP_DIR}/dry_install_engine_prod.log" "peertube-engine" || true
  check_cmd_success "dry_install_engine_dev" bash "${ROOT_DIR}/engine/install-engine-service.sh" --mode dev --project-dir "${ROOT_DIR}" --dry-run || true
  check_output_contains "dry_install_engine_dev_unit" "${TMP_DIR}/dry_install_engine_dev.log" "peertube-engine-dev" || true

  check_cmd_success "dry_install_client_prod" bash "${ROOT_DIR}/client/install-client-service.sh" --mode prod --project-dir "${ROOT_DIR}" --dry-run || true
  check_output_contains "dry_install_client_prod_unit" "${TMP_DIR}/dry_install_client_prod.log" "peertube-client" || true
  check_cmd_success "dry_install_client_dev" bash "${ROOT_DIR}/client/install-client-service.sh" --mode dev --project-dir "${ROOT_DIR}" --dry-run || true
  check_output_contains "dry_install_client_dev_unit" "${TMP_DIR}/dry_install_client_dev.log" "peertube-client-dev" || true

  check_cmd_success "dry_uninstall_engine_prod" bash "${ROOT_DIR}/engine/uninstall-engine-service.sh" --mode prod --project-dir "${ROOT_DIR}" --dry-run || true
  check_output_contains "dry_uninstall_engine_prod_unit" "${TMP_DIR}/dry_uninstall_engine_prod.log" "peertube-engine" || true
  check_cmd_success "dry_uninstall_engine_dev" bash "${ROOT_DIR}/engine/uninstall-engine-service.sh" --mode dev --project-dir "${ROOT_DIR}" --dry-run || true
  check_output_contains "dry_uninstall_engine_dev_unit" "${TMP_DIR}/dry_uninstall_engine_dev.log" "peertube-engine-dev" || true

  check_cmd_success "dry_uninstall_client_prod" bash "${ROOT_DIR}/client/uninstall-client-service.sh" --mode prod --project-dir "${ROOT_DIR}" --dry-run || true
  check_output_contains "dry_uninstall_client_prod_unit" "${TMP_DIR}/dry_uninstall_client_prod.log" "peertube-client" || true
  check_cmd_success "dry_uninstall_client_dev" bash "${ROOT_DIR}/client/uninstall-client-service.sh" --mode dev --project-dir "${ROOT_DIR}" --dry-run || true
  check_output_contains "dry_uninstall_client_dev_unit" "${TMP_DIR}/dry_uninstall_client_dev.log" "peertube-client-dev" || true
}

run_live_contour_centralized() {
  local contour="$1"
  local opposite
  if [[ "${contour}" == "prod" ]]; then
    opposite="dev"
  else
    opposite="prod"
  fi

  log "Live centralized flow: contour=${contour}"
  local before_opposite
  before_opposite="$(capture_contour_signature "${opposite}")"

  LIVE_STAGE_CONTOUR="${contour}"
  LIVE_STAGE_KIND="centralized"

  check_cmd_success "${contour}_preclean_uninstall" bash "${ROOT_DIR}/uninstall-service.sh" --mode "${contour}" --project-dir "${ROOT_DIR}" --purge-updater-state || true

  check_cmd_success "${contour}_install_first" bash "${ROOT_DIR}/install-service.sh" --mode "${contour}" --project-dir "${ROOT_DIR}" --with-updater-timer --force || true
  check_cmd_success "${contour}_install_second_idempotent" bash "${ROOT_DIR}/install-service.sh" --mode "${contour}" --project-dir "${ROOT_DIR}" --with-updater-timer --no-force || true

  local engine_service
  local client_service
  local updater_service
  local updater_timer
  local engine_port
  local client_port
  local state_dir
  local week_state_file

  engine_service="$(contour_engine_service "${contour}")"
  client_service="$(contour_client_service "${contour}")"
  updater_service="$(contour_updater_service "${contour}")"
  updater_timer="$(contour_updater_timer "${contour}")"
  engine_port="$(contour_engine_port "${contour}")"
  client_port="$(contour_client_port "${contour}")"
  state_dir="$(contour_state_dir "${contour}")"
  week_state_file="${state_dir}/updater-last-success-week.txt"

  assert_service_active "${contour}_engine_active" "${engine_service}.service" || true
  assert_service_active "${contour}_client_active" "${client_service}.service" || true
  assert_service_active "${contour}_timer_active" "${updater_timer}.timer" || true

  run_interaction_check_for_contour "${contour}"

  mkdir -p "${state_dir}"
  echo "smoke-week-state" > "${week_state_file}"
  check_cmd_success "${contour}_uninstall_first" bash "${ROOT_DIR}/uninstall-service.sh" --mode "${contour}" --project-dir "${ROOT_DIR}" --purge-updater-state || true
  assert_service_not_active "${contour}_engine_inactive_after_uninstall" "${engine_service}.service" || true
  assert_service_not_active "${contour}_client_inactive_after_uninstall" "${client_service}.service" || true
  assert_service_not_active "${contour}_timer_inactive_after_uninstall" "${updater_timer}.timer" || true

  assert_file_absent "${contour}_engine_unit_removed" "/etc/systemd/system/${engine_service}.service" || true
  assert_file_absent "${contour}_client_unit_removed" "/etc/systemd/system/${client_service}.service" || true
  assert_file_absent "${contour}_updater_unit_removed" "/etc/systemd/system/${updater_service}.service" || true
  assert_file_absent "${contour}_updater_timer_removed" "/etc/systemd/system/${updater_timer}.timer" || true
  assert_file_absent "${contour}_updater_sudoers_removed" "/etc/sudoers.d/${updater_service}-systemctl" || true
  assert_file_absent "${contour}_updater_week_state_removed" "${week_state_file}" || true

  check_http_unreachable "${contour}_engine_down_after_uninstall" "http://127.0.0.1:${engine_port}/api/health" || true
  check_http_unreachable "${contour}_client_down_after_uninstall" "http://127.0.0.1:${client_port}/api/health" || true

  check_cmd_success "${contour}_uninstall_second_idempotent" bash "${ROOT_DIR}/uninstall-service.sh" --mode "${contour}" --project-dir "${ROOT_DIR}" --purge-updater-state || true

  local after_opposite
  after_opposite="$(capture_contour_signature "${opposite}")"
  CHECK_COUNT=$((CHECK_COUNT + 1))
  if [[ "${before_opposite}" == "${after_opposite}" ]]; then
    log_check "PASS" "${contour}_isolation_opposite_contour_unchanged" "${opposite}"
  else
    log_check "FAIL" "${contour}_isolation_opposite_contour_unchanged" "${opposite}"
    record_error "${contour}: opposite contour (${opposite}) state changed. before='${before_opposite}' after='${after_opposite}'"
  fi

  LIVE_STAGE_KIND=""
  LIVE_STAGE_CONTOUR=""
}

run_live_contour_service_specific_dev() {
  if ! mode_is_selected "dev"; then
    return
  fi

  log "Live service-specific flow: contour=dev"
  LIVE_STAGE_CONTOUR="dev"
  LIVE_STAGE_KIND="service_specific"

  check_cmd_success "dev_specific_preclean_uninstall" bash "${ROOT_DIR}/uninstall-service.sh" --mode dev --project-dir "${ROOT_DIR}" --purge-updater-state || true
  check_cmd_success "dev_specific_install_engine" bash "${ROOT_DIR}/engine/install-engine-service.sh" --mode dev --project-dir "${ROOT_DIR}" --force || true
  check_cmd_success "dev_specific_install_client" bash "${ROOT_DIR}/client/install-client-service.sh" --mode dev --project-dir "${ROOT_DIR}" --force --engine-url "http://127.0.0.1:${DEV_ENGINE_PORT}" || true

  assert_service_active "dev_specific_engine_active" "${DEV_ENGINE_SERVICE}.service" || true
  assert_service_active "dev_specific_client_active" "${DEV_CLIENT_SERVICE}.service" || true
  run_interaction_check_for_contour "dev"

  check_cmd_success "dev_specific_uninstall_client" bash "${ROOT_DIR}/client/uninstall-client-service.sh" --mode dev --project-dir "${ROOT_DIR}" || true
  check_cmd_success "dev_specific_uninstall_engine" bash "${ROOT_DIR}/engine/uninstall-engine-service.sh" --mode dev --project-dir "${ROOT_DIR}" || true
  check_cmd_success "dev_specific_cleanup_updater" bash "${ROOT_DIR}/uninstall-service.sh" --mode dev --project-dir "${ROOT_DIR}" --purge-updater-state || true

  assert_service_not_active "dev_specific_engine_inactive" "${DEV_ENGINE_SERVICE}.service" || true
  assert_service_not_active "dev_specific_client_inactive" "${DEV_CLIENT_SERVICE}.service" || true
  check_http_unreachable "dev_specific_engine_down" "http://127.0.0.1:${DEV_ENGINE_PORT}/api/health" || true
  check_http_unreachable "dev_specific_client_down" "http://127.0.0.1:${DEV_CLIENT_PORT}/api/health" || true

  LIVE_STAGE_KIND=""
  LIVE_STAGE_CONTOUR=""
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --allow-prod)
      ALLOW_PROD=1
      shift
      ;;
    --dry-run-only)
      DRY_RUN_ONLY=1
      shift
      ;;
    --skip-publish-check)
      CHECK_PUBLISH=0
      shift
      ;;
    --engine-db-path)
      ENGINE_DB_PATH="${2:-}"
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

case "${MODE}" in
  dev|prod|all) ;;
  *)
    echo "ERROR: invalid --mode=${MODE} (expected dev|prod|all)" >&2
    exit 1
    ;;
esac

if [[ "${MODE}" != "dev" && "${ALLOW_PROD}" -ne 1 ]]; then
  echo "ERROR: --allow-prod is required for --mode ${MODE}" >&2
  exit 1
fi

require_cmd bash
require_cmd curl
require_cmd python3

if ! [[ "${STARTUP_TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] || (( STARTUP_TIMEOUT_SECONDS < 1 )); then
  echo "ERROR: invalid --startup-timeout=${STARTUP_TIMEOUT_SECONDS} (expected integer >= 1)" >&2
  exit 1
fi

if [[ ! -f "${ROOT_DIR}/install-service.sh" ]]; then
  echo "ERROR: install-service.sh not found in ${ROOT_DIR}" >&2
  exit 1
fi

run_contract_matrix
check_cmd_success "frontend_gateway_boundary_contract" bash "${ROOT_DIR}/tests/check-frontend-client-gateway.sh" || true

if (( DRY_RUN_ONLY == 1 )); then
  log "Dry-run-only mode: skipping live systemd checks."
else
  if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: live mode requires root. Run with sudo or use --dry-run-only." >&2
    exit 1
  fi
  require_cmd systemctl
  require_cmd journalctl
  [[ -f "${ENGINE_DB_PATH}" ]] || record_error "Engine DB not found: ${ENGINE_DB_PATH}"

  if mode_is_selected "dev"; then
    run_live_contour_centralized "dev"
  fi
  if mode_is_selected "prod"; then
    run_live_contour_centralized "prod"
  fi

  run_live_contour_service_specific_dev
fi

if (( ERROR_COUNT > 0 )); then
  if [[ -n "${LIVE_STAGE_CONTOUR}" && "${EUID}" -eq 0 ]]; then
    dump_diagnostics "${LIVE_STAGE_CONTOUR}"
  fi
  echo "[installers-smoke] FAILED: ${ERROR_COUNT} error(s), ${CHECK_COUNT} check(s) executed." >&2
  for idx in "${!ERRORS[@]}"; do
    echo "  $((idx + 1)). ${ERRORS[$idx]}" >&2
  done
  if [[ -f "${LAST_BODY_FILE}" ]]; then
    echo "--- Last response (${LAST_NAME}: ${LAST_DETAILS}) ---" >&2
    sed -n '1,80p' "${LAST_BODY_FILE}" >&2 || true
  fi
  echo "[installers-smoke] Check log: ${CHECK_LOG}" >&2
  echo "[installers-smoke] Error log: ${ERROR_LOG}" >&2
  echo "[installers-smoke] Run log: ${RUN_LOG}" >&2
  exit 1
fi

echo "NO_ERRORS" >> "${ERROR_LOG}"
log "PASS: all ${CHECK_COUNT} checks succeeded."
log "Check log: ${CHECK_LOG}"
log "Error log: ${ERROR_LOG}"
log "Run log: ${RUN_LOG}"
exit 0
