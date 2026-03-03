import pytest
import json

def test_plan_tasks_success_chain(workflow, tmp_repo):
    """
    Tests the complex task planning flow:
    1. Setup milestone and feature.
    2. Add an issue to DEV_MAP but keep it 'Pending'.
    3. Verify that 'plan tasks' fails due to 'Pending' status.
    4. Move issue to 'Planned' via FEATURE_PLANS.md + empty delta.
    5. Run full 'plan tasks' with delta and verify 'Tasked' status.
    """
    # 1. Setup initial state
    dev_map = {
        "version": "1.0",
        "updated_at": "2026-02-24T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Pending", "Planned", "Tasked", "Done", "Approved"],
        "milestones": [
            {
                "id": "M1",
                "title": "Milestone 1",
                "status": "Planned",
                "features": [
                    {
                        "id": "F9-M1",
                        "title": "Smoke feature",
                        "status": "Planned",
                        "track": "System/Test",
                        "issues": [
                            {
                                "id": "I1-F9-M1",
                                "title": "Smoke issue",
                                "status": "Pending",
                                "gh_issue_number": None,
                                "gh_issue_url": None,
                                "tasks": []
                            }
                        ]
                    }
                ]
            }
        ]
    }
    dev_map_path = tmp_repo / "dev/map/DEV_MAP.json"
    dev_map_path.write_text(json.dumps(dev_map, indent=2), encoding="utf-8")

    # delta.json
    delta = {
        "issues": [
            {
                "id": "I1-F9-M1",
                "title": "Smoke issue",
                "tasks": [{"id": "$t1", "title": "Smoke task", "summary": "Smoke summary"}]
            }
        ],
        "task_list_entries": [
            {
                "id": "$t1",
                "title": "Smoke task",
                "problem": "Deterministic smoke.",
                "solution_option": "Execute flow.",
                "concrete_steps": ["Run command."]
            }
        ],
        "pipeline": {
            "execution_sequence_append": [{"tasks": ["$t1"], "description": "smoke-chain"}],
            "functional_blocks_append": [{"title": "Smoke block", "tasks": ["$t1"], "scope": "Smoke flow.", "outcome": "Success."}],
            "overlaps_append": []
        }
    }
    delta_path = tmp_repo / "dev/sync_delta.json"
    delta_path.write_text(json.dumps(delta, indent=2), encoding="utf-8")

    # 2. Verify failure on 'Pending' status
    # We need --allocate-task-ids because delta.json uses tokens ($t1)
    with pytest.raises(pytest.fail.Exception) as excinfo:
        workflow.run("plan", "tasks", "for", "feature", "--id", "F9-M1", "--delta-file", str(delta_path), "--write", "--allocate-task-ids")
    assert "cannot run for issue I1-F9-M1 with status 'Pending'" in str(excinfo.value)

    # 3. Setup FEATURE_PLANS.md to promote to 'Planned'
    plans_path = tmp_repo / "dev/FEATURE_PLANS.md"
    plans_content = """# Feature Plans
## F9-M1
### Issue Execution Order
1. `I1-F9-M1` - Smoke issue

### I1-F9-M1 - Smoke issue
#### Dependencies
- smoke
#### Decomposition
1. smoke
"""
    plans_path.write_text(plans_content, encoding="utf-8")

    # 4. Promote to 'Planned' using empty delta
    empty_delta_path = tmp_repo / "dev/empty_delta.json"
    empty_delta_path.write_text("{}", encoding="utf-8")
    res = workflow.run("plan", "tasks", "for", "feature", "--id", "F9-M1", "--delta-file", str(empty_delta_path), "--write")
    assert "I1-F9-M1" in res["issue_planning_status_reconciliation"]["reconciled_issue_ids"]

    # Verify status in DEV_MAP
    updated_map = json.loads(dev_map_path.read_text(encoding="utf-8"))
    assert updated_map["milestones"][0]["features"][0]["issues"][0]["status"] == "Planned"

    # 5. Run full 'plan tasks' and verify 'Tasked'
    res = workflow.run("plan", "tasks", "for", "feature", "--id", "F9-M1", "--delta-file", str(delta_path), "--write", "--allocate-task-ids", "--update-pipeline")
    assert res["action"] == "planned-tasks"
    assert res["task_count_after"] == 1
    
    # Verify final status
    updated_map = json.loads(dev_map_path.read_text(encoding="utf-8"))
    assert updated_map["milestones"][0]["features"][0]["issues"][0]["status"] == "Tasked"

def test_batch_issue_planning(workflow, tmp_repo):
    """Verifies that multiple issues can be planned in a single batch command."""
    # Setup F1-M1 with two issues
    dev_map = {
        "version": "1.0",
        "updated_at": "2026-02-24T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Planned", "Tasked", "Done"],
        "milestones": [
            {
                "id": "M1", "title": "M1", "status": "Planned",
                "features": [
                    {
                        "id": "F1-M1", "title": "F1", "status": "Planned", "track": "Test",
                        "issues": [
                            {"id": "I1-F1-M1", "title": "I1", "status": "Planned", "tasks": []},
                            {"id": "I2-F1-M1", "title": "I2", "status": "Planned", "tasks": []}
                        ]
                    }
                ]
            }
        ]
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map), encoding="utf-8")
    
    # Needs FEATURE_PLANS.md section with issue blocks for status reconciliation
    plans = (
        "# Feature Plans\n"
        "## F1-M1\n"
        "### Issue Execution Order\n"
        "1. `I1-F1-M1` - I1\n"
        "2. `I2-F1-M1` - I2\n\n"
        "### `I1-F1-M1` - I1\n"
        "#### Dependencies\n- None\n"
        "#### Decomposition\n- T1\n"
        "#### Issue/Task Decomposition Assessment\n- OK\n\n"
        "### `I2-F1-M1` - I2\n"
        "#### Dependencies\n- None\n"
        "#### Decomposition\n- T2\n"
        "#### Issue/Task Decomposition Assessment\n- OK\n"
    )
    (tmp_repo / "dev/FEATURE_PLANS.md").write_text(plans, encoding="utf-8")
    
    delta = {
        "issues": [
            {"id": "I1-F1-M1", "tasks": [{"id": "$t1", "title": "T1", "summary": "S"}]},
            {"id": "I2-F1-M1", "tasks": [{"id": "$t2", "title": "T2", "summary": "S"}]}
        ],
        "task_list_entries": [
            {"id": "$t1", "title": "T1", "problem": "P", "solution_option": "S", "concrete_steps": ["C"]},
            {"id": "$t2", "title": "T2", "problem": "P", "solution_option": "S", "concrete_steps": ["C"]}
        ],
        "pipeline": {
            "execution_sequence_append": [{"tasks": ["$t1", "$t2"], "description": "batch"}],
            "functional_blocks_append": [{"title": "B", "tasks": ["$t1", "$t2"], "scope": "S", "outcome": "O"}],
            "overlaps_append": []
        }
    }
    delta_path = tmp_repo / "dev/batch_delta.json"
    delta_path.write_text(json.dumps(delta), encoding="utf-8")
    
    res = workflow.run("plan", "tasks", "for", "issues", "--issue-id", "I1-F1-M1", "--issue-id", "I2-F1-M1", "--delta-file", str(delta_path), "--write", "--allocate-task-ids", "--update-pipeline")
    assert res["dev_map_tasks_upserted"] == 2
    
    updated_map = json.loads((tmp_repo / "dev/map/DEV_MAP.json").read_text())
    issues = updated_map["milestones"][0]["features"][0]["issues"]
    # Check status by looking up in the list
    status_by_id = {i["id"]: i["status"] for i in issues}
    assert status_by_id["I1-F1-M1"] == "Tasked", f"I1-F1-M1 status is {status_by_id.get('I1-F1-M1')}. Full issues: {issues}"
    assert status_by_id["I2-F1-M1"] == "Tasked", f"I2-F1-M1 status is {status_by_id.get('I2-F1-M1')}. Full issues: {issues}"

def test_materialize_missing_milestone_title_fails(workflow, tmp_repo):
    """Verifies that materialization fails if the milestone title is empty in DEV_MAP."""
    dev_map = {
        "version": "1.0", "updated_at": "2026-02-24T0", "task_count": 0, "statuses": ["Planned"],
        "milestones": [{"id": "M1", "title": "", "status": "Planned", "features": [{"id": "F1-M1", "title": "F1", "status": "Planned"}]}]
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map), encoding="utf-8")
    
    with pytest.raises(pytest.fail.Exception) as excinfo:
        workflow.run("feature", "materialize", "--id", "F1-M1", "--mode", "issues-sync")
    assert "has empty title in DEV_MAP" in str(excinfo.value)

def test_issue_mapping_skip_logic(workflow, tmp_repo):
    """Verifies that already mapped issues (with gh_issue_number) are skipped during creation."""
    dev_map = {
        "version": "1.0", "updated_at": "2026-02-24T0", "task_count": 0, "statuses": ["Planned", "Tasked", "Approved"],
        "milestones": [{
            "id": "M1", "title": "M1", "status": "Planned",
            "features": [{
                "id": "F1-M1", "title": "F1", "status": "Approved", "issues": [
                    # Set status to 'Tasked' to satisfy materialize requirements
                    {
                        "id": "I1-F1-M1", "title": "Mapped", "status": "Tasked", 
                        "gh_issue_number": 123, "gh_issue_url": "https://github.com/owner/repo/issues/123",
                        "tasks": [{"id": "1", "title": "T", "summary": "S", "status": "Done"}]
                    }
                ]
            }]
        }]
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map), encoding="utf-8")
    
    # Materialize mode issues-create with no-github should skip the mapped issue
    # Since we use --no-github, it's a dry-run and reports 'would_skip'
    res = workflow.run("feature", "materialize", "--id", "F1-M1", "--mode", "issues-create", "--no-github")
    assert res["issues_materialized_summary"]["created"] == 0
    assert res["issues_materialized_summary"]["would_skip"] == 1

def test_approved_gate_audit():
    """Checks that 'Approved' gate is enforced where expected by auditing source."""
    import subprocess
    from pathlib import Path
    root_dir = Path(__file__).resolve().parent.parent.parent
    lib_dir = root_dir / "dev/workflow_lib"
    
    # Use grep -r which is more standard than rg
    cmd = ["grep", "-r", "expected Approved", str(lib_dir)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # The original script failed if results were found, meaning it's a cleanliness/no-todo check
    # for these specific strings.
    assert result.returncode != 0, f"Found unexpected gate audit strings:\n{result.stdout}"
