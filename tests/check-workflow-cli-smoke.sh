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

run_expect_failure_contains() {
  local name="$1"
  local expected_fragment="$2"
  shift 2
  run_expect_failure "${name}" "$@"
  if grep -Fq "${expected_fragment}" "${TMP_DIR}/${name}.log"; then
    echo "ok-failed-match:${name}"
  else
    echo "fail-missing-fragment:${name}"
    echo "expected fragment: ${expected_fragment}"
    cat "${TMP_DIR}/${name}.log"
    return 1
  fi
}

assert_json_value() {
  local name="$1"
  local path="$2"
  local expected="$3"
  python3 - "${TMP_DIR}/${name}.log" "${path}" "${expected}" <<'PY'
import json
import sys

log_path, path, expected = sys.argv[1], sys.argv[2], sys.argv[3]
payload = json.loads(open(log_path, encoding="utf-8").read())
value = payload
for token in path.split("."):
    if token.isdigit():
        value = value[int(token)]
    else:
        value = value[token]
if isinstance(value, bool):
    actual = "true" if value else "false"
elif value is None:
    actual = "null"
else:
    actual = str(value)
if actual != expected:
    print(f"json-assert-failed path={path} expected={expected!r} actual={actual!r}")
    sys.exit(1)
PY
  echo "ok-json:${name}:${path}"
}

create_workflow_fixture_repo() {
  local repo_dir="$1"
  mkdir -p "${repo_dir}/dev/map" "${repo_dir}/dev/workflow_lib"
  cp "${WORKFLOW_ROOT}/dev/workflow" "${repo_dir}/dev/workflow"
  cp "${WORKFLOW_ROOT}"/dev/workflow_lib/*.py "${repo_dir}/dev/workflow_lib/"
  chmod +x "${repo_dir}/dev/workflow"
  cat >"${repo_dir}/dev/TASK_LIST.md" <<'EOF'
# Task List
EOF
  cat >"${repo_dir}/dev/TASK_EXECUTION_PIPELINE.md" <<'EOF'
# Task Execution Pipeline

### Execution sequence

### Functional blocks

### Cross-task overlaps and dependencies
EOF
  cat >"${repo_dir}/dev/FEATURE_PLANS.md" <<'EOF'
# Feature Plans
EOF
}

run_expect_success "help-root" "${WORKFLOW[@]}" --help
run_expect_success "help-feature" "${WORKFLOW[@]}" feature --help
run_expect_success "help-task" "${WORKFLOW[@]}" task --help
run_expect_success "help-confirm" "${WORKFLOW[@]}" confirm --help
run_expect_success "help-validate" "${WORKFLOW[@]}" validate --help

run_expect_failure "invalid-group" "${WORKFLOW[@]}" invalid
run_expect_failure "missing-required-arg" "${WORKFLOW[@]}" feature create --milestone M1

# Success-chain smoke (create -> plan-init/lint -> approve -> sync -> execution-plan).
CHAIN_REPO="${TMP_DIR}/chain-fixture"
create_workflow_fixture_repo "${CHAIN_REPO}"
cat >"${CHAIN_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "version": "1.0",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 0,
  "statuses": ["Planned", "InProgress", "Done", "Approved"],
  "milestones": [
    {
      "id": "M1",
      "title": "Milestone 1",
      "status": "Planned",
      "features": [],
      "standalone_issues": []
    }
  ]
}
EOF
cat >"${CHAIN_REPO}/dev/sync_delta.json" <<'EOF'
{
  "issues": [
    {
      "id": "I1-F9-M1",
      "title": "Smoke issue",
      "tasks": [
        {
          "id": "$t1",
          "title": "Smoke task",
          "summary": "Smoke summary"
        }
      ]
    }
  ],
  "task_list_entries": [
    {
      "id": "$t1",
      "title": "Smoke task",
      "problem": "Need deterministic smoke chain.",
      "solution_option": "Execute full feature command flow end-to-end.",
      "concrete_steps": [
        "Run feature command sequence in fixture repository."
      ]
    }
  ],
  "pipeline": {
    "execution_sequence_append": [
      {
        "tasks": ["$t1"],
        "description": "smoke-chain"
      }
    ],
    "functional_blocks_append": [
      {
        "title": "Smoke block",
        "tasks": ["$t1"],
        "scope": "Single-task smoke flow.",
        "outcome": "Execution-plan returns one pending task."
      }
    ],
    "overlaps_append": []
  }
}
EOF
run_expect_success "chain-create" "${CHAIN_REPO}/dev/workflow" feature create --id F9-M1 --milestone M1 --title "Smoke feature" --write
assert_json_value "chain-create" "action" "created"
assert_json_value "chain-create" "feature_id" "F9-M1"
run_expect_success "chain-plan-init" "${CHAIN_REPO}/dev/workflow" feature plan-init --id F9-M1 --write
assert_json_value "chain-plan-init" "action" "created"
run_expect_success "chain-plan-lint" "${CHAIN_REPO}/dev/workflow" feature plan-lint --id F9-M1
assert_json_value "chain-plan-lint" "valid" "true"
run_expect_success "chain-approve" "${CHAIN_REPO}/dev/workflow" feature approve --id F9-M1 --write
assert_json_value "chain-approve" "action" "approved"
assert_json_value "chain-approve" "status_after" "Approved"
run_expect_success "chain-sync" "${CHAIN_REPO}/dev/workflow" feature sync --id F9-M1 --delta-file "${CHAIN_REPO}/dev/sync_delta.json" --write --allocate-task-ids --update-pipeline
assert_json_value "chain-sync" "action" "synced"
assert_json_value "chain-sync" "task_count_after" "1"
assert_json_value "chain-sync" "task_list_entries_added" "1"
assert_json_value "chain-sync" "pipeline_execution_rows_added" "1"
run_expect_success "chain-execution-plan" "${CHAIN_REPO}/dev/workflow" feature execution-plan --id F9-M1
assert_json_value "chain-execution-plan" "task_count" "1"
assert_json_value "chain-execution-plan" "tasks.0.id" "1"
assert_json_value "chain-execution-plan" "tasks.0.issue_id" "I1-F9-M1"

# Gate-fail: sync --write blocked for non-approved feature status.
GATE_SYNC_REPO="${TMP_DIR}/gate-sync-fixture"
create_workflow_fixture_repo "${GATE_SYNC_REPO}"
cat >"${GATE_SYNC_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "version": "1.0",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 0,
  "statuses": ["Planned", "InProgress", "Done", "Approved"],
  "milestones": [
    {
      "id": "M1",
      "title": "Milestone 1",
      "status": "Planned",
      "features": [
        {
          "id": "F1-M1",
          "title": "Feature F1-M1",
          "status": "Planned",
          "track": "System/Test",
          "gh_issue_number": null,
          "gh_issue_url": null,
          "issues": [],
          "branch_name": null,
          "branch_url": null
        }
      ],
      "standalone_issues": []
    }
  ]
}
EOF
cat >"${GATE_SYNC_REPO}/dev/empty_delta.json" <<'EOF'
{}
EOF
run_expect_failure_contains \
  "gate-sync-non-approved" \
  "requires status Approved" \
  "${GATE_SYNC_REPO}/dev/workflow" feature sync --id F1-M1 --delta-file "${GATE_SYNC_REPO}/dev/empty_delta.json" --write

# Gate-fail: materialize blocked when milestone-to-title mapping is missing.
GATE_MATERIALIZE_REPO="${TMP_DIR}/gate-materialize-fixture"
create_workflow_fixture_repo "${GATE_MATERIALIZE_REPO}"
cat >"${GATE_MATERIALIZE_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "version": "1.0",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 1,
  "statuses": ["Planned", "InProgress", "Done", "Approved"],
  "milestones": [
    {
      "id": "M1",
      "title": "",
      "status": "Planned",
      "features": [
        {
          "id": "F1-M1",
          "title": "Feature F1-M1",
          "status": "Approved",
          "track": "System/Test",
          "gh_issue_number": null,
          "gh_issue_url": null,
          "issues": [
            {
              "id": "I1-F1-M1",
              "title": "Issue I1-F1-M1",
              "status": "Planned",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": [
                {
                  "id": "1",
                  "title": "Task 1",
                  "summary": "Summary",
                  "status": "Planned",
                  "date": "2026-02-24",
                  "time": "00:00:00"
                }
              ]
            }
          ],
          "branch_name": null,
          "branch_url": null
        }
      ],
      "standalone_issues": []
    }
  ]
}
EOF
run_expect_failure_contains \
  "gate-materialize-missing-milestone" \
  "has empty title in DEV_MAP" \
  "${GATE_MATERIALIZE_REPO}/dev/workflow" feature materialize --id F1-M1

# Gate-fail: task preflight blocked for missing materialization metadata.
GATE_PREFLIGHT_REPO="${TMP_DIR}/gate-preflight-fixture"
create_workflow_fixture_repo "${GATE_PREFLIGHT_REPO}"
cat >"${GATE_PREFLIGHT_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "version": "1.0",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 1,
  "statuses": ["Planned", "InProgress", "Done", "Approved"],
  "milestones": [
    {
      "id": "M1",
      "title": "Milestone 1",
      "status": "Planned",
      "features": [
        {
          "id": "F1-M1",
          "title": "Feature F1-M1",
          "status": "Approved",
          "track": "System/Test",
          "gh_issue_number": null,
          "gh_issue_url": null,
          "issues": [
            {
              "id": "I1-F1-M1",
              "title": "Issue I1-F1-M1",
              "status": "Planned",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": [
                {
                  "id": "1",
                  "title": "Task 1",
                  "summary": "Summary",
                  "status": "Planned",
                  "date": "2026-02-24",
                  "time": "00:00:00"
                }
              ]
            }
          ],
          "branch_name": null,
          "branch_url": null
        }
      ],
      "standalone_issues": []
    }
  ]
}
EOF
cat >"${GATE_PREFLIGHT_REPO}/dev/TASK_LIST.md" <<'EOF'
# Task List

### 1) [M1][F1] Smoke task
**Problem:** Smoke problem.

**Solution option:** Smoke solution.

#### **Concrete steps:**
1. Smoke step.
EOF
run_expect_failure_contains \
  "gate-preflight-missing-metadata" \
  "has no materialization metadata" \
  "${GATE_PREFLIGHT_REPO}/dev/workflow" task preflight --id 1

echo "workflow-cli-smoke:pass"
