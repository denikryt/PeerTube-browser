#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_DIR="${ROOT_DIR}/client/backend"

TMP_FILE="$(mktemp /tmp/client-engine-boundary.XXXXXX)"
trap 'rm -f "${TMP_FILE}"' EXIT

violations=0

if rg -n "(^|[[:space:]])(from|import)[[:space:]]+engine\.server" "${TARGET_DIR}" --glob '*.py' >"${TMP_FILE}" 2>/dev/null; then
  echo "[client-engine-boundary] FAIL: direct imports from engine.server are forbidden"
  cat "${TMP_FILE}"
  violations=1
fi

if rg -n "engine/server/db/|DEFAULT_ENGINE_DB_PATH|--engine-db" "${TARGET_DIR}" --glob '*.py' >"${TMP_FILE}" 2>/dev/null; then
  echo "[client-engine-boundary] FAIL: direct Engine DB coupling is forbidden"
  cat "${TMP_FILE}"
  violations=1
fi

if [[ ${violations} -ne 0 ]]; then
  exit 1
fi

echo "[client-engine-boundary] PASS: no direct Client->Engine code/DB coupling found"
