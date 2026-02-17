#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_DIR="${ROOT_DIR}/client/frontend/src"

TMP_FILE="$(mktemp /tmp/frontend-client-gateway.XXXXXX)"
trap 'rm -f "${TMP_FILE}"' EXIT

violations=0

search_frontend() {
  local pattern="$1"
  if command -v rg >/dev/null 2>&1; then
    rg -n "${pattern}" "${TARGET_DIR}" --glob '*.ts' --glob '*.tsx' --glob '*.js'
    return
  fi
  grep -RInE --include='*.ts' --include='*.tsx' --include='*.js' "${pattern}" "${TARGET_DIR}"
}

if search_frontend "resolveEngineApiBase|VITE_ENGINE_API_BASE" >"${TMP_FILE}" 2>/dev/null; then
  echo "[frontend-client-gateway] FAIL: direct Engine API base usage in frontend src is forbidden"
  cat "${TMP_FILE}"
  violations=1
fi

if search_frontend "https?://127\\.0\\.0\\.1:(7070|7171)|https?://localhost:(7070|7171)" >"${TMP_FILE}" 2>/dev/null; then
  echo "[frontend-client-gateway] FAIL: hardcoded Engine host/port in frontend src is forbidden"
  cat "${TMP_FILE}"
  violations=1
fi

if [[ ${violations} -ne 0 ]]; then
  exit 1
fi

echo "[frontend-client-gateway] PASS: frontend read path is Client-gateway only"
