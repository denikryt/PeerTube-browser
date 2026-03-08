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
        '{"schema_version":"1.1","issue_execution_order":{"ordered_issue_ids":[]},"overlaps":[]}\n',
        encoding="utf-8",
    )
    (tmp_repo / "dev/ISSUE_DEP_INDEX.json").write_text(
        '{"schema_version":"1.1","scope_type":"all","scope_id":"all","by_issue":{},"by_surface":{}}\n',
        encoding="utf-8",
    )
    (tmp_repo / "dev/FEATURE_PLANS.md").write_text(
        "# Feature Plans\n"
        "## F14-M1\n"
        "### Expected Behaviour\n"
        "- Overlap planning should expose deterministic related-issue context for this feature.\n"
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
        "#### Expected Behaviour\n"
        "- Issue one should publish dependency surfaces for overlap discovery.\n"
        "#### Dependencies\n"
        "- file: dev/workflow_lib/feature_commands.py | reason: parser and router work\n"
        "- module: dev.workflow_lib.context | reason: shared path wiring\n"
        "#### Decomposition\n"
        "1. Step one.\n"
        "#### Issue/Task Decomposition Assessment\n"
        "- task_count = 0\n\n"
        "### I2-F14-M1 - Issue two\n"
        "#### Expected Behaviour\n"
        "- Issue two should share at least one dependency surface with issue one.\n"
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


def test_plan_lint_rejects_missing_expected_behaviour(workflow, tmp_repo):
    """Lint must fail when feature or issue plan blocks omit Expected Behaviour sections."""
    _write_minimal_repo_state(tmp_repo)
    plans_path = tmp_repo / "dev/FEATURE_PLANS.md"
    plans_path.write_text(
        plans_path.read_text(encoding="utf-8").replace("### Expected Behaviour\n- Overlap planning should expose deterministic related-issue context for this feature.\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(pytest.fail.Exception) as excinfo:
        workflow.run("feature", "plan-lint", "--id", "F14-M1")
    assert "Expected Behaviour" in str(excinfo.value)


def test_plan_lint_strict_rejects_expected_behaviour_placeholder(workflow, tmp_repo):
    """Strict lint must reject placeholder Expected Behaviour text in issue blocks."""
    _write_minimal_repo_state(tmp_repo)
    plans_path = tmp_repo / "dev/FEATURE_PLANS.md"
    plans_path.write_text(
        plans_path.read_text(encoding="utf-8").replace(
            "- Issue one should publish dependency surfaces for overlap discovery.",
            "- TODO describe expected behaviour here.",
        ),
        encoding="utf-8",
    )

    with pytest.raises(pytest.fail.Exception) as excinfo:
        workflow.run("feature", "plan-lint", "--id", "F14-M1", "--strict")
    assert "placeholder content" in str(excinfo.value)


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


def test_issue_dependency_index_load_migrates_legacy_verbose_shape(workflow, tmp_repo):
    """Legacy dep-index payloads should be migrated into the reduced canonical shape on load."""
    _write_minimal_repo_state(tmp_repo)
    (tmp_repo / "dev/ISSUE_DEP_INDEX.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "feature_scope": "I1-F14-M1",
                "by_issue": {
                    "I1-F14-M1": {
                        "surfaces": [
                            "file: dev/workflow_lib/feature_commands.py",
                            "file: dev/workflow_lib/feature_commands.py",
                        ],
                        "feature_id": "F14-M1",
                        "status": "Planned",
                    }
                },
                "by_surface": {
                    "file: dev/workflow_lib/feature_commands.py": {
                        "surface": "file: dev/workflow_lib/feature_commands.py",
                        "issue_ids": ["I1-F14-M1"],
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    index_result = workflow.run("plan", "index-dependencies", "--issue-id", "I1-F14-M1", "--write")
    assert index_result["issues_reindexed"] == 1

    rewritten = json.loads((tmp_repo / "dev/ISSUE_DEP_INDEX.json").read_text(encoding="utf-8"))
    assert rewritten["scope_type"] == "issue"
    assert rewritten["scope_id"] == "I1-F14-M1"
    assert rewritten["by_issue"]["I1-F14-M1"]["surface_keys"] == [
        "file: dev/workflow_lib/feature_commands.py",
        "module: dev.workflow_lib.context",
    ]
    assert rewritten["by_surface"]["file: dev/workflow_lib/feature_commands.py"] == ["I1-F14-M1"]


def test_issue_dependency_index_rejects_hybrid_shape(workflow, tmp_repo):
    """Hybrid dep-index payloads mixing reduced and legacy fields should fail deterministically."""
    _write_minimal_repo_state(tmp_repo)
    (tmp_repo / "dev/ISSUE_DEP_INDEX.json").write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "scope_type": "issue",
                "scope_id": "I1-F14-M1",
                "by_issue": {
                    "I1-F14-M1": {
                        "surface_keys": ["file: dev/workflow_lib/feature_commands.py"],
                        "status": "Planned",
                    }
                },
                "by_surface": {
                    "file: dev/workflow_lib/feature_commands.py": ["I1-F14-M1"]
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(pytest.fail.Exception) as excinfo:
        workflow.run("plan", "show-related", "--issue-id", "I1-F14-M1")
    assert "legacy fields" in str(excinfo.value)


def test_issue_scoped_index_refresh_preserves_shared_surface_peers(workflow, tmp_repo):
    """Issue-scoped dep-index refresh must keep unrelated peer issue IDs on shared surfaces."""
    _write_minimal_repo_state(tmp_repo)

    workflow.run("plan", "index-dependencies", "--feature-id", "F14-M1", "--write")
    refresh_result = workflow.run("plan", "index-dependencies", "--issue-id", "I1-F14-M1", "--write")

    payload = json.loads((tmp_repo / "dev/ISSUE_DEP_INDEX.json").read_text(encoding="utf-8"))
    assert payload["by_surface"]["file: dev/workflow_lib/feature_commands.py"] == ["I1-F14-M1", "I2-F14-M1"]
    assert refresh_result["surfaces_pruned"] == 1
    assert refresh_result["surfaces_added"] == 1
    assert refresh_result["surfaces_updated"] == 1

    related_result = workflow.run("plan", "show-related", "--issue-id", "I1-F14-M1")
    assert related_result["related_issues"][0]["issue_id"] == "I2-F14-M1"


def test_issue_and_feature_dep_index_refresh_converge_to_same_state(workflow, tmp_repo):
    """Issue-scoped refresh followed by feature refresh should converge to the same reduced dep-index state."""
    _write_minimal_repo_state(tmp_repo)

    workflow.run("plan", "index-dependencies", "--feature-id", "F14-M1", "--write")
    feature_payload_before = json.loads((tmp_repo / "dev/ISSUE_DEP_INDEX.json").read_text(encoding="utf-8"))

    workflow.run("plan", "index-dependencies", "--issue-id", "I1-F14-M1", "--write")
    workflow.run("plan", "index-dependencies", "--feature-id", "F14-M1", "--write")
    feature_payload_after = json.loads((tmp_repo / "dev/ISSUE_DEP_INDEX.json").read_text(encoding="utf-8"))

    assert feature_payload_after == feature_payload_before


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
    stored_payload = json.loads((tmp_repo / "dev/ISSUE_OVERLAPS.json").read_text(encoding="utf-8"))
    assert stored_payload["issue_execution_order"]["ordered_issue_ids"] == ["I1-F14-M1", "I2-F14-M1"]


def test_execution_plan_does_not_require_pipeline_file(workflow, tmp_repo):
    """Execution planning must work without FEATURE_PLANS issue-order blocks after overlaps cutover."""
    _write_minimal_repo_state(tmp_repo)
    dev_map_path = tmp_repo / "dev/map/DEV_MAP.json"
    dev_map = json.loads(dev_map_path.read_text(encoding="utf-8"))
    feature = dev_map["milestones"][0]["features"][0]
    feature["issues"][0]["tasks"] = [{"id": "1", "title": "Task one", "summary": "Task summary", "status": "Planned"}]
    feature["issues"][1]["tasks"] = [{"id": "2", "title": "Task two", "summary": "Task summary", "status": "Planned"}]
    dev_map_path.write_text(json.dumps(dev_map, indent=2), encoding="utf-8")
    plans_path = tmp_repo / "dev/FEATURE_PLANS.md"
    plans_path.write_text(
        plans_path.read_text(encoding="utf-8").replace(
            "### Issue Execution Order\n1. `I1-F14-M1` - Issue one\n2. `I2-F14-M1` - Issue two\n\n",
            "",
        ),
        encoding="utf-8",
    )
    (tmp_repo / "dev/ISSUE_OVERLAPS.json").write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "issue_execution_order": {
                    "ordered_issue_ids": ["I2-F14-M1", "I1-F14-M1"]
                },
                "overlaps": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    result = workflow.run("feature", "execution-plan", "--id", "F14-M1", "--only-pending")
    assert result["feature_id"] == "F14-M1"
    assert result["next_issue_from_plan_order"]["id"] == "I2-F14-M1"
    assert [task["issue_id"] for task in result["tasks"]] == ["I2-F14-M1", "I1-F14-M1"]


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
                "schema_version": "1.1",
                "issue_execution_order": {"ordered_issue_ids": ["I1-F14-M1", "I2-F14-M1"]},
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
                "schema_version": "1.1",
                "scope_type": "all",
                "scope_id": "all",
                "by_issue": {
                    "I1-F14-M1": {
                        "surface_keys": ["file: dev/workflow_lib/feature_commands.py"],
                    },
                    "I2-F14-M1": {
                        "surface_keys": ["file: dev/workflow_lib/feature_commands.py"],
                    },
                },
                "by_surface": {
                    "file: dev/workflow_lib/feature_commands.py": ["I1-F14-M1", "I2-F14-M1"]
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
    assert issue_overlaps["issue_execution_order"]["ordered_issue_ids"] == ["I2-F14-M1"]

    issue_dep_index = json.loads((tmp_repo / "dev/ISSUE_DEP_INDEX.json").read_text(encoding="utf-8"))
    assert "I1-F14-M1" not in issue_dep_index["by_issue"]
    assert issue_dep_index["by_surface"]["file: dev/workflow_lib/feature_commands.py"] == ["I2-F14-M1"]


def test_confirm_feature_preview_reports_feature_plan_section_cleanup(workflow, tmp_repo):
    """Confirm feature preview should report full FEATURE_PLANS section cleanup without mutating files."""
    _write_minimal_repo_state(tmp_repo)

    dev_map_path = tmp_repo / "dev/map/DEV_MAP.json"
    dev_map = json.loads(dev_map_path.read_text(encoding="utf-8"))
    feature = dev_map["milestones"][0]["features"][0]
    feature["status"] = "Tasked"
    feature["issues"][0]["status"] = "Tasked"
    feature["issues"][0]["tasks"] = [{"id": "1", "title": "Task one", "summary": "Task summary", "status": "Planned"}]
    feature["issues"][1]["status"] = "Tasked"
    feature["issues"][1]["tasks"] = [{"id": "2", "title": "Task two", "summary": "Task summary", "status": "Planned"}]
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
                        "problem": "Need feature cleanup preview.",
                        "solution_option": "Run confirm feature preview.",
                        "concrete_steps": ["Preview feature cleanup."],
                    },
                    {
                        "id": "2",
                        "marker": "[M1][F14]",
                        "title": "Task two",
                        "problem": "Need feature cleanup preview.",
                        "solution_option": "Run confirm feature preview.",
                        "concrete_steps": ["Preview feature cleanup."],
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    plans_before = (tmp_repo / "dev/FEATURE_PLANS.md").read_text(encoding="utf-8")
    result = workflow.run(
        "confirm",
        "feature",
        "--id",
        "F14-M1",
        "done",
        "--no-close-github",
    )

    assert result["cleanup"]["feature_plans"]["feature_section_would_be_removed"] is True
    assert result["cleanup"]["feature_plans"]["feature_section_removed"] is False
    assert (tmp_repo / "dev/FEATURE_PLANS.md").read_text(encoding="utf-8") == plans_before


def test_confirm_feature_write_removes_feature_plan_section(workflow, tmp_repo):
    """Confirm feature write should remove the full FEATURE_PLANS section for the confirmed feature."""
    _write_minimal_repo_state(tmp_repo)

    dev_map_path = tmp_repo / "dev/map/DEV_MAP.json"
    dev_map = json.loads(dev_map_path.read_text(encoding="utf-8"))
    feature = dev_map["milestones"][0]["features"][0]
    feature["status"] = "Tasked"
    feature["issues"][0]["status"] = "Tasked"
    feature["issues"][0]["tasks"] = [{"id": "1", "title": "Task one", "summary": "Task summary", "status": "Planned"}]
    feature["issues"][1]["status"] = "Tasked"
    feature["issues"][1]["tasks"] = [{"id": "2", "title": "Task two", "summary": "Task summary", "status": "Planned"}]
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
                        "problem": "Need feature cleanup write path.",
                        "solution_option": "Run confirm feature write.",
                        "concrete_steps": ["Apply feature cleanup."],
                    },
                    {
                        "id": "2",
                        "marker": "[M1][F14]",
                        "title": "Task two",
                        "problem": "Need feature cleanup write path.",
                        "solution_option": "Run confirm feature write.",
                        "concrete_steps": ["Apply feature cleanup."],
                    },
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
                "schema_version": "1.1",
                "issue_execution_order": {
                    "ordered_issue_ids": ["I1-F14-M1", "I2-F14-M1", "I7-F99-M1"]
                },
                "overlaps": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = workflow.run(
        "confirm",
        "feature",
        "--id",
        "F14-M1",
        "done",
        "--write",
        "--no-close-github",
    )

    assert result["cleanup"]["feature_plans"]["feature_section_removed"] is True
    plans_after = (tmp_repo / "dev/FEATURE_PLANS.md").read_text(encoding="utf-8")
    assert "## F14-M1" not in plans_after
    issue_overlaps = json.loads((tmp_repo / "dev/ISSUE_OVERLAPS.json").read_text(encoding="utf-8"))
    assert issue_overlaps["issue_execution_order"]["ordered_issue_ids"] == ["I7-F99-M1"]


def test_confirm_feature_write_is_stable_when_feature_plan_section_is_missing(workflow, tmp_repo):
    """Confirm feature write should stay stable when the feature section is already absent."""
    _write_minimal_repo_state(tmp_repo)

    dev_map_path = tmp_repo / "dev/map/DEV_MAP.json"
    dev_map = json.loads(dev_map_path.read_text(encoding="utf-8"))
    feature = dev_map["milestones"][0]["features"][0]
    feature["status"] = "Tasked"
    feature["issues"][0]["status"] = "Tasked"
    feature["issues"][0]["tasks"] = [{"id": "1", "title": "Task one", "summary": "Task summary", "status": "Planned"}]
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
                        "problem": "Need no-op feature cleanup path.",
                        "solution_option": "Run confirm on missing section.",
                        "concrete_steps": ["Apply no-op feature cleanup."],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_repo / "dev/FEATURE_PLANS.md").write_text("# Feature Plans\n", encoding="utf-8")

    result = workflow.run(
        "confirm",
        "feature",
        "--id",
        "F14-M1",
        "done",
        "--write",
        "--no-close-github",
    )

    assert result["cleanup"]["feature_plans"]["feature_section_found"] is False
    assert result["cleanup"]["feature_plans"]["feature_section_removed"] is False
