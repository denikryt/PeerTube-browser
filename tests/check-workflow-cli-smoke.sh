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

# Materialize/confirm: keep feature-level checklist in sync for child issue rows.
CHECKLIST_SYNC_REPO="${TMP_DIR}/checklist-sync-fixture"
create_workflow_fixture_repo "${CHECKLIST_SYNC_REPO}"
cat >"${CHECKLIST_SYNC_REPO}/dev/map/DEV_MAP.json" <<'EOF'
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
CHECKLIST_BODY_FILE="${TMP_DIR}/feature-issue-body.md"
cat >"${CHECKLIST_BODY_FILE}" <<'EOF'
## Scope
Feature F1-M1

## Planned work/issues
- [x] I1-F1-M1: First issue
EOF
CHECKLIST_FAKE_GH_DIR="${TMP_DIR}/checklist-fake-gh-bin"
CHECKLIST_FAKE_GH_LOG="${TMP_DIR}/checklist-fake-gh.log"
mkdir -p "${CHECKLIST_FAKE_GH_DIR}"
cat >"${CHECKLIST_FAKE_GH_DIR}/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${CHECKLIST_FAKE_GH_LOG}"
if [[ "$1" == "repo" && "$2" == "view" ]]; then
  echo '{"nameWithOwner":"owner/repo","url":"https://github.com/owner/repo"}'
  exit 0
fi
if [[ "$1" == "api" ]]; then
  echo '[{"title":"Milestone 1"}]'
  exit 0
fi
if [[ "$1" == "issue" && "$2" == "view" ]]; then
  python3 - "${CHECKLIST_BODY_FILE}" <<'PY'
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
  if [[ "$issue_number" == "500" ]]; then
    printf "%s" "${body_value}" > "${CHECKLIST_BODY_FILE}"
  fi
  exit 0
fi
if [[ "$1" == "issue" && "$2" == "close" ]]; then
  exit 0
fi
echo "unsupported gh call: $*" >&2
exit 1
EOF
chmod +x "${CHECKLIST_FAKE_GH_DIR}/gh"
run_expect_success \
  "checklist-sync-materialize" \
  env PATH="${CHECKLIST_FAKE_GH_DIR}:${PATH}" CHECKLIST_FAKE_GH_LOG="${CHECKLIST_FAKE_GH_LOG}" CHECKLIST_BODY_FILE="${CHECKLIST_BODY_FILE}" \
  "${CHECKLIST_SYNC_REPO}/dev/workflow" feature materialize --id F1-M1 --mode issues-sync --issue-id I2-F1-M1 --write --github
assert_json_value "checklist-sync-materialize" "feature_issue_checklist_sync.updated" "true"
assert_json_value "checklist-sync-materialize" "feature_issue_checklist_sync.added_issue_ids.0" "I2-F1-M1"
assert_file_contains "checklist-sync-materialize-body" "${CHECKLIST_BODY_FILE}" "- [ ] I2-F1-M1: Second issue"
run_expect_success \
  "checklist-sync-confirm-issue-done" \
  env PATH="${CHECKLIST_FAKE_GH_DIR}:${PATH}" CHECKLIST_FAKE_GH_LOG="${CHECKLIST_FAKE_GH_LOG}" CHECKLIST_BODY_FILE="${CHECKLIST_BODY_FILE}" \
  "${CHECKLIST_SYNC_REPO}/dev/workflow" confirm issue --id I2-F1-M1 done --write --force
assert_json_value "checklist-sync-confirm-issue-done" "feature_issue_checklist_sync.row_found" "true"
assert_json_value "checklist-sync-confirm-issue-done" "feature_issue_checklist_sync.updated" "true"
assert_file_contains "checklist-sync-confirm-body" "${CHECKLIST_BODY_FILE}" "- [x] I2-F1-M1: Second issue"

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
