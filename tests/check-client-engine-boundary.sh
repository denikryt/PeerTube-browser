#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_DIR="${ROOT_DIR}/client/backend"

TMP_FILE="$(mktemp /tmp/client-engine-boundary.XXXXXX)"
trap 'rm -f "${TMP_FILE}"' EXIT

violations=0

search_py() {
  local pattern="$1"
  if command -v rg >/dev/null 2>&1; then
    rg -n "${pattern}" "${TARGET_DIR}" --glob '*.py'
    return
  fi
  grep -RInE --include='*.py' "${pattern}" "${TARGET_DIR}"
}

if search_py "(^|[[:space:]])(from|import)[[:space:]]+engine\\.server" >"${TMP_FILE}" 2>/dev/null; then
  echo "[client-engine-boundary] FAIL: direct imports from engine.server are forbidden"
  cat "${TMP_FILE}"
  violations=1
fi

if search_py "engine/server/db/|DEFAULT_ENGINE_DB_PATH|--engine-db" >"${TMP_FILE}" 2>/dev/null; then
  echo "[client-engine-boundary] FAIL: direct Engine DB coupling is forbidden"
  cat "${TMP_FILE}"
  violations=1
fi

if [[ ${violations} -ne 0 ]]; then
  exit 1
fi

echo "[client-engine-boundary] PASS: no direct Client->Engine code/DB coupling found"
