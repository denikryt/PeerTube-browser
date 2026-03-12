import json


def _write_feature_fixture(tmp_repo):
    dev_map = {
        "schema_version": "1.4",
        "updated_at": "2026-03-12T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Pending", "Draft", "Planned", "Done", "Approved", "Tasked", "Rejected"],
        "milestones": [
            {
                "id": "M1",
                "title": "Milestone 1",
                "goal": "Smoke goal",
                "features": [
                    {
                        "id": "F9-M1",
                        "milestone_id": "M1",
                        "title": "Smoke feature",
                        "description": "Feature description.",
                        "status": "Planned",
                        "track": "System/Test",
                        "gh_issue_number": 91,
                        "gh_issue_url": "https://github.com/owner/repo/issues/91",
                        "issues": [
                            {
                                "id": "I1-F9-M1",
                                "feature_id": "F9-M1",
                                "milestone_id": "M1",
                                "title": "Smoke issue",
                                "description": "Issue description.",
                                "status": "Planned",
                                "gh_issue_number": 92,
                                "gh_issue_url": "https://github.com/owner/repo/issues/92",
                            }
                        ],
                        "branch_name": "feature/F9-M1",
                        "branch_url": "https://github.com/owner/repo/tree/feature/F9-M1",
                    }
                ],
                "standalone_issues": [],
                "non_feature_items": [],
            }
        ],
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map, indent=2), encoding="utf-8")
    (tmp_repo / "dev/TASK_LIST.json").write_text('{"schema_version":"1.0","tasks":[]}\n', encoding="utf-8")
    (tmp_repo / "dev/FEATURE_PLANS.md").write_text(
        "## F9-M1\n"
        "### Expected Behaviour\n"
        "- Smoke feature should remain executable with local task text stored only in the plan.\n\n"
        "### I1-F9-M1 - Smoke issue\n"
        "#### Expected Behaviour\n"
        "- Smoke issue should expose local task decomposition in the plan only.\n"
        "#### Dependencies\n"
        "- file: dev/workflow_lib/feature_commands.py | reason: smoke execution surface\n"
        "#### Decomposition\n"
        "1. Update the execution command contract.\n"
        "2. Verify readiness output.\n"
        "#### Issue/Task Decomposition Assessment\n"
        "- task_count = 2\n",
        encoding="utf-8",
    )


def test_execute_feature_uses_issue_materialization_and_plan_tasks(workflow, tmp_repo):
    _write_feature_fixture(tmp_repo)

    res = workflow.run("execute", "feature", "--id", "F9-M1")
    assert res["ready"] is True
    assert res["feature_materialized"] is True
    assert res["issue_execution_order"] == ["I1-F9-M1"]
    assert res["issues"][0]["has_local_task_plan"] is True


def test_done_issue_marks_local_done_without_remote(workflow, tmp_repo):
    _write_feature_fixture(tmp_repo)

    res = workflow.run("done", "issue", "--id", "I1-F9-M1", "--write")
    assert res["status_after"] == "Done"
    assert res["remote_closed"] is False

    updated_map = json.loads((tmp_repo / "dev/map/DEV_MAP.json").read_text(encoding="utf-8"))
    issue_node = updated_map["milestones"][0]["features"][0]["issues"][0]
    assert issue_node["status"] == "Done"


def test_tracking_validate_no_longer_requires_devmap_task_ownership(workflow, tmp_repo):
    _write_feature_fixture(tmp_repo)

    res = workflow.run("validate", "--scope", "tracking", "--feature", "F9-M1")
    assert res["valid"] is True


def test_clean_issue_removes_local_plan_and_overlap_artifacts(workflow, tmp_repo):
    _write_feature_fixture(tmp_repo)
    (tmp_repo / "dev/ISSUE_OVERLAPS.json").write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "issue_execution_order": {"ordered_issue_ids": ["I1-F9-M1"]},
                "overlaps": [
                    {
                        "issues": ["I1-F9-M1", "I9-F1-M1"],
                        "type": "dependency",
                        "surface": "dev/workflow_lib/feature_commands.py",
                        "order": "I9-F1-M1->I1-F9-M1",
                        "description": "why: smoke overlap exists; impact: smoke cleanup must prune it; action: remove issue-owned overlap rows."
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (tmp_repo / "dev/ISSUE_DEP_INDEX.json").write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "scope_type": "all",
                "scope_id": "all",
                "by_issue": {"I1-F9-M1": {"surface_keys": ["file:dev/workflow_lib/feature_commands.py"]}},
                "by_surface": {"file:dev/workflow_lib/feature_commands.py": ["I1-F9-M1"]},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    res = workflow.run("clean", "issue", "--id", "I1-F9-M1", "--write")
    assert res["cleanup"]["issue_overlaps"]["overlap_rows_removed"] == 1

    feature_plans = (tmp_repo / "dev/FEATURE_PLANS.md").read_text(encoding="utf-8")
    assert "### I1-F9-M1 - Smoke issue" not in feature_plans
