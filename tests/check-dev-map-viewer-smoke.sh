#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIEWER_JS="${ROOT_DIR}/dev/map/dev-map.js"

require_pattern() {
  local label="$1"
  local pattern="$2"
  if rg -n "${pattern}" "${VIEWER_JS}" >/dev/null; then
    echo "ok:${label}"
  else
    echo "fail:${label}"
    echo "missing pattern: ${pattern}"
    exit 1
  fi
}

forbid_pattern() {
  local label="$1"
  local pattern="$2"
  if rg -n "${pattern}" "${VIEWER_JS}" >/dev/null; then
    echo "fail:${label}"
    echo "forbidden pattern found: ${pattern}"
    exit 1
  fi
  echo "ok:${label}"
}

require_pattern "description-helper" "function appendDescriptionMeta\\(parent, description\\)"
require_pattern "feature-description-hook" "appendDescriptionMeta\\(details, feature\\.description\\);"
require_pattern "issue-description-hook" "appendDescriptionMeta\\(details, issue\\.description\\);"
forbid_pattern "no-description-label-prefix" "Description:"
forbid_pattern "task-timestamp-removed" "Timestamp:"

echo "dev-map-viewer-smoke:pass"
