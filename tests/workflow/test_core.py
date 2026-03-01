import pytest

def test_help(workflow):
    """Verifies that --help returns successfully and contains expected text."""
    output = workflow.run("--help", parse_json=False)
    assert "usage:" in output.lower()
    assert "positional arguments:" in output.lower()

def test_feature_help(workflow):
    """Verifies that feature --help returns successfully."""
    output = workflow.run("feature", "--help", parse_json=False)
    assert "usage: workflow feature" in output.lower()
    assert "{create,plan-init,plan-lint,plan-issue,materialize,execution-plan}" in output.lower()

def test_invalid_command(workflow):
    """Verifies that invalid commands return a failure exit code."""
    with pytest.raises(pytest.fail.Exception):
        workflow.run("invalid-group-name", check=True)
