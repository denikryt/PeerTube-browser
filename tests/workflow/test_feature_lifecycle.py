import pytest
import json

def test_feature_success_chain(workflow, tmp_repo):
    """
    Tests the full feature creation and initial planning chain:
    create -> plan-init -> plan-lint
    """
    # 1. Setup DEV_MAP.json fixture
    dev_map = {
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
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map, indent=2), encoding="utf-8")

    # 2. feature create
    res = workflow.run("feature", "create", "--id", "F9-M1", "--milestone", "M1", "--title", "Smoke feature", "--write")
    assert res["action"] == "created"
    assert res["feature_id"] == "F9-M1"

    # 3. feature plan-init
    res = workflow.run("feature", "plan-init", "--id", "F9-M1", "--write")
    assert res["action"] == "created"

    # 4. feature plan-lint (should be valid immediately after init)
    res = workflow.run("feature", "plan-lint", "--id", "F9-M1")
    assert res["valid"] is True
