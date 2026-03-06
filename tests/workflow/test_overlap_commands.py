import json

import pytest


def _write_minimal_repo_state(tmp_repo):
    """Write minimal tracker files required by overlap command tests."""
    dev_map = {
        "version": "1.0",
        "updated_at": "2026-03-06T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Pending", "Planned", "Tasked", "Done", "Approved", "Rejected"],
        "milestones": [
            {
                "id": "M1",
                "title": "Milestone 1",
                "status": "Planned",
                "features": [
                    {
                        "id": "F14-M1",
                        "title": "Overlap feature",
                        "description": "Overlap feature description.",
                        "status": "Approved",
                        "track": "System/Test",
                        "gh_issue_number": 10,
                        "gh_issue_url": "https://github.com/owner/repo/issues/10",
                        "issues": [
                            {
                                "id": "I1-F14-M1",
                                "title": "Issue one",
                                "description": "Issue one description.",
                                "status": "Planned",
                                "gh_issue_number": 11,
                                "gh_issue_url": "https://github.com/owner/repo/issues/11",
                                "tasks": [],
                            },
                            {
                                "id": "I2-F14-M1",
                                "title": "Issue two",
                                "description": "Issue two description.",
                                "status": "Planned",
                                "gh_issue_number": 12,
                                "gh_issue_url": "https://github.com/owner/repo/issues/12",
                                "tasks": [],
                            },
                        ],
                        "branch_name": None,
                        "branch_url": None,
                    }
                ],
                "standalone_issues": [],
            }
        ],
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map, indent=2), encoding="utf-8")
    (tmp_repo / "dev/TASK_LIST.json").write_text('{"schema_version":"1.0","tasks":[]}\n', encoding="utf-8")
    (tmp_repo / "dev/ISSUE_OVERLAPS.json").write_text(
        '{"schema_version":"1.0","overlaps":[]}\n',
        encoding="utf-8",
    )
    (tmp_repo / "dev/ISSUE_DEP_INDEX.json").write_text(
        '{"schema_version":"1.0","feature_scope":"all","by_issue":{},"by_surface":{}}\n',
        encoding="utf-8",
    )
    (tmp_repo / "dev/FEATURE_PLANS.md").write_text(
        "# Feature Plans\n"
        "## F14-M1\n"
        "### Dependencies\n"
        "- file: dev/workflow_lib/feature_commands.py | reason: planning command surface\n\n"
        "### Decomposition\n"
        "1. Build dependency index and dedicated overlap helpers.\n\n"
        "### Issue Execution Order\n"
        "1. `I1-F14-M1` - Issue one\n"
        "2. `I2-F14-M1` - Issue two\n\n"
        "### Issue/Task Decomposition Assessment\n"
        "- task_count = 0\n\n"
        "### I1-F14-M1 - Issue one\n"
        "#### Dependencies\n"
        "- file: dev/workflow_lib/feature_commands.py | reason: parser and router work\n"
        "- module: dev.workflow_lib.context | reason: shared path wiring\n"
        "#### Decomposition\n"
        "1. Step one.\n"
        "#### Issue/Task Decomposition Assessment\n"
        "- task_count = 0\n\n"
        "### I2-F14-M1 - Issue two\n"
        "#### Dependencies\n"
        "- file: dev/workflow_lib/feature_commands.py | reason: same parser surface\n"
        "- file: dev/workflow_lib/tracker_store.py | reason: overlap storage work\n"
        "#### Decomposition\n"
        "1. Step two.\n"
        "#### Issue/Task Decomposition Assessment\n"
        "- task_count = 0\n",
        encoding="utf-8",
    )


def test_plan_lint_rejects_invalid_issue_dependency_line(workflow, tmp_repo):
    """Lint must fail when one issue block uses free-form dependency prose."""
    _write_minimal_repo_state(tmp_repo)
    plans_path = tmp_repo / "dev/FEATURE_PLANS.md"
    plans_path.write_text(
        plans_path.read_text(encoding="utf-8").replace(
            "- file: dev/workflow_lib/tracker_store.py | reason: overlap storage work",
            "- free form dependency prose",
        ),
        encoding="utf-8",
    )

    with pytest.raises(pytest.fail.Exception) as excinfo:
        workflow.run("feature", "plan-lint", "--id", "F14-M1")
    assert "invalid dependency line" in str(excinfo.value)


def test_index_dependencies_and_get_plan_block(workflow, tmp_repo):
    """Dependency commands must index strict dependency lines and return Dependencies-only blocks."""
    _write_minimal_repo_state(tmp_repo)

    index_result = workflow.run("plan", "index-dependencies", "--feature-id", "F14-M1", "--write")
    assert index_result["issues_reindexed"] == 2

    related_result = workflow.run("plan", "show-related", "--issue-id", "I1-F14-M1")
    assert related_result["related_issues"][0]["issue_id"] == "I2-F14-M1"
    assert "file: dev/workflow_lib/feature_commands.py" in related_result["related_issues"][0]["matched_surfaces"]

    block_result = workflow.run("plan", "get-plan-block", "--issue-id", "I1-F14-M1")
    assert "module: dev.workflow_lib.context" in block_result["dependencies"]


def test_apply_and_show_issue_overlaps(workflow, tmp_repo):
    """Overlap commands must validate, persist, and filter dedicated overlap records."""
    _write_minimal_repo_state(tmp_repo)
    overlap_delta = tmp_repo / "overlaps.json"
    overlap_delta.write_text(
        json.dumps(
            {
                "overlaps": [
                    {
                        "issues": ["I1-F14-M1", "I2-F14-M1"],
                        "type": "shared_logic",
                        "surface": "file: dev/workflow_lib/feature_commands.py",
                        "description": "why: same parser helpers; impact: duplicate parsing logic would drift; action: keep one shared dependency parser.",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    apply_result = workflow.run("plan", "apply-overlaps", "--delta-file", str(overlap_delta), "--write")
    assert apply_result["overlap_count"] == 1

    show_result = workflow.run("plan", "show-overlaps", "--issue-id", "I1-F14-M1")
    assert len(show_result["overlaps"]) == 1
    assert show_result["overlaps"][0]["issues"] == ["I1-F14-M1", "I2-F14-M1"]


def test_execution_plan_does_not_require_pipeline_file(workflow, tmp_repo):
    """Execution planning must work without TASK_EXECUTION_PIPELINE after cutover."""
    _write_minimal_repo_state(tmp_repo)
    result = workflow.run("feature", "execution-plan", "--id", "F14-M1", "--only-pending")
    assert result["feature_id"] == "F14-M1"


def test_migrate_overlaps_is_retired_after_pipeline_cutover(workflow, tmp_repo):
    """Legacy pipeline migration command should fail deterministically after cutover."""
    _write_minimal_repo_state(tmp_repo)
    with pytest.raises(pytest.fail.Exception) as excinfo:
        workflow.run("plan", "migrate-overlaps", "--write")
    assert "retired" in str(excinfo.value)


def test_confirm_issue_cleans_issue_overlaps_and_dependency_index(workflow, tmp_repo):
    """Confirm issue must remove issue-level overlap and dependency-index rows for that issue."""
    _write_minimal_repo_state(tmp_repo)

    dev_map_path = tmp_repo / "dev/map/DEV_MAP.json"
    dev_map = json.loads(dev_map_path.read_text(encoding="utf-8"))
    issue_one = dev_map["milestones"][0]["features"][0]["issues"][0]
    issue_one["status"] = "Tasked"
    issue_one["tasks"] = [{"id": "1", "title": "Task one", "summary": "Task summary", "status": "Planned"}]
    dev_map_path.write_text(json.dumps(dev_map, indent=2), encoding="utf-8")

    (tmp_repo / "dev/TASK_LIST.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "tasks": [
                    {
                        "id": "1",
                        "marker": "[M1][F14]",
                        "title": "Task one",
                        "problem": "Need cleanup coverage.",
                        "solution_option": "Run confirm cleanup.",
                        "concrete_steps": ["Confirm issue and prune trackers."],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_repo / "dev/ISSUE_OVERLAPS.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "overlaps": [
                    {
                        "issues": ["I1-F14-M1", "I2-F14-M1"],
                        "type": "shared_logic",
                        "surface": "file: dev/workflow_lib/feature_commands.py",
                        "description": "why: shared command helpers; impact: cleanup must remove stale pair rows; action: drop pair when one issue is confirmed done.",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_repo / "dev/ISSUE_DEP_INDEX.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "feature_scope": "all",
                "by_issue": {
                    "I1-F14-M1": {
                        "surfaces": ["file: dev/workflow_lib/feature_commands.py"],
                        "feature_id": "F14-M1",
                        "status": "Tasked",
                    },
                    "I2-F14-M1": {
                        "surfaces": ["file: dev/workflow_lib/feature_commands.py"],
                        "feature_id": "F14-M1",
                        "status": "Planned",
                    },
                },
                "by_surface": {
                    "file: dev/workflow_lib/feature_commands.py": {
                        "surface": "file: dev/workflow_lib/feature_commands.py",
                        "issue_ids": ["I1-F14-M1", "I2-F14-M1"],
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = workflow.run(
        "confirm",
        "issue",
        "--id",
        "I1-F14-M1",
        "done",
        "--write",
        "--force",
        "--no-close-github",
    )
    assert result["issue_status_after"] == "Done"

    task_list = json.loads((tmp_repo / "dev/TASK_LIST.json").read_text(encoding="utf-8"))
    assert task_list["tasks"] == []

    issue_overlaps = json.loads((tmp_repo / "dev/ISSUE_OVERLAPS.json").read_text(encoding="utf-8"))
    assert issue_overlaps["overlaps"] == []

    issue_dep_index = json.loads((tmp_repo / "dev/ISSUE_DEP_INDEX.json").read_text(encoding="utf-8"))
    assert "I1-F14-M1" not in issue_dep_index["by_issue"]
    assert issue_dep_index["by_surface"]["file: dev/workflow_lib/feature_commands.py"]["issue_ids"] == ["I2-F14-M1"]
