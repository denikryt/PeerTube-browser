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

assert_file_contains() {
  local name="$1"
  local file_path="$2"
  local expected_fragment="$3"
  if grep -Fq -- "${expected_fragment}" "${file_path}"; then
    echo "ok-file-match:${name}"
  else
    echo "fail-file-missing-fragment:${name}"
    echo "expected fragment: ${expected_fragment}"
    cat "${file_path}"
    return 1
  fi
}

assert_file_not_contains() {
  local name="$1"
  local file_path="$2"
  local forbidden_fragment="$3"
  if grep -Fq -- "${forbidden_fragment}" "${file_path}"; then
    echo "fail-file-unexpected-fragment:${name}"
    echo "forbidden fragment: ${forbidden_fragment}"
    cat "${file_path}"
    return 1
  fi
  echo "ok-file-no-fragment:${name}"
}

assert_jq_file_value() {
  local name="$1"
  local file_path="$2"
  local jq_path="$3"
  local expected="$4"
  local actual
  actual="$(jq -r "${jq_path}" "${file_path}")"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "fail-jq-value:${name}"
    echo "path: ${jq_path}"
    echo "expected: ${expected}"
    echo "actual: ${actual}"
    cat "${file_path}"
    return 1
  fi
  echo "ok-jq:${name}:${jq_path}"
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
run_expect_success "help-reject" "${WORKFLOW[@]}" reject --help
run_expect_success "help-validate" "${WORKFLOW[@]}" validate --help

run_expect_failure "invalid-group" "${WORKFLOW[@]}" invalid
run_expect_failure "missing-required-arg" "${WORKFLOW[@]}" feature create --milestone M1
run_expect_failure_contains \
  "materialize-missing-mode" \
  "the following arguments are required: --mode" \
  "${WORKFLOW[@]}" feature materialize --id F1-M1
run_expect_failure "feature-approve-unsupported" "${WORKFLOW[@]}" feature approve --id F1-M1
if rg -n "expected Approved|requires status Approved" "${WORKFLOW_ROOT}/dev/workflow_lib" >"${TMP_DIR}/approved-gate-audit.log"; then
  echo "fail-approved-gate-audit"
  cat "${TMP_DIR}/approved-gate-audit.log"
  exit 1
fi
echo "ok-approved-gate-audit"

# Success-chain smoke (create -> plan-init/lint -> plan tasks -> execution-plan).
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
python3 - "${CHAIN_REPO}/dev/map/DEV_MAP.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
feature = payload["milestones"][0]["features"][0]
feature["issues"] = [
    {
        "id": "I1-F9-M1",
        "title": "Smoke issue",
        "status": "Pending",
        "gh_issue_number": None,
        "gh_issue_url": None,
        "tasks": []
    }
]
path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
run_expect_failure_contains \
  "chain-sync-pending-gate" \
  "status 'Pending'; run plan issue I1-F9-M1 first." \
  "${CHAIN_REPO}/dev/workflow" plan tasks for feature --id F9-M1 --delta-file "${CHAIN_REPO}/dev/sync_delta.json" --write --allocate-task-ids --update-pipeline

cat >"${CHAIN_REPO}/dev/FEATURE_PLANS.md" <<'EOF'
# Feature Plans

## F9-M1
### Dependencies
- smoke

### Decomposition
1. smoke

### Issue Execution Order
1. `I1-F9-M1` - Smoke issue

### I1-F9-M1 - Smoke issue

#### Dependencies
- smoke

#### Decomposition
1. smoke

#### Issue/Task Decomposition Assessment
- smoke

### Issue/Task Decomposition Assessment
- smoke
EOF

cat >"${CHAIN_REPO}/dev/empty_delta.json" <<'EOF'
{}
EOF
run_expect_success \
  "chain-sync-promote-planned" \
  "${CHAIN_REPO}/dev/workflow" plan tasks for feature --id F9-M1 --delta-file "${CHAIN_REPO}/dev/empty_delta.json" --write
assert_json_value "chain-sync-promote-planned" "issue_planning_status_reconciliation.reconciled_issue_ids.0" "I1-F9-M1"
assert_jq_file_value \
  "chain-sync-issue-status-planned" \
  "${CHAIN_REPO}/dev/map/DEV_MAP.json" \
  '.milestones[0].features[0].issues[0].status' \
  "Planned"
run_expect_success "chain-sync" "${CHAIN_REPO}/dev/workflow" plan tasks for feature --id F9-M1 --delta-file "${CHAIN_REPO}/dev/sync_delta.json" --write --allocate-task-ids --update-pipeline
assert_json_value "chain-sync" "action" "planned-tasks"
assert_json_value "chain-sync" "task_count_after" "1"
assert_json_value "chain-sync" "task_list_entries_added" "1"
assert_json_value "chain-sync" "pipeline_execution_rows_added" "1"
assert_json_value "chain-sync" "issue_planning_status_reconciliation.mismatch_count" "0"
assert_jq_file_value \
  "chain-sync-issue-status-tasked" \
  "${CHAIN_REPO}/dev/map/DEV_MAP.json" \
  '.milestones[0].features[0].issues[0].status' \
  "Tasked"
run_expect_success "chain-plan-lint-order-ok" "${CHAIN_REPO}/dev/workflow" feature plan-lint --id F9-M1
assert_json_value "chain-plan-lint-order-ok" "valid" "true"
assert_json_value "chain-plan-lint-order-ok" "messages.3" "Issue Plan Blocks:ok"
assert_json_value "chain-plan-lint-order-ok" "messages.4" "Issue Planning Status:ok"
assert_json_value "chain-plan-lint-order-ok" "messages.5" "Issue Execution Order:ok"
run_expect_success "chain-execution-plan-order-ok" "${CHAIN_REPO}/dev/workflow" feature execution-plan --id F9-M1
assert_json_value "chain-execution-plan-order-ok" "feature_status" "Planned"
assert_json_value "chain-execution-plan-order-ok" "issue_execution_order.0.id" "I1-F9-M1"
assert_json_value "chain-execution-plan-order-ok" "next_issue_from_plan_order.id" "I1-F9-M1"
assert_json_value "chain-execution-plan-order-ok" "tasks.0.issue_id" "I1-F9-M1"

python3 - "${CHAIN_REPO}/dev/map/DEV_MAP.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
payload["milestones"][0]["features"][0]["issues"][0]["status"] = "Planned"
path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
run_expect_failure_contains \
  "chain-plan-lint-status-mismatch" \
  "Issue planning status mismatch: I1-F9-M1(status='Planned', expected='Tasked', has_plan_block=True)." \
  "${CHAIN_REPO}/dev/workflow" feature plan-lint --id F9-M1

cat >"${CHAIN_REPO}/dev/FEATURE_PLANS.md" <<'EOF'
# Feature Plans

## F9-M1
### Dependencies
- smoke

### Decomposition
1. smoke

### Issue Execution Order
1. `I1-F9-M1` - Smoke issue

### Follow-up issue: I1-F9-M1

#### Dependencies
- smoke

#### Decomposition
1. smoke

#### Issue/Task Decomposition Assessment
- smoke

### Issue/Task Decomposition Assessment
- smoke
EOF
run_expect_failure_contains \
  "chain-plan-lint-issue-heading-malformed" \
  "Invalid issue plan heading" \
  "${CHAIN_REPO}/dev/workflow" feature plan-lint --id F9-M1

cat >"${CHAIN_REPO}/dev/FEATURE_PLANS.md" <<'EOF'
# Feature Plans

## F9-M1
### Dependencies
- smoke

### Decomposition
1. smoke

### Issue Execution Order
1. `I1-F9-M1` - Smoke issue

### I1-F9-M1 - Smoke issue

#### Dependencies
- smoke

#### Decomposition
1. smoke

#### Issue/Task Decomposition Assessment
- smoke

### I1-F9-M1 - Smoke issue duplicate

#### Dependencies
- smoke

#### Decomposition
1. smoke

#### Issue/Task Decomposition Assessment
- smoke

### Issue/Task Decomposition Assessment
- smoke
EOF
run_expect_failure_contains \
  "chain-plan-lint-issue-heading-duplicate" \
  "Duplicate issue plan block for issue I1-F9-M1." \
  "${CHAIN_REPO}/dev/workflow" feature plan-lint --id F9-M1

cat >"${CHAIN_REPO}/dev/FEATURE_PLANS.md" <<'EOF'
# Feature Plans

## F9-M1
### Dependencies
- smoke

### Decomposition
1. smoke

### Issue Execution Order
1. `I9-F9-M1` - Unknown issue

### Issue/Task Decomposition Assessment
- smoke
EOF
run_expect_failure_contains \
  "chain-plan-lint-order-unknown-issue" \
  "Issue Execution Order references unknown issue" \
  "${CHAIN_REPO}/dev/workflow" feature plan-lint --id F9-M1

# Multi-issue decomposition: one run for explicit issue queue.
BATCH_ISSUES_REPO="${TMP_DIR}/batch-issues-fixture"
create_workflow_fixture_repo "${BATCH_ISSUES_REPO}"
cat >"${BATCH_ISSUES_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "version": "1.0",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 0,
  "statuses": ["Pending", "Planned", "Tasked", "Done", "Rejected", "Approved"],
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
          "issues": [
            {
              "id": "I1-F1-M1",
              "title": "Issue one",
              "status": "Planned",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": []
            },
            {
              "id": "I2-F1-M1",
              "title": "Issue two",
              "status": "Planned",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": []
            }
          ],
          "branch_name": null,
          "branch_url": null
        },
        {
          "id": "F2-M1",
          "title": "Feature F2-M1",
          "status": "Planned",
          "track": "System/Test",
          "gh_issue_number": null,
          "gh_issue_url": null,
          "issues": [
            {
              "id": "I1-F2-M1",
              "title": "Issue from another feature",
              "status": "Planned",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": []
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
cat >"${BATCH_ISSUES_REPO}/dev/FEATURE_PLANS.md" <<'EOF'
# Feature Plans

## F1-M1
### Dependencies
- smoke

### Decomposition
1. smoke

### Issue Execution Order
1. `I1-F1-M1` - Issue one
2. `I2-F1-M1` - Issue two

### I1-F1-M1 - Issue one

#### Dependencies
- smoke

#### Decomposition
1. smoke

#### Issue/Task Decomposition Assessment
- smoke

### I2-F1-M1 - Issue two

#### Dependencies
- smoke

#### Decomposition
1. smoke

#### Issue/Task Decomposition Assessment
- smoke

### Issue/Task Decomposition Assessment
- smoke
EOF
cat >"${BATCH_ISSUES_REPO}/dev/batch_delta.json" <<'EOF'
{
  "issues": [
    {
      "id": "I2-F1-M1",
      "tasks": [
        {
          "id": "$t1",
          "title": "Issue two task",
          "summary": "Summary two"
        }
      ]
    },
    {
      "id": "I1-F1-M1",
      "tasks": [
        {
          "id": "$t2",
          "title": "Issue one task",
          "summary": "Summary one"
        }
      ]
    }
  ],
  "task_list_entries": [
    {
      "id": "$t1",
      "title": "Issue two task",
      "problem": "Need one-run decomposition for selected issue queue.",
      "solution_option": "Support batch issue-scope decomposition command.",
      "concrete_steps": [
        "Run plan tasks for issues with explicit queue."
      ]
    },
    {
      "id": "$t2",
      "title": "Issue one task",
      "problem": "Need queue-scoped delta filtering.",
      "solution_option": "Filter delta by selected issue IDs only.",
      "concrete_steps": [
        "Validate queue and filter issues payload."
      ]
    }
  ],
  "pipeline": {
    "execution_sequence_append": [
      {
        "tasks": ["$t1", "$t2"],
        "description": "batch issues"
      }
    ],
    "functional_blocks_append": [
      {
        "title": "Batch issues block",
        "tasks": ["$t1", "$t2"],
        "scope": "queue-scoped decomposition run.",
        "outcome": "one run plans selected issue set."
      }
    ],
    "overlaps_append": [
      {
        "tasks": ["$t1", "$t2"],
        "description": "same batch decomposition path."
      }
    ]
  }
}
EOF
run_expect_success \
  "batch-issues-sync" \
  "${BATCH_ISSUES_REPO}/dev/workflow" plan tasks for issues --issue-id I2-F1-M1 --issue-id I1-F1-M1 --delta-file "${BATCH_ISSUES_REPO}/dev/batch_delta.json" --write --allocate-task-ids --update-pipeline
assert_json_value "batch-issues-sync" "command" "plan.tasks.for.issues"
assert_json_value "batch-issues-sync" "issue_id_filter" "null"
assert_json_value "batch-issues-sync" "issue_id_queue.0" "I2-F1-M1"
assert_json_value "batch-issues-sync" "issue_id_queue.1" "I1-F1-M1"
assert_json_value "batch-issues-sync" "dev_map_tasks_upserted" "2"
assert_json_value "batch-issues-sync" "task_count_after" "2"
assert_jq_file_value \
  "batch-issues-status-issue1" \
  "${BATCH_ISSUES_REPO}/dev/map/DEV_MAP.json" \
  '.milestones[0].features[0].issues[] | select(.id=="I1-F1-M1") | .status' \
  "Tasked"
assert_jq_file_value \
  "batch-issues-status-issue2" \
  "${BATCH_ISSUES_REPO}/dev/map/DEV_MAP.json" \
  '.milestones[0].features[0].issues[] | select(.id=="I2-F1-M1") | .status' \
  "Tasked"
run_expect_failure_contains \
  "batch-issues-duplicate-queue" \
  "Duplicate --issue-id value I1-F1-M1" \
  "${BATCH_ISSUES_REPO}/dev/workflow" plan tasks for issues --issue-id I1-F1-M1 --issue-id I1-F1-M1 --delta-file "${BATCH_ISSUES_REPO}/dev/batch_delta.json"
run_expect_failure_contains \
  "batch-issues-non-owned-queue" \
  "requires issue IDs from one feature chain" \
  "${BATCH_ISSUES_REPO}/dev/workflow" plan tasks for issues --issue-id I1-F1-M1 --issue-id I1-F2-M1 --delta-file "${BATCH_ISSUES_REPO}/dev/batch_delta.json"

# No-approve gate: plan tasks --write must not require feature Approved status.
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
cat >"${GATE_SYNC_REPO}/dev/FEATURE_PLANS.md" <<'EOF'
# Feature Plans

## F1-M1
### Dependencies
- smoke

### Decomposition
1. smoke

### Issue/Task Decomposition Assessment
- smoke
EOF
cat >"${GATE_SYNC_REPO}/dev/empty_delta.json" <<'EOF'
{}
EOF
run_expect_success \
  "gate-sync-no-approve-gate" \
  "${GATE_SYNC_REPO}/dev/workflow" plan tasks for feature --id F1-M1 --delta-file "${GATE_SYNC_REPO}/dev/empty_delta.json" --write
assert_json_value "gate-sync-no-approve-gate" "action" "planned-tasks"
assert_file_not_contains \
  "gate-sync-no-approve-error-text" \
  "${TMP_DIR}/gate-sync-no-approve-gate.log" \
  "Approved"
run_expect_success \
  "gate-validate-no-approve-gate" \
  "${GATE_SYNC_REPO}/dev/workflow" validate --scope tracking --feature F1-M1
assert_json_value "gate-validate-no-approve-gate" "valid" "true"
assert_file_not_contains \
  "gate-validate-no-approve-error-text" \
  "${TMP_DIR}/gate-validate-no-approve-gate.log" \
  "Approved"

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
          "status": "Planned",
          "track": "System/Test",
          "gh_issue_number": null,
          "gh_issue_url": null,
          "issues": [
            {
              "id": "I1-F1-M1",
              "title": "Issue I1-F1-M1",
              "status": "Tasked",
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
  "${GATE_MATERIALIZE_REPO}/dev/workflow" feature materialize --id F1-M1 --mode issues-sync
assert_file_not_contains \
  "gate-materialize-no-approve-error-text" \
  "${TMP_DIR}/gate-materialize-missing-milestone.log" \
  "Approved"

# Materialize issues-create: mapped issues must be skipped (no gh issue edit); only unmapped issues are created.
CREATE_ONLY_REPO="${TMP_DIR}/create-only-fixture"
create_workflow_fixture_repo "${CREATE_ONLY_REPO}"
git -C "${CREATE_ONLY_REPO}" init -q
git -C "${CREATE_ONLY_REPO}" checkout -q -b feature/F1-M1
cat >"${CREATE_ONLY_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "version": "1.0",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 2,
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
              "title": "Mapped issue",
              "status": "Tasked",
              "gh_issue_number": 401,
              "gh_issue_url": "https://github.com/owner/repo/issues/401",
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
            },
            {
              "id": "I2-F1-M1",
              "title": "Unmapped issue",
              "status": "Tasked",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": [
                {
                  "id": "2",
                  "title": "Task 2",
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
cp "${CREATE_ONLY_REPO}/dev/map/DEV_MAP.json" "${CREATE_ONLY_REPO}/dev/map/DEV_MAP.initial.json"
FAKE_GH_DIR="${TMP_DIR}/fake-gh-bin"
FAKE_GH_LOG="${TMP_DIR}/fake-gh-calls.log"
mkdir -p "${FAKE_GH_DIR}"
cat >"${FAKE_GH_DIR}/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${FAKE_GH_LOG}"
if [[ "$1" == "repo" && "$2" == "view" ]]; then
  echo '{"nameWithOwner":"owner/repo","url":"https://github.com/owner/repo"}'
  exit 0
fi
if [[ "$1" == "api" ]]; then
  echo '[{"title":"Milestone 1"}]'
  exit 0
fi
if [[ "$1" == "issue" && "$2" == "create" ]]; then
  echo "https://github.com/owner/repo/issues/777"
  exit 0
fi
if [[ "$1" == "issue" && "$2" == "edit" ]]; then
  exit 0
fi
echo "unsupported gh call: $*" >&2
exit 1
EOF
chmod +x "${FAKE_GH_DIR}/gh"
run_expect_success \
  "create-only-no-edit" \
  env PATH="${FAKE_GH_DIR}:${PATH}" FAKE_GH_LOG="${FAKE_GH_LOG}" \
  "${CREATE_ONLY_REPO}/dev/workflow" feature materialize --id F1-M1 --mode issues-create --write --github
assert_json_value "create-only-no-edit" "issues_materialized.0.issue_id" "I1-F1-M1"
assert_json_value "create-only-no-edit" "issues_materialized.0.action" "skipped"
assert_json_value "create-only-no-edit" "issues_materialized.1.issue_id" "I2-F1-M1"
assert_json_value "create-only-no-edit" "issues_materialized.1.action" "created"
assert_file_contains "create-only-gh-create-called" "${FAKE_GH_LOG}" "issue create"
assert_file_not_contains "create-only-gh-edit-not-called" "${FAKE_GH_LOG}" "issue edit"
cp "${CREATE_ONLY_REPO}/dev/map/DEV_MAP.initial.json" "${CREATE_ONLY_REPO}/dev/map/DEV_MAP.json"
run_expect_success \
  "create-only-queue-order" \
  env PATH="${FAKE_GH_DIR}:${PATH}" FAKE_GH_LOG="${FAKE_GH_LOG}" \
  "${CREATE_ONLY_REPO}/dev/workflow" feature materialize --id F1-M1 --mode issues-create --issue-id I2-F1-M1 --issue-id I1-F1-M1 --write --github
assert_json_value "create-only-queue-order" "issue_id_queue.0" "I2-F1-M1"
assert_json_value "create-only-queue-order" "issue_id_queue.1" "I1-F1-M1"
assert_json_value "create-only-queue-order" "selected_issue_ids.0" "I2-F1-M1"
assert_json_value "create-only-queue-order" "selected_issue_ids.1" "I1-F1-M1"
assert_json_value "create-only-queue-order" "issues_materialized.0.issue_id" "I2-F1-M1"
assert_json_value "create-only-queue-order" "issues_materialized.0.action" "created"
assert_json_value "create-only-queue-order" "issues_materialized.1.issue_id" "I1-F1-M1"
assert_json_value "create-only-queue-order" "issues_materialized.1.action" "skipped"
run_expect_failure_contains \
  "create-only-queue-duplicate-rejected" \
  "Duplicate --issue-id value I1-F1-M1" \
  "${CREATE_ONLY_REPO}/dev/workflow" feature materialize --id F1-M1 --mode issues-sync --issue-id I1-F1-M1 --issue-id I1-F1-M1 --no-github

# Materialize sub-issues reconcile: first run adds missing links, second run is idempotent.
SUBISSUE_RECONCILE_REPO="${TMP_DIR}/subissue-reconcile-fixture"
create_workflow_fixture_repo "${SUBISSUE_RECONCILE_REPO}"
git -C "${SUBISSUE_RECONCILE_REPO}" init -q
git -C "${SUBISSUE_RECONCILE_REPO}" checkout -q -b feature/F1-M1
cat >"${SUBISSUE_RECONCILE_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "version": "1.0",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 2,
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
          "gh_issue_number": 500,
          "gh_issue_url": "https://github.com/owner/repo/issues/500",
          "issues": [
            {
              "id": "I1-F1-M1",
              "title": "Mapped issue",
              "status": "Tasked",
              "gh_issue_number": 401,
              "gh_issue_url": "https://github.com/owner/repo/issues/401",
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
            },
            {
              "id": "I2-F1-M1",
              "title": "Unmapped issue",
              "status": "Tasked",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": [
                {
                  "id": "2",
                  "title": "Task 2",
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
SUBISSUE_STATE_FILE="${TMP_DIR}/subissue-state.json"
cat >"${SUBISSUE_STATE_FILE}" <<'EOF'
{"numbers":[401]}
EOF
SUBISSUE_FAKE_GH_DIR="${TMP_DIR}/subissue-fake-gh-bin"
SUBISSUE_FAKE_GH_LOG="${TMP_DIR}/subissue-fake-gh.log"
mkdir -p "${SUBISSUE_FAKE_GH_DIR}"
cat >"${SUBISSUE_FAKE_GH_DIR}/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${SUBISSUE_FAKE_GH_LOG}"
if [[ "$1" == "repo" && "$2" == "view" ]]; then
  echo '{"nameWithOwner":"owner/repo","url":"https://github.com/owner/repo"}'
  exit 0
fi
if [[ "$1" == "api" ]]; then
  route=""
  sub_issue_number=""
  for token in "$@"; do
    if [[ "${token}" == repos/owner/repo/* ]]; then
      route="${token}"
    fi
    if [[ "${token}" == sub_issue_id=* ]]; then
      sub_issue_number="${token#sub_issue_id=}"
    fi
  done
  if [[ "${route}" == repos/owner/repo/milestones* ]]; then
    echo '[{"title":"Milestone 1"}]'
    exit 0
  fi
  if [[ "${route}" == "repos/owner/repo/issues/500/sub_issues?per_page=100" ]]; then
    python3 - "${SUBISSUE_STATE_FILE}" <<'PY'
import json
import pathlib
import sys
state = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(json.dumps([{"number": number} for number in state.get("numbers", [])]))
PY
    exit 0
  fi
  if [[ "${route}" == "repos/owner/repo/issues/500/sub_issues" ]]; then
    python3 - "${SUBISSUE_STATE_FILE}" "${sub_issue_number}" <<'PY'
import json
import pathlib
import sys
state_path = pathlib.Path(sys.argv[1])
number = int(sys.argv[2])
state = json.loads(state_path.read_text(encoding="utf-8"))
numbers = [int(item) for item in state.get("numbers", [])]
if number not in numbers:
    numbers.append(number)
state["numbers"] = numbers
state_path.write_text(json.dumps(state), encoding="utf-8")
print("{}")
PY
    exit 0
  fi
fi
if [[ "$1" == "issue" && "$2" == "create" ]]; then
  echo "https://github.com/owner/repo/issues/402"
  exit 0
fi
if [[ "$1" == "issue" && "$2" == "edit" ]]; then
  exit 0
fi
if [[ "$1" == "issue" && "$2" == "close" ]]; then
  exit 0
fi
echo "unsupported gh call: $*" >&2
exit 1
EOF
chmod +x "${SUBISSUE_FAKE_GH_DIR}/gh"
run_expect_success \
  "subissue-reconcile-first-run" \
  env PATH="${SUBISSUE_FAKE_GH_DIR}:${PATH}" SUBISSUE_FAKE_GH_LOG="${SUBISSUE_FAKE_GH_LOG}" SUBISSUE_STATE_FILE="${SUBISSUE_STATE_FILE}" \
  "${SUBISSUE_RECONCILE_REPO}/dev/workflow" feature materialize --id F1-M1 --mode issues-create --write --github
assert_json_value "subissue-reconcile-first-run" "sub_issues_sync.attempted" "true"
assert_json_value "subissue-reconcile-first-run" "sub_issues_sync.added.0.issue_id" "I2-F1-M1"
assert_json_value "subissue-reconcile-first-run" "missing_issue_mappings" "[]"
run_expect_success \
  "subissue-reconcile-second-run" \
  env PATH="${SUBISSUE_FAKE_GH_DIR}:${PATH}" SUBISSUE_FAKE_GH_LOG="${SUBISSUE_FAKE_GH_LOG}" SUBISSUE_STATE_FILE="${SUBISSUE_STATE_FILE}" \
  "${SUBISSUE_RECONCILE_REPO}/dev/workflow" feature materialize --id F1-M1 --mode issues-create --write --github
assert_json_value "subissue-reconcile-second-run" "sub_issues_sync.attempted" "true"
assert_json_value "subissue-reconcile-second-run" "sub_issues_sync.added" "[]"
assert_json_value "subissue-reconcile-second-run" "missing_issue_mappings" "[]"

# Materialize/confirm: issue bodies are description-driven (no checkbox sync side-effects).
DESCRIPTION_BODY_REPO="${TMP_DIR}/description-body-fixture"
create_workflow_fixture_repo "${DESCRIPTION_BODY_REPO}"
cat >"${DESCRIPTION_BODY_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "version": "1.0",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 2,
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
          "gh_issue_number": 500,
          "gh_issue_url": "https://github.com/owner/repo/issues/500",
          "issues": [
            {
              "id": "I1-F1-M1",
              "title": "First issue",
              "description": "Existing done issue.",
              "status": "Done",
              "gh_issue_number": 401,
              "gh_issue_url": "https://github.com/owner/repo/issues/401",
              "tasks": [
                {
                  "id": "1",
                  "title": "Task 1",
                  "summary": "Summary",
                  "status": "Done",
                  "date": "2026-02-24",
                  "time": "00:00:00"
                }
              ]
            },
            {
              "id": "I2-F1-M1",
              "title": "Second issue",
              "description": "Materialize should rewrite this body using readable description-driven sections.",
              "status": "Tasked",
              "gh_issue_number": 402,
              "gh_issue_url": "https://github.com/owner/repo/issues/402",
              "tasks": [
                {
                  "id": "2",
                  "title": "Task 2",
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
DESCRIPTION_BODY_FILE="${TMP_DIR}/materialized-issue-body.md"
cat >"${DESCRIPTION_BODY_FILE}" <<'EOF'
## Scope
Legacy checkbox body

## Planned work/tasks
- [ ] Legacy checkbox row
EOF
DESCRIPTION_FAKE_GH_DIR="${TMP_DIR}/description-fake-gh-bin"
DESCRIPTION_FAKE_GH_LOG="${TMP_DIR}/description-fake-gh.log"
mkdir -p "${DESCRIPTION_FAKE_GH_DIR}"
cat >"${DESCRIPTION_FAKE_GH_DIR}/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${DESCRIPTION_FAKE_GH_LOG}"
if [[ "$1" == "repo" && "$2" == "view" ]]; then
  echo '{"nameWithOwner":"owner/repo","url":"https://github.com/owner/repo"}'
  exit 0
fi
if [[ "$1" == "api" ]]; then
  echo '[{"title":"Milestone 1"}]'
  exit 0
fi
if [[ "$1" == "issue" && "$2" == "edit" ]]; then
  issue_number="$3"
  shift 3
  body_value=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --body)
        body_value="$2"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done
  if [[ "$issue_number" == "402" ]]; then
    printf "%s" "${body_value}" > "${DESCRIPTION_BODY_FILE}"
  fi
  exit 0
fi
if [[ "$1" == "issue" && "$2" == "close" ]]; then
  exit 0
fi
echo "unsupported gh call: $*" >&2
exit 1
EOF
chmod +x "${DESCRIPTION_FAKE_GH_DIR}/gh"
run_expect_success \
  "description-body-materialize-sync" \
  env PATH="${DESCRIPTION_FAKE_GH_DIR}:${PATH}" DESCRIPTION_FAKE_GH_LOG="${DESCRIPTION_FAKE_GH_LOG}" DESCRIPTION_BODY_FILE="${DESCRIPTION_BODY_FILE}" \
  "${DESCRIPTION_BODY_REPO}/dev/workflow" feature materialize --id F1-M1 --mode issues-sync --issue-id I2-F1-M1 --write --github
assert_json_value "description-body-materialize-sync" "issues_materialized.0.action" "updated"
assert_json_value "description-body-materialize-sync" "feature_issue_checklist_sync.attempted" "false"
assert_file_contains "description-body-materialize-description" "${DESCRIPTION_BODY_FILE}" "Materialize should rewrite this body using readable description-driven sections."
assert_file_not_contains "description-body-materialize-no-scope" "${DESCRIPTION_BODY_FILE}" "## Scope"
assert_file_not_contains "description-body-materialize-no-tasks-section" "${DESCRIPTION_BODY_FILE}" "## Planned work/tasks"
assert_file_not_contains "description-body-materialize-no-checkbox" "${DESCRIPTION_BODY_FILE}" "- [ ]"
run_expect_success \
  "description-body-confirm-issue-done" \
  env PATH="${DESCRIPTION_FAKE_GH_DIR}:${PATH}" DESCRIPTION_FAKE_GH_LOG="${DESCRIPTION_FAKE_GH_LOG}" DESCRIPTION_BODY_FILE="${DESCRIPTION_BODY_FILE}" \
  "${DESCRIPTION_BODY_REPO}/dev/workflow" confirm issue --id I2-F1-M1 done --write --force
assert_json_value "description-body-confirm-issue-done" "feature_issue_checklist_sync.attempted" "false"
assert_json_value "description-body-confirm-issue-done" "feature_issue_checklist_sync.updated" "false"

# Reject flow: mapped close+marker, missing mapping local-only, repeated reject idempotency.
REJECT_FLOW_REPO="${TMP_DIR}/reject-flow-fixture"
create_workflow_fixture_repo "${REJECT_FLOW_REPO}"
cat >"${REJECT_FLOW_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "version": "1.0",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 0,
  "statuses": ["Pending", "Planned", "Tasked", "Done", "Approved", "Rejected"],
  "milestones": [
    {
      "id": "M1",
      "title": "Milestone 1",
      "features": [
        {
          "id": "F1-M1",
          "title": "Feature F1-M1",
          "status": "Approved",
          "gh_issue_number": 500,
          "gh_issue_url": "https://github.com/owner/repo/issues/500",
          "issues": [
            {
              "id": "I1-F1-M1",
              "title": "Mapped reject issue",
              "status": "Tasked",
              "gh_issue_number": 401,
              "gh_issue_url": "https://github.com/owner/repo/issues/401",
              "tasks": []
            },
            {
              "id": "I2-F1-M1",
              "title": "Unmapped reject issue",
              "status": "Tasked",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": []
            }
          ],
          "branch_name": null,
          "branch_url": null
        }
      ],
      "standalone_issues": [],
      "non_feature_items": []
    }
  ]
}
EOF
REJECT_MAPPED_BODY_FILE="${TMP_DIR}/reject-mapped-body.md"
cat >"${REJECT_MAPPED_BODY_FILE}" <<'EOF'
## Scope
Mapped reject issue
EOF
REJECT_FAKE_GH_DIR="${TMP_DIR}/reject-fake-gh-bin"
REJECT_FAKE_GH_LOG="${TMP_DIR}/reject-fake-gh.log"
mkdir -p "${REJECT_FAKE_GH_DIR}"
cat >"${REJECT_FAKE_GH_DIR}/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${REJECT_FAKE_GH_LOG}"
if [[ "$1" == "repo" && "$2" == "view" ]]; then
  echo '{"nameWithOwner":"owner/repo","url":"https://github.com/owner/repo"}'
  exit 0
fi
if [[ "$1" == "issue" && "$2" == "view" ]]; then
  python3 - "${REJECT_MAPPED_BODY_FILE}" <<'PY'
import json
import pathlib
import sys
body_path = pathlib.Path(sys.argv[1])
print(json.dumps({"body": body_path.read_text(encoding="utf-8")}))
PY
  exit 0
fi
if [[ "$1" == "issue" && "$2" == "edit" ]]; then
  issue_number="$3"
  shift 3
  body_value=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --body)
        body_value="$2"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done
  if [[ "$issue_number" == "401" ]]; then
    printf "%s" "${body_value}" > "${REJECT_MAPPED_BODY_FILE}"
  fi
  exit 0
fi
if [[ "$1" == "issue" && "$2" == "close" ]]; then
  exit 0
fi
echo "unsupported gh call: $*" >&2
exit 1
EOF
chmod +x "${REJECT_FAKE_GH_DIR}/gh"
run_expect_success \
  "reject-flow-mapped-write" \
  env PATH="${REJECT_FAKE_GH_DIR}:${PATH}" REJECT_FAKE_GH_LOG="${REJECT_FAKE_GH_LOG}" REJECT_MAPPED_BODY_FILE="${REJECT_MAPPED_BODY_FILE}" \
  "${REJECT_FLOW_REPO}/dev/workflow" reject issue --id I1-F1-M1 --write
assert_json_value "reject-flow-mapped-write" "status_after" "Rejected"
assert_json_value "reject-flow-mapped-write" "github_rejection.attempted" "true"
assert_json_value "reject-flow-mapped-write" "github_rejection.closed" "true"
assert_json_value "reject-flow-mapped-write" "github_rejection.marker_added" "true"
assert_file_contains "reject-flow-mapped-marker" "${REJECT_MAPPED_BODY_FILE}" "<!-- workflow:issue-rejected:I1-F1-M1 -->"
run_expect_success \
  "reject-flow-repeated-write" \
  env PATH="${REJECT_FAKE_GH_DIR}:${PATH}" REJECT_FAKE_GH_LOG="${REJECT_FAKE_GH_LOG}" REJECT_MAPPED_BODY_FILE="${REJECT_MAPPED_BODY_FILE}" \
  "${REJECT_FLOW_REPO}/dev/workflow" reject issue --id I1-F1-M1 --write
assert_json_value "reject-flow-repeated-write" "status_before" "Rejected"
assert_json_value "reject-flow-repeated-write" "github_rejection.reason" "already-rejected-no-op"
run_expect_success \
  "reject-flow-unmapped-write" \
  env PATH="${REJECT_FAKE_GH_DIR}:${PATH}" REJECT_FAKE_GH_LOG="${REJECT_FAKE_GH_LOG}" REJECT_MAPPED_BODY_FILE="${REJECT_MAPPED_BODY_FILE}" \
  "${REJECT_FLOW_REPO}/dev/workflow" reject issue --id I2-F1-M1 --write
assert_json_value "reject-flow-unmapped-write" "status_after" "Rejected"
assert_json_value "reject-flow-unmapped-write" "github_rejection.reason" "issue-not-mapped"

# Confirm issue keeps DEV_MAP issue/task nodes, but removes issue plan artifacts from FEATURE_PLANS.
CONFIRM_PLAN_CLEANUP_REPO="${TMP_DIR}/confirm-plan-cleanup-fixture"
create_workflow_fixture_repo "${CONFIRM_PLAN_CLEANUP_REPO}"
cat >"${CONFIRM_PLAN_CLEANUP_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "version": "1.0",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 1,
  "statuses": ["Pending", "Planned", "InProgress", "Done", "Approved", "Rejected"],
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
              "id": "I3-F1-M1",
              "title": "Plan cleanup issue",
              "status": "Planned",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": [
                {
                  "id": "1",
                  "title": "Plan cleanup task",
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
cat >"${CONFIRM_PLAN_CLEANUP_REPO}/dev/FEATURE_PLANS.md" <<'EOF'
# Feature Plans

## F1-M1
### Dependencies
- smoke

### Decomposition
1. smoke

### Issue Execution Order
1. `I3-F1-M1` - Plan cleanup issue

### I3-F1-M1 - Plan cleanup issue

#### Dependencies
- smoke

#### Decomposition
1. smoke

#### Issue/Task Decomposition Assessment
- smoke

### Issue/Task Decomposition Assessment
- smoke
EOF
cat >"${CONFIRM_PLAN_CLEANUP_REPO}/dev/TASK_LIST.json" <<'EOF'
{
  "schema_version": "1.0",
  "tasks": [
    {
      "id": "1",
      "marker": "[M1][F1]",
      "title": "Plan cleanup task",
      "problem": "Need cleanup check.",
      "solution_option": "Run confirm issue cleanup flow.",
      "concrete_steps": [
        "Run confirm issue and verify artifacts."
      ]
    }
  ]
}
EOF
cat >"${CONFIRM_PLAN_CLEANUP_REPO}/dev/TASK_EXECUTION_PIPELINE.json" <<'EOF'
{
  "schema_version": "1.0",
  "execution_sequence": [
    {
      "tasks": ["1"],
      "description": "cleanup-order"
    }
  ],
  "functional_blocks": [
    {
      "title": "Cleanup block",
      "tasks": ["1"],
      "scope": "Cleanup scope.",
      "outcome": "Cleanup outcome."
    }
  ],
  "overlaps": [
    {
      "tasks": ["1", "1"],
      "description": "cleanup-overlap"
    }
  ]
}
EOF
run_expect_success \
  "confirm-plan-cleanup-run" \
  "${CONFIRM_PLAN_CLEANUP_REPO}/dev/workflow" confirm issue --id I3-F1-M1 done --write --force --no-close-github
assert_json_value "confirm-plan-cleanup-run" "cleanup.feature_plans.issue_order_row_removed" "true"
assert_json_value "confirm-plan-cleanup-run" "cleanup.feature_plans.issue_block_removed" "true"
assert_file_not_contains 'confirm-plan-cleanup-row-removed' "${CONFIRM_PLAN_CLEANUP_REPO}/dev/FEATURE_PLANS.md" '`I3-F1-M1` - Plan cleanup issue'
assert_file_not_contains "confirm-plan-cleanup-block-removed" "${CONFIRM_PLAN_CLEANUP_REPO}/dev/FEATURE_PLANS.md" "### I3-F1-M1 - Plan cleanup issue"
assert_jq_file_value \
  "confirm-plan-cleanup-dev-map-issue-kept" \
  "${CONFIRM_PLAN_CLEANUP_REPO}/dev/map/DEV_MAP.json" \
  '.milestones[0].features[0].issues | length' \
  "1"
assert_jq_file_value \
  "confirm-plan-cleanup-dev-map-issue-done" \
  "${CONFIRM_PLAN_CLEANUP_REPO}/dev/map/DEV_MAP.json" \
  '.milestones[0].features[0].issues[0].status' \
  "Done"
assert_jq_file_value \
  "confirm-plan-cleanup-dev-map-task-done" \
  "${CONFIRM_PLAN_CLEANUP_REPO}/dev/map/DEV_MAP.json" \
  '.milestones[0].features[0].issues[0].tasks[0].status' \
  "Done"

# plan-issue command: create/update/dry-run/failure/idempotency behavior.
PLAN_ISSUE_REPO="${TMP_DIR}/plan-issue-fixture"
create_workflow_fixture_repo "${PLAN_ISSUE_REPO}"
cat >"${PLAN_ISSUE_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "schema_version": "1.4",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 1,
  "statuses": ["Pending", "Planned", "Tasked", "Approved", "Rejected", "Done"],
  "milestones": [
    {
      "id": "M1",
      "title": "Milestone 1",
      "features": [
        {
          "id": "F1-M1",
          "title": "Feature F1-M1",
          "status": "Planned",
          "gh_issue_number": null,
          "gh_issue_url": null,
          "branch_name": null,
          "branch_url": null,
          "issues": [
            {
              "id": "I1-F1-M1",
              "title": "Issue One",
              "status": "Planned",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": [
                {
                  "id": "1",
                  "title": "Task One",
                  "summary": "Summary",
                  "status": "Planned",
                  "date": "2026-02-24",
                  "time": "00:00:00"
                }
              ]
            },
            {
              "id": "I2-F1-M1",
              "title": "Issue Two",
              "status": "Planned",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": []
            }
          ]
        }
      ],
      "standalone_issues": [],
      "non_feature_items": []
    }
  ]
}
EOF
cat >"${PLAN_ISSUE_REPO}/dev/FEATURE_PLANS.md" <<'EOF'
# Feature Plans

## F1-M1
### Dependencies
- smoke

### Decomposition
1. smoke

### Issue Execution Order
1. `I1-F1-M1` - Issue One
2. `I2-F1-M1` - Issue Two

### I1-F1-M1 - Issue One

#### Dependencies
- legacy dependency

#### Decomposition
1. legacy decomposition

#### Issue/Task Decomposition Assessment
- legacy assessment

### Issue/Task Decomposition Assessment
- smoke
EOF
cat >"${PLAN_ISSUE_REPO}/dev/TASK_LIST.json" <<'EOF'
{"schema_version":"1.0","tasks":[]}
EOF
cat >"${PLAN_ISSUE_REPO}/dev/TASK_EXECUTION_PIPELINE.json" <<'EOF'
{"schema_version":"1.0","execution_sequence":[],"functional_blocks":[],"overlaps":[]}
EOF
run_expect_success \
  "plan-issue-dry-run-update" \
  "${PLAN_ISSUE_REPO}/dev/workflow" feature plan-issue --id I1-F1-M1
assert_json_value "plan-issue-dry-run-update" "action" "would-update"
assert_json_value "plan-issue-dry-run-update" "plan_block_updated" "true"
assert_json_value "plan-issue-dry-run-update" "issue_order_checked" "true"
assert_file_contains "plan-issue-dry-run-no-write" "${PLAN_ISSUE_REPO}/dev/FEATURE_PLANS.md" "legacy dependency"
run_expect_success \
  "plan-issue-create-write" \
  "${PLAN_ISSUE_REPO}/dev/workflow" feature plan-issue --id I2-F1-M1 --write
assert_json_value "plan-issue-create-write" "action" "created"
assert_file_contains "plan-issue-create-block" "${PLAN_ISSUE_REPO}/dev/FEATURE_PLANS.md" "### I2-F1-M1 - Issue Two"
run_expect_success \
  "plan-issue-update-write" \
  "${PLAN_ISSUE_REPO}/dev/workflow" feature plan-issue --id I1-F1-M1 --write
assert_json_value "plan-issue-update-write" "action" "updated"
assert_file_not_contains "plan-issue-update-clears-legacy" "${PLAN_ISSUE_REPO}/dev/FEATURE_PLANS.md" "legacy dependency"
run_expect_success \
  "plan-issue-idempotent-write" \
  "${PLAN_ISSUE_REPO}/dev/workflow" feature plan-issue --id I1-F1-M1 --write
assert_json_value "plan-issue-idempotent-write" "action" "unchanged"
assert_json_value "plan-issue-idempotent-write" "plan_block_updated" "false"
run_expect_failure_contains \
  "plan-issue-unknown-issue" \
  "Issue I9-F1-M1 not found in DEV_MAP." \
  "${PLAN_ISSUE_REPO}/dev/workflow" feature plan-issue --id I9-F1-M1
run_expect_failure_contains \
  "plan-issue-malformed-id" \
  "Invalid issue ID" \
  "${PLAN_ISSUE_REPO}/dev/workflow" feature plan-issue --id bad-id
run_expect_failure_contains \
  "plan-issue-feature-mismatch" \
  "plan-issue feature assertion mismatch" \
  "${PLAN_ISSUE_REPO}/dev/workflow" feature plan-issue --id I1-F1-M1 --feature-id F2-M1

PLAN_ISSUE_MISSING_ROW_REPO="${TMP_DIR}/plan-issue-missing-row-fixture"
create_workflow_fixture_repo "${PLAN_ISSUE_MISSING_ROW_REPO}"
cat >"${PLAN_ISSUE_MISSING_ROW_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "schema_version": "1.4",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 0,
  "statuses": ["Pending", "Planned", "Tasked", "Approved", "Rejected", "Done"],
  "milestones": [
    {
      "id": "M1",
      "title": "Milestone 1",
      "features": [
        {
          "id": "F1-M1",
          "title": "Feature F1-M1",
          "status": "Planned",
          "gh_issue_number": null,
          "gh_issue_url": null,
          "branch_name": null,
          "branch_url": null,
          "issues": [
            {
              "id": "I1-F1-M1",
              "title": "Issue One",
              "status": "Planned",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": []
            }
          ]
        }
      ],
      "standalone_issues": [],
      "non_feature_items": []
    }
  ]
}
EOF
cat >"${PLAN_ISSUE_MISSING_ROW_REPO}/dev/FEATURE_PLANS.md" <<'EOF'
# Feature Plans

## F1-M1
### Dependencies
- smoke

### Decomposition
1. smoke

### Issue Execution Order
1. `I9-F1-M1` - Other issue

### Issue/Task Decomposition Assessment
- smoke
EOF
cat >"${PLAN_ISSUE_MISSING_ROW_REPO}/dev/TASK_LIST.json" <<'EOF'
{"schema_version":"1.0","tasks":[]}
EOF
cat >"${PLAN_ISSUE_MISSING_ROW_REPO}/dev/TASK_EXECUTION_PIPELINE.json" <<'EOF'
{"schema_version":"1.0","execution_sequence":[],"functional_blocks":[],"overlaps":[]}
EOF
run_expect_failure_contains \
  "plan-issue-missing-active-row" \
  "plan-issue requires active issue row" \
  "${PLAN_ISSUE_MISSING_ROW_REPO}/dev/workflow" feature plan-issue --id I1-F1-M1 --write

PLAN_ISSUE_INVALID_HEADING_REPO="${TMP_DIR}/plan-issue-invalid-heading-fixture"
create_workflow_fixture_repo "${PLAN_ISSUE_INVALID_HEADING_REPO}"
cat >"${PLAN_ISSUE_INVALID_HEADING_REPO}/dev/map/DEV_MAP.json" <<'EOF'
{
  "schema_version": "1.4",
  "updated_at": "2026-02-24T00:00:00+00:00",
  "task_count": 0,
  "statuses": ["Pending", "Planned", "Tasked", "Approved", "Rejected", "Done"],
  "milestones": [
    {
      "id": "M1",
      "title": "Milestone 1",
      "features": [
        {
          "id": "F1-M1",
          "title": "Feature F1-M1",
          "status": "Planned",
          "gh_issue_number": null,
          "gh_issue_url": null,
          "branch_name": null,
          "branch_url": null,
          "issues": [
            {
              "id": "I1-F1-M1",
              "title": "Issue One",
              "status": "Planned",
              "gh_issue_number": null,
              "gh_issue_url": null,
              "tasks": []
            }
          ]
        }
      ],
      "standalone_issues": [],
      "non_feature_items": []
    }
  ]
}
EOF
cat >"${PLAN_ISSUE_INVALID_HEADING_REPO}/dev/FEATURE_PLANS.md" <<'EOF'
# Feature Plans

## F1-M1
### Dependencies
- smoke

### Decomposition
1. smoke

### Issue Execution Order
1. `I1-F1-M1` - Issue One

### I1-F1-M1 - Issue One

#### Dependencies
- smoke

##### Custom heading
- invalid

#### Decomposition
1. smoke

#### Issue/Task Decomposition Assessment
- smoke

### Issue/Task Decomposition Assessment
- smoke
EOF
cat >"${PLAN_ISSUE_INVALID_HEADING_REPO}/dev/TASK_LIST.json" <<'EOF'
{"schema_version":"1.0","tasks":[]}
EOF
cat >"${PLAN_ISSUE_INVALID_HEADING_REPO}/dev/TASK_EXECUTION_PIPELINE.json" <<'EOF'
{"schema_version":"1.0","execution_sequence":[],"functional_blocks":[],"overlaps":[]}
EOF
run_expect_failure_contains \
  "plan-issue-invalid-custom-heading" \
  "invalid heading hierarchy" \
  "${PLAN_ISSUE_INVALID_HEADING_REPO}/dev/workflow" feature plan-issue --id I1-F1-M1 --write

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
