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


def test_feature_create_accepts_markdown_input(workflow, tmp_repo):
    """Verifies that feature create can parse title/description from a markdown draft file."""
    dev_map = {
        "schema_version": "1.4",
        "updated_at": "2026-02-24T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Pending", "Planned", "Tasked", "Done", "Approved"],
        "milestones": [
            {
                "id": "M1",
                "title": "Milestone 1",
                "goal": "Smoke goal",
                "features": [],
                "standalone_issues": [],
                "non_feature_items": [],
            }
        ],
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map, indent=2), encoding="utf-8")
    (tmp_repo / "dev/TASK_LIST.json").write_text('{"schema_version":"1.0","tasks":[]}\n', encoding="utf-8")
    (tmp_repo / "dev/TASK_EXECUTION_PIPELINE.json").write_text(
        '{"schema_version":"1.0","execution_sequence":[],"functional_blocks":[],"overlaps":[]}\n',
        encoding="utf-8",
    )

    draft_path = tmp_repo / "tmp_feature_input.md"
    draft_path.write_text("# Draft feature title\nFeature description from markdown.\n", encoding="utf-8")

    res = workflow.run(
        "feature",
        "create",
        "--id",
        "F9-M1",
        "--milestone",
        "M1",
        "--input",
        str(draft_path),
        "--write",
    )
    assert res["action"] == "created"
    updated_map = json.loads((tmp_repo / "dev/map/DEV_MAP.json").read_text(encoding="utf-8"))
    feature_node = updated_map["milestones"][0]["features"][0]
    assert feature_node["title"] == "Draft feature title"
    assert feature_node["description"] == "Feature description from markdown."


def test_feature_create_issue_accepts_markdown_input(workflow, tmp_repo):
    """Verifies that feature create-issue can create one issue node from markdown input."""
    dev_map = {
        "schema_version": "1.4",
        "updated_at": "2026-02-24T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Pending", "Planned", "Tasked", "Done", "Approved"],
        "milestones": [
            {
                "id": "M1",
                "title": "Milestone 1",
                "goal": "Smoke goal",
                "features": [
                    {
                        "id": "F9-M1",
                        "title": "Smoke feature",
                        "description": "Smoke feature description.",
                        "status": "Planned",
                        "track": "System/Test",
                        "gh_issue_number": None,
                        "gh_issue_url": None,
                        "issues": [],
                        "branch_name": None,
                        "branch_url": None,
                    }
                ],
                "standalone_issues": [],
                "non_feature_items": [],
            }
        ],
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map, indent=2), encoding="utf-8")
    (tmp_repo / "dev/TASK_LIST.json").write_text('{"schema_version":"1.0","tasks":[]}\n', encoding="utf-8")
    (tmp_repo / "dev/TASK_EXECUTION_PIPELINE.json").write_text(
        '{"schema_version":"1.0","execution_sequence":[],"functional_blocks":[],"overlaps":[]}\n',
        encoding="utf-8",
    )

    draft_path = tmp_repo / "tmp_issue_input.md"
    draft_path.write_text("# Draft issue title\nIssue description from markdown.\n", encoding="utf-8")

    res = workflow.run(
        "feature",
        "create-issue",
        "--id",
        "I1-F9-M1",
        "--input",
        str(draft_path),
        "--write",
    )
    assert res["action"] == "created"
    updated_map = json.loads((tmp_repo / "dev/map/DEV_MAP.json").read_text(encoding="utf-8"))
    issue_node = updated_map["milestones"][0]["features"][0]["issues"][0]
    assert issue_node["title"] == "Draft issue title"
    assert issue_node["description"] == "Issue description from markdown."


def test_feature_create_rejects_mixed_input_modes(workflow, tmp_repo):
    """Verifies that --input cannot be combined with inline title/description flags."""
    dev_map = {
        "schema_version": "1.4",
        "updated_at": "2026-02-24T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Pending", "Planned", "Tasked", "Done", "Approved"],
        "milestones": [
            {
                "id": "M1",
                "title": "Milestone 1",
                "goal": "Smoke goal",
                "features": [],
                "standalone_issues": [],
                "non_feature_items": [],
            }
        ],
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map, indent=2), encoding="utf-8")
    draft_path = tmp_repo / "tmp_feature_input.md"
    draft_path.write_text("# Draft feature title\nFeature description from markdown.\n", encoding="utf-8")

    with pytest.raises(pytest.fail.Exception) as excinfo:
        workflow.run(
            "feature",
            "create",
            "--id",
            "F9-M1",
            "--milestone",
            "M1",
            "--input",
            str(draft_path),
            "--title",
            "Inline title",
        )
    assert "Cannot combine --input with --title/--description" in str(excinfo.value)


def test_feature_create_input_missing_file_fails(workflow, tmp_repo):
    """Verifies that markdown input reports a deterministic missing-file error."""
    dev_map = {
        "schema_version": "1.4",
        "updated_at": "2026-02-24T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Pending", "Planned", "Tasked", "Done", "Approved"],
        "milestones": [
            {
                "id": "M1",
                "title": "Milestone 1",
                "goal": "Smoke goal",
                "features": [],
                "standalone_issues": [],
                "non_feature_items": [],
            }
        ],
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map, indent=2), encoding="utf-8")

    with pytest.raises(pytest.fail.Exception) as excinfo:
        workflow.run(
            "feature",
            "create",
            "--id",
            "F9-M1",
            "--milestone",
            "M1",
            "--input",
            str(tmp_repo / "missing_input.md"),
        )
    assert "Input file not found:" in str(excinfo.value)


def test_feature_create_input_without_heading_fails(workflow, tmp_repo):
    """Verifies that markdown input without headings fails with actionable guidance."""
    dev_map = {
        "schema_version": "1.4",
        "updated_at": "2026-02-24T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Pending", "Planned", "Tasked", "Done", "Approved"],
        "milestones": [
            {
                "id": "M1",
                "title": "Milestone 1",
                "goal": "Smoke goal",
                "features": [],
                "standalone_issues": [],
                "non_feature_items": [],
            }
        ],
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map, indent=2), encoding="utf-8")
    draft_path = tmp_repo / "invalid_input.md"
    draft_path.write_text("Body without markdown headings.\n", encoding="utf-8")

    with pytest.raises(pytest.fail.Exception) as excinfo:
        workflow.run(
            "feature",
            "create",
            "--id",
            "F9-M1",
            "--milestone",
            "M1",
            "--input",
            str(draft_path),
        )
    assert "No headings detected" in str(excinfo.value)


def test_feature_create_input_truncates_description_at_next_heading(workflow, tmp_repo):
    """Verifies that only content before the next heading is used as description."""
    dev_map = {
        "schema_version": "1.4",
        "updated_at": "2026-02-24T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Pending", "Planned", "Tasked", "Done", "Approved"],
        "milestones": [
            {
                "id": "M1",
                "title": "Milestone 1",
                "goal": "Smoke goal",
                "features": [],
                "standalone_issues": [],
                "non_feature_items": [],
            }
        ],
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map, indent=2), encoding="utf-8")
    (tmp_repo / "dev/TASK_LIST.json").write_text('{"schema_version":"1.0","tasks":[]}\n', encoding="utf-8")
    (tmp_repo / "dev/TASK_EXECUTION_PIPELINE.json").write_text(
        '{"schema_version":"1.0","execution_sequence":[],"functional_blocks":[],"overlaps":[]}\n',
        encoding="utf-8",
    )
    draft_path = tmp_repo / "sectioned_input.md"
    draft_path.write_text(
        "### Title from heading\nFirst description block.\n\n# Extra heading\nIgnored section.\n",
        encoding="utf-8",
    )

    workflow.run(
        "feature",
        "create",
        "--id",
        "F9-M1",
        "--milestone",
        "M1",
        "--input",
        str(draft_path),
        "--write",
    )
    updated_map = json.loads((tmp_repo / "dev/map/DEV_MAP.json").read_text(encoding="utf-8"))
    feature_node = updated_map["milestones"][0]["features"][0]
    assert feature_node["title"] == "Title from heading"
    assert feature_node["description"] == "First description block."


def test_feature_create_input_empty_description_returns_warning(workflow, tmp_repo):
    """Verifies that title-only drafts succeed and return a warning for empty description."""
    dev_map = {
        "schema_version": "1.4",
        "updated_at": "2026-02-24T00:00:00+00:00",
        "task_count": 0,
        "statuses": ["Pending", "Planned", "Tasked", "Done", "Approved"],
        "milestones": [
            {
                "id": "M1",
                "title": "Milestone 1",
                "goal": "Smoke goal",
                "features": [],
                "standalone_issues": [],
                "non_feature_items": [],
            }
        ],
    }
    (tmp_repo / "dev/map/DEV_MAP.json").write_text(json.dumps(dev_map, indent=2), encoding="utf-8")
    (tmp_repo / "dev/TASK_LIST.json").write_text('{"schema_version":"1.0","tasks":[]}\n', encoding="utf-8")
    (tmp_repo / "dev/TASK_EXECUTION_PIPELINE.json").write_text(
        '{"schema_version":"1.0","execution_sequence":[],"functional_blocks":[],"overlaps":[]}\n',
        encoding="utf-8",
    )
    draft_path = tmp_repo / "title_only.md"
    draft_path.write_text("# Title only\n", encoding="utf-8")

    res = workflow.run(
        "feature",
        "create",
        "--id",
        "F9-M1",
        "--milestone",
        "M1",
        "--input",
        str(draft_path),
        "--write",
    )
    assert res["input_warnings"]
    updated_map = json.loads((tmp_repo / "dev/map/DEV_MAP.json").read_text(encoding="utf-8"))
    feature_node = updated_map["milestones"][0]["features"][0]
    assert feature_node["description"].startswith("This feature addresses title only")
