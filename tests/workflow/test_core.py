import pytest

def test_help(workflow):
    """Verifies that --help returns successfully and contains expected text."""
    output = workflow.run("--help", parse_json=False)
    assert "usage:" in output.lower()
    assert "positional arguments:" in output.lower()
    assert "{create,execute,feature,move,plan,publish,sync,task,clean,done,reject,validate}" in output.lower()

def test_feature_help(workflow):
    """Verifies that feature --help exposes only planning and execution-plan commands."""
    output = workflow.run("feature", "--help", parse_json=False)
    assert "usage: workflow feature" in output.lower()
    assert "{plan-init,plan-lint,plan-issue,execution-plan}" in output.lower()

def test_create_help(workflow):
    """Verifies that action-first create help is discoverable from top-level help."""
    output = workflow.run("create", "--help", parse_json=False)
    assert "usage: workflow create" in output.lower()
    assert "{feature,issue}" in output.lower()

def test_publish_help(workflow):
    """Verifies that action-first publish help is discoverable from top-level help."""
    output = workflow.run("publish", "--help", parse_json=False)
    assert "usage: workflow publish" in output.lower()
    assert "{feature,issue}" in output.lower()

def test_invalid_command(workflow):
    """Verifies that invalid commands return a failure exit code."""
    with pytest.raises(pytest.fail.Exception):
        workflow.run("invalid-group-name", check=True)
