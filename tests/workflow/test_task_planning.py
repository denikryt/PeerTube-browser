import pytest
import json

def test_plan_issue_writes_canonical_issue_block(workflow, tmp_repo):
    """Verifies that plan issue writes one canonical issue block into the owning feature section."""
    dev_map = {
        "version": "1.0",
        "updated_at": "2026-02-24T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Pending", "Draft", "Planned", "Done"],
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
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map, indent=2), encoding="utf-8")
    (tmp_repo / "dev/FEATURE_PLANS.md").write_text(
        "## F9-M1\n"
        "### Expected Behaviour\n"
        "- Smoke feature should expose one canonical issue plan block.\n",
        encoding="utf-8",
    )

    res = workflow.run("plan", "issue", "--id", "I1-F9-M1", "--write")
    assert res["command"] == "feature.plan-issue"
    assert res["action"] in {"created", "updated"}
    assert res["plan_block_updated"] is True

    feature_plans = (tmp_repo / "dev/FEATURE_PLANS.md").read_text(encoding="utf-8")
    assert "### I1-F9-M1 - Smoke issue" in feature_plans
    assert "#### Dependencies" in feature_plans
    assert "#### Decomposition" in feature_plans


def test_issue_planning_can_be_done_sequentially_for_multiple_issues(workflow, tmp_repo):
    """Verifies that multiple issues can be planned sequentially under one feature section."""
    dev_map = {
        "version": "1.0",
        "updated_at": "2026-02-24T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Pending", "Draft", "Planned", "Done"],
        "milestones": [
            {
                "id": "M1", "title": "M1", "status": "Planned",
                "features": [
                    {
                        "id": "F1-M1", "title": "F1", "status": "Planned", "track": "Test",
                        "issues": [
                            {"id": "I1-F1-M1", "title": "I1", "status": "Pending", "tasks": []},
                            {"id": "I2-F1-M1", "title": "I2", "status": "Pending", "tasks": []}
                        ]
                    }
                ]
            }
        ]
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map), encoding="utf-8")
    (tmp_repo / "dev/FEATURE_PLANS.md").write_text(
        "## F1-M1\n"
        "### Expected Behaviour\n"
        "- Both issues should remain valid planning inputs for sequential issue planning.\n",
        encoding="utf-8",
    )

    res1 = workflow.run("plan", "issue", "--id", "I1-F1-M1", "--write")
    res2 = workflow.run("plan", "issue", "--id", "I2-F1-M1", "--write")
    assert res1["plan_block_updated"] is True
    assert res2["plan_block_updated"] is True

    feature_plans = (tmp_repo / "dev/FEATURE_PLANS.md").read_text(encoding="utf-8")
    assert "### I1-F1-M1 - I1" in feature_plans
    assert "### I2-F1-M1 - I2" in feature_plans

def test_sync_feature_missing_milestone_title_fails(workflow, tmp_repo):
    """Verifies that sync fails if the milestone title is empty in DEV_MAP."""
    dev_map = {
        "version": "1.0", "updated_at": "2026-02-24T0", "task_count": 0, "statuses": ["Planned"],
        "milestones": [{"id": "M1", "title": "", "status": "Planned", "features": [{"id": "F1-M1", "title": "F1", "status": "Planned", "gh_issue_number": 5, "gh_issue_url": "https://github.com/owner/repo/issues/5"}]}]
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map), encoding="utf-8")
    
    with pytest.raises(pytest.fail.Exception) as excinfo:
        workflow.run("sync", "feature", "--feature-id", "F1-M1")
    assert "has empty title in DEV_MAP" in str(excinfo.value)

def test_publish_issue_already_mapped_target_fails(workflow, tmp_repo):
    """Verifies that publish issue rejects already mapped targets instead of skipping them."""
    dev_map = {
        "version": "1.0", "updated_at": "2026-02-24T0", "task_count": 0, "statuses": ["Planned", "Tasked", "Approved"],
        "milestones": [{
            "id": "M1", "title": "M1", "status": "Planned",
            "features": [{
                "id": "F1-M1", "title": "F1", "status": "Approved", "issues": [
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
    
    with pytest.raises(pytest.fail.Exception) as excinfo:
        workflow.run("publish", "issue", "--children-of", "F1-M1", "--no-github")
    assert "already mapped issue ids" in str(excinfo.value).lower()

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
