#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

WORKFLOW_ROOT="${ROOT_DIR}"
if [[ ! -x "${ROOT_DIR}/dev/workflow" ]]; then
  # Some filesystems (for example, NTFS/fuseblk mounts) ignore executable bits.
  # Build a temporary POSIX-permission mirror and still verify canonical ./dev/workflow invocation there.
  WORKFLOW_ROOT="${TMP_DIR}/workflow-posix"
  mkdir -p "${WORKFLOW_ROOT}/dev/workflow_lib"
  cp "${ROOT_DIR}/dev/workflow" "${WORKFLOW_ROOT}/dev/workflow"
  cp "${ROOT_DIR}"/dev/workflow_lib/*.py "${WORKFLOW_ROOT}/dev/workflow_lib/"
  chmod +x "${WORKFLOW_ROOT}/dev/workflow"
fi
WORKFLOW=("${WORKFLOW_ROOT}/dev/workflow")

run_expect_success() {
  local name="$1"
  shift
  if "$@" >"${TMP_DIR}/${name}.log" 2>&1; then
    echo "ok:${name}"
  else
    echo "fail:${name}"
    cat "${TMP_DIR}/${name}.log"
    return 1
  fi
}

run_expect_failure() {
  local name="$1"
  shift
  if "$@" >"${TMP_DIR}/${name}.log" 2>&1; then
    echo "unexpected-success:${name}"
    cat "${TMP_DIR}/${name}.log"
    return 1
  fi
  echo "ok-failed:${name}"
}

run_expect_success "help-root" "${WORKFLOW[@]}" --help
run_expect_success "help-feature" "${WORKFLOW[@]}" feature --help
run_expect_success "help-task" "${WORKFLOW[@]}" task --help
run_expect_success "help-confirm" "${WORKFLOW[@]}" confirm --help
run_expect_success "help-validate" "${WORKFLOW[@]}" validate --help

run_expect_failure "invalid-group" "${WORKFLOW[@]}" invalid
run_expect_failure "missing-required-arg" "${WORKFLOW[@]}" feature create --milestone M1

echo "workflow-cli-smoke:pass"
